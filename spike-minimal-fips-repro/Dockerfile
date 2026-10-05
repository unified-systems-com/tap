# Minimal, standalone reproduction (no application code, no Django, no compose):
# `cryptography`'s own EC keygen succeeds, and a PLAIN, separate `_hashlib` fetch for an
# algorithm the active FIPS provider genuinely implements fails immediately afterward, in
# the same process. Confirmed real-hardware-only: fails 100% of the time on GitHub Actions
# ubuntu-24.04 (x86_64, AMD EPYC) runners; does not reproduce locally on aarch64 or under
# QEMU emulation of amd64.
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
RUN apk add --no-cache \
      python-3.14 python-3.14-dev build-base rust pkgconf \
      openssl-4.0=4.0.3-r2 openssl-4.0-dev=4.0.3-r2

# The pinned, CMVP-tracked FIPS provider -- same version, same build process a real
# downstream (tap) uses. This is the only thing that needs to be "ours"; everything else
# here is stock Wolfi + stock OpenSSL + stock cryptography from PyPI.
COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so
RUN openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so

# Standard strict fips+base provider set, fips=yes globally -- the ordinary way anyone
# activates this provider, nothing downstream-specific.
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
RUN uv venv /venv --python python3.14 \
 && uv pip install --python /venv --no-binary cryptography "cryptography==50.0.0"

COPY repro.py /repro.py
CMD ["/venv/bin/python3", "/repro.py"]
