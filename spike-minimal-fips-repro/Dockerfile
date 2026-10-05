# Minimal, standalone reproduction (no application code, no Django, no compose):
# `cryptography`'s own EC keygen+sign+verify succeeds, and a PLAIN, separate `_hashlib`
# fetch for an algorithm the active FIPS provider genuinely implements fails immediately
# afterward, in the same process.
#
# Round 2: uses tap's REAL pyproject.toml + uv.lock (uv sync --all-packages, the full
# 71-package dependency closure) rather than installing cryptography alone -- every
# earlier "minimal" test in this investigation ran inside tap's actual entrypoint.sh,
# always AFTER the real uv sync had already populated the full venv. A truly standalone
# single-package install did not reproduce the failure (4 consecutive negative results);
# testing whether the full dependency closure, not just the 2-line script, is required.
#
# Build: docker build -t fips-repro .
# Run:   docker run --rm fips-repro

FROM cgr.dev/chainguard/wolfi-base:latest@sha256:08df5982c3d27e70a4ce1607e3bb9af09d746f8722cf135a7694afef879fc5a2 AS ossl-builder
RUN apk add --no-cache build-base perl linux-headers curl
WORKDIR /build
RUN curl -fsSL -o openssl.tar.gz \
      https://github.com/openssl/openssl/releases/download/openssl-3.0.22/openssl-3.0.22.tar.gz \
 && tar xzf openssl.tar.gz
WORKDIR /build/openssl-3.0.22
RUN ./Configure enable-fips \
 && make -j"$(nproc)" \
 && make install_fips

FROM cgr.dev/chainguard/wolfi-base:latest@sha256:08df5982c3d27e70a4ce1607e3bb9af09d746f8722cf135a7694afef879fc5a2
# Same apk set tap's own base stage installs, so the full `uv sync --all-packages`
# below (psycopg[c], etc.) builds exactly the way tap's own does.
RUN apk add --no-cache \
      python-3.14 python-3.14-dev build-base rust pkgconf git bash curl tzdata \
      postgresql-client postgresql-dev \
      openssl-4.0=4.0.3-r2 openssl-4.0-dev=4.0.3-r2

COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so
RUN openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so

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

COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --all-packages

COPY repro_mod.py /app/repro_mod.py
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:${PATH}"
CMD ["uv", "run", "--no-project", "python", "-m", "repro_mod"]
