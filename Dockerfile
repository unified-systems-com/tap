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
# FIPS: this image runs crypto through the free upstream OpenSSL FIPS provider at the version
# pinned in docker/build-openssl-fips.sh (whether that version is CMVP-validated is derived
# there, never claimed here — D17), self-built in the `ossl-builder` stage and activated in-image. The mode is
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
# ossl-builder — compile the pinned OpenSSL FIPS provider (fips.so)
# ============================================================================
# Only built when the FIPS variant is selected (BuildKit prunes it for TAP_FIPS=0, since
# nothing COPYs from it in the fips-0 path). We run the pinned fips.so module against
# the base's MODERN libcrypto at runtime — OpenSSL guarantees a certified fips.so is
# binary-compatible with any LATER libcrypto, so OpenSSL 3.0's LTS-EOL is irrelevant (D4).
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:fac38d12efdb4bf43ac9e599a31db10a27ad5dd71e5f1618790962eda8d66180 AS ossl-builder
# Wolfi's apk repo flakes under load (observed 2026-08-16: HTTP 403s mid-install;
# 2026-08-20: fetch error on one package) — bounded retry with backoff, failing
# closed after 3 attempts. apk add is idempotent across retries.
RUN for i in 1 2 3; do \
      if apk add --no-cache build-base perl linux-headers curl gpg gpg-agent; then break; fi; \
      echo "apk add failed (attempt $i/3)" >&2; \
      if [ "$i" -eq 3 ]; then exit 1; fi; \
      sleep $((i*10)); \
    done
# Fetching the OpenSSL source, proving it is the source upstream published, and compiling the
# FIPS provider are ALL in docker/build-openssl-fips.sh — the pinned version, both integrity
# gates, the confinement the signature check runs under, and the bump procedure. It is the most
# security-significant step in this build, which is exactly why it is a readable, reviewable
# script and not an `&&`-chained RUN. docker/postgres/Dockerfile runs the SAME script against the
# SAME pins, so the two images cannot drift into different trust stories for the same fips.so.
COPY docker/openssl-release-keys.asc docker/build-openssl-fips.sh /opt/ossl/
RUN /opt/ossl/build-openssl-fips.sh

# ============================================================================
# base — the common runtime (identical for both FIPS modes)
# ============================================================================
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:fac38d12efdb4bf43ac9e599a31db10a27ad5dd71e5f1618790962eda8d66180 AS base

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
      if apk add --no-cache \
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
      ; then break; fi; \
      echo "apk add failed (attempt $i/3)" >&2; \
      if [ "$i" -eq 3 ]; then exit 1; fi; \
      sleep $((i*10)); \
    done

# Copy the UV binary from the official UV image (no package manager needed).
COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /uvx /bin/

# Dependency installation runs at container START via docker/entrypoint.sh, NOT at image
# build: the compose bind mount `.:/app` overrides /app and /app/.venv + the uv cache are
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
# js-vendor — browser-library closure via npm (req-cicd-sbom-13, adopt-native:
# the ecosystem's registry + lockfile + integrity, merged at the lockfile seam).
# The four libs the UI loads (htmx/echarts/tabulator + cytoscape) arrive by
# `npm ci --ignore-scripts` against the committed package-lock.json — the bytes
# never live in git. Files are staged under the SAME app-relative static names
# the templates reference, so {% static %} lookups are unchanged; the lock rides
# along into the image as the SBOM's declared-closure source (the js analog of
# uv.lock). Digest-pinned node from the credential-free ECR mirror
# (req-cicd-base-image-sourcing); bump procedure = the FROM-lines note above.
# ============================================================================
FROM public.ecr.aws/docker/library/node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1 AS js-vendor
WORKDIR /vendor
COPY package.json package-lock.json ./
# npm runs UNPRIVILEGED (defense-in-depth on top of --ignore-scripts: a
# hostile tarball extraction lands as `node`, not root; also SonarCloud
# S6471). Root only prepares the target dirs.
RUN mkdir -p /opt/tap-static-vendor/tap_web/js/lib /opt/tap-static-vendor/tap_web/css/lib /opt/tap-static-vendor/tap_viz/js/lib \
 && chown -R node:node /vendor /opt/tap-static-vendor
USER node
RUN npm ci --ignore-scripts --loglevel=error \
 && cp node_modules/htmx.org/dist/htmx.min.js       /opt/tap-static-vendor/tap_web/js/lib/ \
 && cp node_modules/tabulator-tables/dist/css/tabulator.min.css /opt/tap-static-vendor/tap_web/css/lib/ \
 && cp node_modules/echarts/dist/echarts.min.js     /opt/tap-static-vendor/tap_web/js/lib/ \
 && cp node_modules/tabulator-tables/dist/js/tabulator.min.js /opt/tap-static-vendor/tap_web/js/lib/ \
 && cp node_modules/cytoscape/dist/cytoscape.min.js /opt/tap-static-vendor/tap_viz/js/lib/ \
 && cp package-lock.json /opt/tap-static-vendor/package-lock.json

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
# sbom-allow(req-cicd-sbom-2): the wheel-cache seed is available-bytes infra, deliberately EXCLUDED from the SBOM
COPY --from=deps-warm /root/.cache/uv /opt/uv-cache-seed
# The seed's build-time manifest + the stdlib verifier, baked at a bind-mount-proof
# path (the /app copy is shadowed by the dev bind mount, like entrypoint.sh).
# The entrypoint verifies seed-vs-manifest BEFORE seeding an empty cache volume;
# present-but-invalid aborts, absent degrades (req-cicd-supply-chain-provenance-2).
# sbom-allow(req-cicd-supply-chain-provenance-2): the seed's integrity manifest — verification data, not a component
COPY --from=deps-warm /root/uv-cache-seed.manifest.json /opt/uv-cache-seed.manifest.json
COPY docker/seed_manifest.py /usr/local/lib/tap/seed_manifest.py

# Vendored browser libs + their lockfile (js-vendor stage above). Outside /app on
# purpose: the dev bind mount shadows /app, and these files must come from the
# attested image, not the working tree (which no longer carries them).
# sbom-allow(req-cicd-sbom-13): declared by its OWN lockfile seam — package-lock.json rides in the tree and the scan catalogs it
COPY --from=js-vendor /opt/tap-static-vendor /opt/tap-static-vendor

# Note on tailwindcss: the image does NOT carry the binary. The /tailwind-rebuild skill
# installs it on demand into the tailwind_bin volume; the committed
# tap_web/static/tap_web/css/tailwind.css is served as-is. See spec-web-tailwind-pipeline.md.

# ============================================================================
# Runtime user — the serving stage does not run as root (tap#754)
# ============================================================================
# The stage that SERVES REQUESTS runs unprivileged. `USER nonroot` itself is one line
# (at the bottom of `final`, after the fips stages' root-only RUNs); what needs stating
# is the directory preparation here, because every writable path the container touches
# at runtime is a MOUNT, and a mount's ownership is not something the entrypoint can fix
# once it has dropped root.
#
# Two ownership facts do the work:
#
#  1. A fresh NAMED VOLUME inherits the ownership and mode of the image directory at its
#     mount path — including when that path is nested under a bind mount (verified on
#     Docker Desktop 2026-09-22 with /app/.venv under `.:/app`). So `/app/.venv`,
#     the uv cache and `/opt/tailwind` are created HERE, owned and group-writable, and
#     the volumes Docker creates for them come out writable by the runtime user. A path
#     NOT created here gets a root-owned mountpoint and a container that dies at `uv sync`.
#
#  2. Group 0 + `g+rwX`, not `nonroot:nonroot` alone, because the uid is not fixed in
#     development. The `.:/app` bind mount is host-owned, so on Linux (CI, Codespaces,
#     a Linux workstation) the container has to run as the HOST's uid or it cannot write
#     the tree it is serving from — `scripts/dc` passes that uid through as `TAP_UID`
#     (docker-compose.yml `user:`). That uid has no passwd entry, so HOME is declared
#     explicitly below rather than resolved from /etc/passwd. The published image's own
#     default stays `nonroot` (65532), which is what a plain `docker run` gets.
#
# `/run/tap` holds the persisted TAP_PLUGINS set. It is a directory in the image's
# writable layer — NOT a tmpfs, despite what the entrypoint comment used to say — so it
# is fresh per container either way, and it has to be prepared here because `/run` itself
# is root-owned and a non-root process cannot create a path in it.
RUN mkdir -p /app/.venv /home/nonroot/.cache/uv /opt/tailwind /run/tap \
 && chown -R nonroot:0 /app/.venv /home/nonroot /opt/tailwind /run/tap \
 && chmod -R g+rwX /app/.venv /home/nonroot /opt/tailwind /run/tap

# HOME is declared, not inherited: under the dev `user:` override the runtime uid has no
# /etc/passwd entry, so Docker would hand it HOME=/ and uv, git and anything else reaching
# for a home directory would write into the image root (or fail).
ENV HOME=/home/nonroot
# uv's cache, which used to sit at /root/.cache/uv — literally root's home — and is the
# mount target of the per-project `uv_cache` volume. Named explicitly rather than left to
# uv's $HOME-relative default so the compose mount target and the entrypoint's seed
# destination are the same string in both places.
ENV UV_CACHE_DIR=/home/nonroot/.cache/uv

EXPOSE 8000

# The entrypoint runs uv sync, the FIPS self-check, pre-boot, migrate, then the server.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
CMD ["/entrypoint.sh"]

# ============================================================================
# HEALTHCHECK — the container says whether it is fit to serve (req-tap-health-exposure-6)
# ============================================================================
# Declared HERE, in the image, not on the compose service: a compose-only health check is
# absent from the published artifact and therefore absent under `docker run` and under a plain
# `docker compose` from another file — the lesson of tap#502, where a property asserted in one
# place was untrue in the artifact that ships. Compose can still override this per deployment;
# it can no longer be the only place it exists.
#
# WHO ACTUALLY READS IT — stated narrowly on purpose, because "any orchestrator gets it"
# would be exactly the false declaration this epic exists to remove. Three different answers:
#   - READS IT, AND DOES NOTHING BUT REPORT: the Docker engine (`docker ps`, `docker inspect`)
#     and Compose, which also gates `depends_on: condition: service_healthy` on it. This is the
#     deployment this repo actually ships, and the one the numbers below are chosen for.
#     Podman and nerdctl read it the same way.
#   - DOES NOT READ IT AT ALL: **Kubernetes.** It ignores image health metadata and requires
#     `readinessProbe` / `livenessProbe` in the Pod spec. A future Kubernetes deployment
#     declares its own; this line will not cover it.
#   - READS IT AND *ACTS*: **Swarm** (`docker stack deploy` / `docker service`) treats a failed
#     image health check as task failure and REPLACES the replica. Under Swarm this check would
#     therefore do the precise thing tap_health/selection.py refuses to allow — turn a Postgres
#     or cache outage into a replica-replacement loop, because every probe in `readiness` checks
#     a dependency a restart does not fix. **A Swarm deployment MUST override or disable this
#     HEALTHCHECK, or move to a liveness-only set first.** The same warning applies to any
#     runtime that maps image health onto replacement. This is not a hypothetical caveat: it is
#     the one deployment shape in which the "informational" property below stops being true.
#     A warning is not a safeguard, and that is a decision, not an oversight: the options and
#     the done-test for choosing one are Issue# 545 - tap (an L — the question is unsettled).
#
# WHAT IT RUNS. `manage.py health --set readiness`, executed INSIDE the container by Docker.
# That is exactly the network-free projection req-tap-health-exposure-2 already built and the
# spawn gate already uses; it adds no endpoint, no route, and no listening socket.
#
# THE PROBE IS A FRESH PROCESS, NOT THE SERVER'S. Docker does not run it through
# docker/entrypoint.sh, so three things are worth stating rather than assuming:
#   - The venv interpreter is named ABSOLUTELY, because the probe inherits none of the
#     environment the entrypoint exports for the server (VIRTUAL_ENV / PATH).
#   - It runs as the SAME uid as the server: this image declares no `USER` in the runtime
#     stages and the entrypoint drops no privileges, so both are root. The probe is not more
#     privileged than the process it reports on.
#   - `TAP_PLUGINS` is not inherited either — but the entrypoint already PERSISTS the resolved
#     plugin set precisely so sibling execs that do not inherit its shell env read the same
#     authoritative set (see entrypoint.sh, the plugin-loading-race note). The probe is one of
#     those siblings. It costs one short-lived database connection per run, released when the
#     process exits.
#
# WHY `readiness` AND NOT `liveness`. Liveness answers one question: would RESTARTING fix it?
# Every probe registered today checks something a restart does not fix — Postgres, the cache
# table, migration state, secret material on disk — so calling them liveness would turn a
# database outage into a restart loop (tap_health/selection.py states this at length).
# `liveness` resolves to zero probes and reports `unknown`, never `healthy`; `readiness` is
# the only populated set.
#
# AND IT DOES SEE A WEDGED SERVER. "Dependency probe" is about restart-fixability, not about
# blindness to the web process: `readiness` includes http.web and http.api, which GET the
# LOOPBACK `TAP_HEALTH_SELF_URL` and read the auth responses (302 into the login wall, 401 on
# the API) as proof that the WSGI stack, the middleware chain and the auth layer all executed.
# A wedged or dead gunicorn fails those. That is why this catches the 2026-09-15 shape:
# connection exhaustion failed `db`, `http.web` AND `http.api` together. What it does NOT see
# is a fault that leaves all three answering correctly.
#
# WHERE ITS OUTPUT GOES. Docker records each run's stdout/stderr into the container's
# `State.Health.Log` (last few results, truncated), readable by `docker inspect`. The CLI is a
# TRUSTED surface and prints `report.full()` — per-probe `detail` and machine `code`, not the
# coarse scorecard — so this is a real sink, and named here rather than left to be discovered.
# It is NOT a new disclosure: reading `State.Health.Log` needs the Docker socket, which is
# root-equivalent on the host and already permits `docker exec` into this container. The
# projection boundary (req-tap-health-exposure-3) is unchanged — it governs the UNTRUSTED
# tier, and this check stands entirely inside the trusted one. What makes that reasoning
# load-bearing rather than obvious is what the probes PUT in `detail`: probe_db, probe_cache
# and probe_queue emit a raw `str(exc)`. Tracked as Issue# 546 - tap.
#
# WHAT THIS DOES NOT BUY. **Docker does not restart an unhealthy container.** The restart
# policy reacts to container EXIT, not to health status; `restart: unless-stopped` ignores
# health entirely. An unhealthy container reads `(unhealthy)` in `docker ps` and nothing else
# happens. What this buys is visibility and `depends_on: condition: service_healthy` at
# startup. Auto-recovery is a separate, unmade decision — and per the Swarm note above, the
# runtimes that WOULD act on this signal are the ones where a readiness-based check is the
# wrong thing to give them.
#
# THE NUMBERS, each with its reason (a number without a reason is the defect this epic exists
# to remove). Measured in-container, direct venv binary: the command takes 2-3s, of which
# `django.setup()` alone is 2.25s. The probes themselves are milliseconds, so a NARROWER
# selection set would save nothing — trimming probes trims the free part. The lever is
# frequency, not weight.
#
#   --interval=120s      The failure this epic opened on ran for NINETEEN HOURS. A 60s
#                        detection window buys nothing over a 120s one, and the cost is
#                        linear in frequency: ~2.5s of CPU per probe is ~2% of one core at
#                        120s and ~4% at 60s. 120s is the cheapest interval that still
#                        detects an outage far faster than a human does.
#   --timeout=30s        Two bounds meet here. (a) It must not outlive the worker watchdog it
#                        sits beside (gunicorn `timeout`, 60s — tap#504): a health check that
#                        can still be running after the arbiter has already SIGABRTed a worker
#                        is reporting on a process that no longer exists. (b) 30s is the
#                        statement bound (`TAP_SEARCH_STATEMENT_TIMEOUT`), the same ceiling
#                        every other database wait in this stack uses. Against a measured
#                        2-3s that is ~10x headroom for a loaded host. It also matters because
#                        `run_health()` has no runner-level time budget in v0 (the http.web /
#                        http.api probes carry their own 2s socket timeout; the `db` probe
#                        does not) — so this IS the bound on a hung probe, and Docker scoring
#                        a timed-out check as a failure is the correct reading.
#   --start-period=240s  Pre-boot, migrate and plugin seeding take roughly 180s. Failures
#                        inside the start period do not count toward `retries` and the
#                        container reads `starting`, so this is what keeps a NORMAL startup
#                        from ever flapping to `unhealthy`. 240s is 180s plus a 60s margin for
#                        a cold cache or a slow host. (No `--start-interval`: the first probe
#                        lands at t=120s, already inside a boot that cannot finish before
#                        ~180s, so probing more eagerly would only burn CPU during the most
#                        contended minutes of the container's life.)
#   --retries=3          Three consecutive failures before the flip. Be precise about what
#                        that costs in wall-clock: Docker waits `interval` AFTER a check
#                        finishes, not between starts, so the window is
#                        3 x (interval + check duration) plus the gap between the outage and
#                        the next scheduled check — about 6 minutes when checks fail fast, and
#                        up to ~7.5 minutes when every attempt burns the full 30s timeout. It
#                        is deliberately NOT "interval x retries". Three absorbs two transient
#                        blips (a restarting database, a momentary connection-pool exhaustion)
#                        while staying minutes, not hours, behind a real outage.
#
# TRAP — exit code 2 is RESERVED by Docker. Docker's health contract is 0 healthy, 1 unhealthy,
# 2 reserved and documented "do not use". `manage.py health` exits 2 on a USAGE error (no
# `--set`, or an unknown selection name; `EXIT_USAGE` in tap_health/management/commands/health.py),
# and argparse exits 2 on an unknown flag. A typo in the line below would therefore hand Docker
# a reserved code and present a CONFIGURATION error as a health failure. The remedy is a test,
# not a wrapper: tap/tests/test_container_healthcheck.py parses this instruction and feeds its
# argv to the health command's OWN parser, then checks the `--set` value against
# tap_health.selection.SELECTION_NAMES. That verifies the claim against its source (remedy 2)
# rather than detecting drift afterward; a 2->1 wrapper would only have MASKED the config error
# as an outage, which is the confusion the trap is about.
HEALTHCHECK --interval=120s --timeout=30s --start-period=240s --retries=3 \
  CMD ["/app/.venv/bin/python", "/app/manage.py", "health", "--set", "readiness"]

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

# Drop our pinned provider into the base's ossl-modules dir.
COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so

# fipsinstall runs the module self-tests and writes the integrity MAC (pinning fips.so's
# exact bytes). It MUST run in the final image (D5); it also proves binary-compat, since the
# base's modern `openssl` loads + self-tests our pinned module (D4).
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

# The serving stage runs unprivileged (tap#754). Declared HERE and not in `app`, because
# the fips-1 stage in between runs `openssl fipsinstall`, which writes /etc/ssl — a
# root-only step that must complete BEFORE the drop. Directory preparation is in `app`.
# 65532 is Wolfi's `nonroot`; development overrides the uid (never back to 0) via the
# compose `user:` key so the container can write the host-owned `.:/app` bind mount.
# This is NOT the build-stage `USER node` in js-vendor, which is a separate control on a
# separate image and stays exactly as it is.
USER nonroot
