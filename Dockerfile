# TAP Development Dockerfile
#
# Base image: a curated-minimal Wolfi base (cgr.dev/chainguard/wolfi-base) carrying exactly
# TAP's runtime binaries, per req-cicd-base-image-lifecycle-3 (Wolfi is the standard base,
# decided 2026-07-09; spike measured OS-CVEs 311→0 vs the outgoing python:3.14-slim). Wolfi
# is glibc-based; it is chosen on Python-3.14 currency, in-image host-independent FIPS
# (req-cicd-base-image-lifecycle-5/-6), and a zero-CVE floor — NOT on shipping a runtime
# package manager (TAP's deps + plugins are Python-package installs synced by uv at runtime,
# not OS-package installs; assessment record docs/misc/doc-fips-assessment-record.md L11).
#
# FIPS: this image runs crypto through the free upstream OpenSSL 3.0.9 FIPS provider
# (CMVP #4282), self-built in the `ossl-builder` stage and activated in-image. The mode is
# selected by a single build flag `ARG TAP_FIPS` (DEFAULT 1 — FIPS is the published artifact;
# `TAP_FIPS=0` is an explicit, never-silent escape hatch). `cryptography` is built --no-binary
# against the SYSTEM OpenSSL in BOTH modes (its wheel bundles its own OpenSSL — D7/L9), so the
# dependency closure is identical and only provider activation differs. A fail-closed boot
# self-check (`tap.fips`, wired in docker/entrypoint.sh) proves the DECLARED mode is the mode
# actually enforced, by executing crypto and observing a refusal — it never inspects files,
# because the FIPS boundary is the OpenSSL config, not the modules directory (L13, D15).
# Full decision record + re-runnable verification suite: doc-fips-assessment-record.md.

# TAP_FIPS is a global build ARG so it can select the final stage below. Default 1 (FIPS on).
ARG TAP_FIPS=1

# Base images are pinned tag@digest (req-cicd-base-image-lifecycle-1): wolfi-base:latest
# rotates its digest DAILY, which invalidated every downstream layer (apk toolchain, the
# OpenSSL FIPS compile) on the first CI build of each day — and silently changed the FIPS
# build environment. Pinning makes bumps deliberate, reviewed commits (Renovate wiring is
# the deferred automation). Bump procedure, all FROM/COPY --from lines in BOTH Dockerfiles
# (this one and docker/postgres/Dockerfile) in the same commit:
#   docker buildx imagetools inspect cgr.dev/chainguard/wolfi-base:latest   # new digest
#   docker buildx imagetools inspect ghcr.io/astral-sh/uv:<latest release>

# ============================================================================
# ossl-builder — compile the validated OpenSSL 3.0.9 FIPS provider (fips.so)
# ============================================================================
# Only built when the FIPS variant is selected (BuildKit prunes it for TAP_FIPS=0, since
# nothing COPYs from it in the fips-0 path). We run the frozen validated 3.0.9 module against
# the base's MODERN libcrypto at runtime — OpenSSL guarantees a certified fips.so is
# binary-compatible with any LATER libcrypto, so OpenSSL 3.0's LTS-EOL is irrelevant (D4).
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:fdcd31a2db35958c251ea22e80cda72a8222228114e736ec7dd9c94452a2dc51 AS ossl-builder
# Wolfi's apk repo flakes under load (observed 2026-08-16: HTTP 403s mid-install;
# 2026-08-20: fetch error on one package) — bounded retry with backoff, failing
# closed after 3 attempts. apk add is idempotent across retries.
RUN for i in 1 2 3; do apk add --no-cache build-base perl linux-headers curl && break || { echo "apk add failed (attempt $i/3)" >&2; [ "$i" -eq 3 ] && exit 1; sleep $((i*10)); }; done
WORKDIR /build
RUN curl -fsSL https://github.com/openssl/openssl/releases/download/openssl-3.0.9/openssl-3.0.9.tar.gz -o o.tgz \
 && tar xf o.tgz
WORKDIR /build/openssl-3.0.9
# enable-fips builds the FIPS provider (fips.so); install_fips installs it.
RUN ./Configure enable-fips && make -j"$(nproc)" && make install_fips

# ============================================================================
# base — the common runtime (identical for both FIPS modes)
# ============================================================================
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:fdcd31a2db35958c251ea22e80cda72a8222228114e736ec7dd9c94452a2dc51 AS base

# Prevents Python from writing .pyc bytecode files to disk (waste + stale-cache risk).
ENV PYTHONDONTWRITEBYTECODE=1
# Forces unbuffered stdout/stderr so logs appear immediately in `docker compose logs`.
ENV PYTHONUNBUFFERED=1
# UV hardlinks between layers cause issues in Docker; copy instead.
ENV UV_LINK_MODE=copy

WORKDIR /app

# System-level runtime binaries — named, itemized attack-surface line-items
# (req-cicd-base-image-lifecycle-3), kept current by the auto-patch loop (-1).
#   Runtime:
#   - python-3.14: the interpreter (Wolfi ships /usr/bin/python -> python3 -> python3.14).
#   - git: uv shells out to it for git-source package-mode plugin installs (req-boot-install-section).
#     Wolfi's git porcelain in /usr/libexec/git-core are shell scripts needing sed/grep — both
#     present via busybox on wolfi-base (verified), so no extra apk (assessment record L3).
#   - bash: docker/entrypoint.sh is a bash script.
#   - postgresql-client: pg_isready/psql for Django + pg_dump/pg_restore for the pre-boot
#     pre-migrate snapshot (tap/preboot.py, req-boot-snapshot). Wolfi ships 18.x; a newer
#     pg_dump dumps the older PG16 server fine.
#   - curl: docker/install-tailwindcss.sh; also in-container debugging.
#   - tzdata: the IANA zoneinfo DB Debian slim shipped implicitly but Wolfi's minimal base
#     does not; without it Python's zoneinfo cannot resolve settings.TIME_ZONE and boot aborts.
#   - openssl: the CLI + libs. fipsinstall (build-time, fips-1 stage) needs it; also debugging.
#   Build toolchain for `cryptography` --no-binary (D7 — applies in BOTH FIPS modes, so it lives
#   here in base, not in the FIPS stage): the sdist compiles a Rust + C extension against the
#   system OpenSSL headers at `uv sync` time (dev installs at runtime, not image build).
#   - build-base: gcc/make/libc headers.
#   - rust: cargo + rustc for cryptography's Rust extension.
#   - openssl-dev: system OpenSSL headers cryptography links against.
#   - pkgconf: pkg-config, used by the build to locate OpenSSL.
#   - python-3.14-dev: Python.h for the C extension.
#   - postgresql-dev: pg_config + libpq headers so psycopg's `[c]` extra builds against the
#     SYSTEM libpq (linking the system OpenSSL / FIPS provider) rather than the `[binary]`
#     wheel's private bundled libpq+OpenSSL, which fails SCRAM under FIPS (see pyproject.toml).
RUN for i in 1 2 3; do \
      apk add --no-cache \
    python-3.14 \
    git \
    bash \
    postgresql-client \
    curl \
    tzdata \
    openssl \
    build-base \
    rust \
    openssl-dev \
    pkgconf \
    python-3.14-dev \
    postgresql-dev \
      && break || { echo "apk add failed (attempt $i/3)" >&2; [ "$i" -eq 3 ] && exit 1; sleep $((i*10)); }; \
    done

# Copy the UV binary from the official UV image (no package manager needed).
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /bin/

# Dependency installation runs at container START via docker/entrypoint.sh, NOT at image
# build: the compose bind mount `.:/app` overrides /app and /app/.venv + /root/.cache/uv are
# named volumes, so a build-time `uv sync` is hidden and can fossilize a corrupted uv state
# into the layer cache. We still carry the lock + pyproject so the image has them.
COPY pyproject.toml uv.lock* ./

# ============================================================================
# deps-warm — pre-compiled wheel cache (the req-cicd-build-once-artifact warm path)
# ============================================================================
# Branches from base BEFORE any source COPY, so this layer is keyed on
# pyproject.toml + uv.lock alone (the uv workspace is intentionally empty — the
# lock holds only the core closure) and survives every source-only commit. The
# expensive FIPS-mandated source compiles (cryptography --no-binary, psycopg[c])
# happen here — once per lockfile change per publish, not once per developer
# boot. What ships is the resulting UV CACHE (built + downloaded wheels), NOT
# the venv: the runtime venv is always created by `uv sync` in the container
# (the long-proven path — a cp-seeded venv behaved differently under uv on the
# CodeBuild runner; see tap/preboot.py _VENV_DIR history), which then installs
# from this cache in seconds instead of compiling. Not the fossilization the
# compose comments warn about: --frozen rebuilds this stage from scratch in a
# clean layer whenever the lock changes.
FROM base AS deps-warm
RUN uv sync --frozen --all-packages
# Hash manifest of the freshly-built cache, generated INSIDE this attested build
# (req-cicd-supply-chain-provenance-2). Relative paths; written OUTSIDE the tree so
# it never lists itself. COPY'd after the sync RUN so lock-keyed layer caching of
# the expensive sync survives verifier-script edits.
COPY docker/seed_manifest.py /seed_manifest.py
RUN python3 /seed_manifest.py generate /root/.cache/uv /root/uv-cache-seed.manifest.json

# ============================================================================
# app — source + entrypoint on top of base; carries the wheel-cache seed
# ============================================================================
FROM base AS app

# Copy the rest of the application code (frequently-changing layer, after deps).
COPY . .

# Pre-compiled wheel cache. docker/entrypoint.sh copies it into the (named-
# volume) uv cache on first boot when that volume is empty; `uv sync` then
# creates the venv from cached wheels — no compile. Explicit entrypoint copy
# from /opt on purpose: avoids depending on Docker volume-init semantics.
COPY --from=deps-warm /root/.cache/uv /opt/uv-cache-seed
# The seed's build-time manifest + the stdlib verifier, baked at a bind-mount-proof
# path (the /app copy is shadowed by the dev bind mount, like entrypoint.sh).
# The entrypoint verifies seed-vs-manifest BEFORE seeding an empty cache volume;
# present-but-invalid aborts, absent degrades (req-cicd-supply-chain-provenance-2).
COPY --from=deps-warm /root/uv-cache-seed.manifest.json /opt/uv-cache-seed.manifest.json
COPY docker/seed_manifest.py /usr/local/lib/tap/seed_manifest.py

# Note on tailwindcss: the image does NOT carry the binary. The /tailwind-rebuild skill
# installs it on demand into the tailwind_bin volume; the committed
# tap_web/static/tap_web/css/tailwind.css is served as-is. See spec-web-tailwind-pipeline.md.

EXPOSE 8000

# The entrypoint runs uv sync, the FIPS self-check, pre-boot, migrate, then the server.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]

# ============================================================================
# fips-0 — non-FIPS variant (explicit escape hatch, TAP_FIPS=0)
# ============================================================================
# Stock provider set; no fips.so, no OPENSSL_CONF override. `cryptography` is still built
# --no-binary (D7) so the closure matches the FIPS build exactly. The image declares its
# mode machine-legibly so CI, the boot record, /healthz, and an AI operator can read it
# without executing crypto (D14).
FROM app AS fips-0
ENV TAP_FIPS_MODE=0
LABEL org.tap.fips="false"

# ============================================================================
# fips-1 — FIPS variant (default, TAP_FIPS=1)
# ============================================================================
FROM app AS fips-1

# Drop our validated 3.0.9 provider into the base's ossl-modules dir.
COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so

# fipsinstall runs the module self-tests and writes the integrity MAC (pinning fips.so's
# exact bytes). It MUST run in the final image (D5); it also proves binary-compat, since the
# base's modern `openssl` loads + self-tests our frozen 3.0.9 module (D4).
RUN openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so

# openssl.cnf activating the strict `fips` + `base` provider set with fips=yes globally.
# ORDER IS LOAD-BEARING (L1): `openssl_conf` must be in the default (pre-section) block. The
# `.include` pulls in fipsmodule.cnf, which STARTS with [fips_sect] — so it must come AFTER
# `openssl_conf`, else openssl_conf is swallowed into [fips_sect] and NO providers activate
# (the config "parses" fine but silently falls back to the default provider — the fail-open
# trap). `.include /etc/ssl/ca.cnf` restores the stock openssl.cnf include that pointing
# OPENSSL_CONF at our file otherwise displaces (else `openssl req` breaks; TLS trust is
# unaffected — L14). `base` supplies encoders/decoders (no crypto primitives) and is required
# for OpenSSL key-file I/O; it is not a hole in the boundary (L15).
RUN printf '%s\n' \
  'config_diagnostics = 1' \
  'openssl_conf = openssl_init' \
  '' \
  '.include /etc/ssl/fipsmodule.cnf' \
  '.include /etc/ssl/ca.cnf' \
  '' \
  '[openssl_init]' \
  'providers = provider_sect' \
  'alg_section = algorithm_sect' \
  '' \
  '[provider_sect]' \
  'fips = fips_sect' \
  'base = base_sect' \
  '' \
  '[base_sect]' \
  'activate = 1' \
  '' \
  '[algorithm_sect]' \
  'default_properties = fips=yes' \
  > /etc/ssl/openssl-fips.cnf
ENV OPENSSL_CONF=/etc/ssl/openssl-fips.cnf

# Keep OpenSSL's legacy provider unloaded, else `cryptography` re-enables MD5/DES (D8).
ENV CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1

# Declare the mode machine-legibly (D14); the boot self-check asserts it is actually enforced.
ENV TAP_FIPS_MODE=1
LABEL org.tap.fips="true"

# ============================================================================
# final — select the variant by the build flag (default fips-1)
# ============================================================================
FROM fips-${TAP_FIPS} AS final
