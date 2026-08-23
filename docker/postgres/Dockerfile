# TAP Postgres image — minimal Wolfi + PostgreSQL 16 + the self-built OpenSSL 3.0.9 FIPS
# provider (CMVP #4282), replacing the outgoing public.ecr.aws/.../postgres:16-alpine.
# Per req-cicd-base-image-lifecycle-3/-5/-6: the DB base becomes a curated-minimal Wolfi base,
# and (like the web image) runs crypto through the validated FIPS provider, selected by
# ARG TAP_FIPS (default 1). Full decision record: docs/misc/doc-fips-assessment-record.md §5.4.
#
# Two things make this a DROP-IN for the official image rather than a reimplementation:
#   * postgresql-16-oci-entrypoint ships the canonical docker-library/postgres
#     `docker-entrypoint.sh` (same POSTGRES_DB/USER/PASSWORD/HOST_AUTH_METHOD/INITDB_ARGS
#     contract + /docker-entrypoint-initdb.d), so we set up the postgres user + PGDATA + gosu
#     exactly as that image does and the entrypoint behaves identically.
#   * postgresql-16 is 16.14 — the exact version the outgoing alpine image ran.
#
# ⚠️ COLLATION, not crypto, is the load-bearing hazard (§5.4). The outgoing alpine image is
# musl, which implements NO locale collation: it is *labelled* en_US.utf8 but *sorts like C*.
# Wolfi is glibc, where en_US.utf8 is a REAL, different collation — so carrying the label
# across would silently change text sort order and every text index's ordering. We initdb with
# `--locale=C` (POSTGRES_INITDB_ARGS below), which reproduces the outgoing cluster's ACTUAL
# ordering AND is immune to the classic "a glibc upgrade invalidates your text indexes" hazard.
# The collation is baked into the cluster at initdb, so the data volume MUST be recreated on
# cutover (dev: `scripts/dc down -v`; a real deploy: dump/restore, never an in-place swap).

ARG TAP_FIPS=1

# ============================================================================
# ossl-builder — compile the validated OpenSSL 3.0.9 FIPS provider (fips.so)
# ============================================================================
# Pinned tag@digest (req-cicd-base-image-lifecycle-1) — bump together with the root
# Dockerfile's pins (procedure documented there).
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:a31344ab2cb8618db84f535eec56f76f6178b142cb92cb2e48676cc2dcebea72 AS ossl-builder
# Wolfi's apk repo flakes under load (observed 2026-08-16: HTTP 403s mid-install;
# 2026-08-20: fetch error on one package) — bounded retry with backoff, failing
# closed after 3 attempts. apk add is idempotent across retries.
RUN for i in 1 2 3; do apk add --no-cache build-base perl linux-headers curl && break || { echo "apk add failed (attempt $i/3)" >&2; [ "$i" -eq 3 ] && exit 1; sleep $((i*10)); }; done
WORKDIR /build
RUN curl -fsSL https://github.com/openssl/openssl/releases/download/openssl-3.0.9/openssl-3.0.9.tar.gz -o o.tgz \
 && tar xf o.tgz
WORKDIR /build/openssl-3.0.9
RUN ./Configure enable-fips && make -j"$(nproc)" && make install_fips

# ============================================================================
# base — Postgres 16 runtime (identical for both FIPS modes)
# ============================================================================
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:a31344ab2cb8618db84f535eec56f76f6178b142cb92cb2e48676cc2dcebea72 AS base

# postgresql-16 + client (pg_isready/psql for the healthcheck + pg_dump), the oci-entrypoint
# (canonical docker-library entrypoint), gosu (privilege drop root→postgres, as the official
# image), openssl (fipsinstall + debugging), bash (the entrypoint is bash), tzdata (zoneinfo,
# which Wolfi's minimal base omits).
RUN for i in 1 2 3; do \
      apk add --no-cache \
    postgresql-16 \
    postgresql-16-client \
    postgresql-16-oci-entrypoint \
    gosu \
    openssl \
    bash \
    tzdata \
      && break || { echo "apk add failed (attempt $i/3)" >&2; [ "$i" -eq 3 ] && exit 1; sleep $((i*10)); }; \
    done

# Recreate the docker-library/postgres runtime contract the oci-entrypoint expects.
RUN addgroup -S postgres && adduser -S -G postgres -H -h /var/lib/postgresql postgres
ENV PGDATA=/var/lib/postgresql/data
# --locale=C reproduces the outgoing musl cluster's actual (C) sort order on glibc Wolfi and
# stays immune to glibc-upgrade text-index invalidation (§5.4). --encoding=UTF8 is REQUIRED and
# NOT optional: `initdb --locale=C` with no explicit encoding silently defaults to SQL_ASCII
# (the C locale implies no codeset), under which varchar(n) counts BYTES not characters and any
# multibyte UTF-8 value overflows — the outgoing alpine cluster was UTF8. So we pin UTF8 storage
# (matches the outgoing cluster) WITH C collation (matches musl's actual sort). Overridable at
# deploy time. (The spike proved the C sort but never stored UTF-8 into a varchar, so it missed
# the encoding default — see §5.4.)
ENV POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C"
RUN mkdir -p "$PGDATA" /var/run/postgresql \
 && chown -R postgres:postgres "$PGDATA" /var/run/postgresql \
 && chmod 1777 /var/run/postgresql
VOLUME /var/lib/postgresql/data
EXPOSE 5432
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]

# ============================================================================
# fips-0 — non-FIPS variant (explicit escape hatch, TAP_FIPS=0)
# ============================================================================
FROM base AS fips-0
ENV TAP_FIPS_MODE=0
LABEL org.tap.fips="false"

# ============================================================================
# fips-1 — FIPS variant (default, TAP_FIPS=1)
# ============================================================================
FROM base AS fips-1

# Drop our validated 3.0.9 provider into the base's ossl-modules dir, then fipsinstall it
# in-image (self-tests + integrity MAC). Postgres links the SYSTEM libcrypto for TLS +
# cryptohash, so it inherits the activated provider with no rebuild (§5.4).
COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so
RUN openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so

# Strict fips + base provider set, fips=yes globally. Order is load-bearing (openssl_conf
# before the .include, else it is swallowed into [fips_sect] and nothing activates — L1);
# re-.include ca.cnf which OPENSSL_CONF otherwise displaces (L14).
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
ENV TAP_FIPS_MODE=1
LABEL org.tap.fips="true"

# ============================================================================
# final — select the variant by the build flag (default fips-1)
# ============================================================================
FROM fips-${TAP_FIPS} AS final
