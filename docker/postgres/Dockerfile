# TAP Postgres image — minimal Wolfi + PostgreSQL 16 + the self-built OpenSSL FIPS provider
# (version pinned, and its CMVP status derived, in docker/build-openssl-fips.sh — D17), replacing the outgoing public.ecr.aws/.../postgres:16-alpine.
# Per req-cicd-base-image-lifecycle-3/-5/-6: the DB base becomes a curated-minimal Wolfi base,
# and (like the web image) runs crypto through the pinned FIPS provider, selected by
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

# How FIPS is activated, independent of whether it is on at all (TAP_FIPS above). See the
# web Dockerfile's matching ARG and docker/activate-fips-system-wide.sh for the full
# rationale; both images share the same script and the same decision record (§5.4).
ARG TAP_FIPS_ACTIVATION=system

# ============================================================================
# ossl-builder — compile the pinned OpenSSL FIPS provider (fips.so)
# ============================================================================
# Pinned tag@digest (req-cicd-base-image-lifecycle-1) — bump together with the root
# Dockerfile's pins (procedure documented there).
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:08df5982c3d27e70a4ce1607e3bb9af09d746f8722cf135a7694afef879fc5a2 AS ossl-builder
# Wolfi's apk repo flakes under load (observed 2026-08-16: HTTP 403s mid-install;
# 2026-08-20: fetch error on one package) — bounded retry with backoff, failing
# closed after 3 attempts. apk add is idempotent across retries.
RUN for i in 1 2 3; do \
      if apk add --no-cache build-base perl linux-headers curl gpg gpg-agent; then break; fi; \
      echo "apk add failed (attempt $i/3)" >&2; \
      if [ "$i" -eq 3 ]; then exit 1; fi; \
      sleep $((i*10)); \
    done
# The SAME script, the SAME pins, the SAME two integrity gates as the web image (tap#221).
# Until 2026-08-29 this stage fetched the identical tarball over bare curl with NO digest and
# NO signature check, while carrying the identical validation claim — one image
# verified its provider's source and the other did not. Sharing the script is what makes that
# class of divergence impossible rather than merely fixed (tap#232). Build context for this image is the
# REPO ROOT (docker-compose.yml / publish-images.yml), so the docker/ paths resolve.
COPY docker/openssl-release-keys.asc docker/build-openssl-fips.sh /opt/ossl/
RUN /opt/ossl/build-openssl-fips.sh

# ============================================================================
# base — Postgres 16 runtime (identical for both FIPS modes)
# ============================================================================
FROM cgr.dev/chainguard/wolfi-base:latest@sha256:08df5982c3d27e70a4ce1607e3bb9af09d746f8722cf135a7694afef879fc5a2 AS base

# postgresql-16 + client (pg_isready/psql for the healthcheck + pg_dump), the oci-entrypoint
# (canonical docker-library entrypoint), gosu (privilege drop root→postgres, as the official
# image), openssl-3.6 (fipsinstall + debugging), bash (the entrypoint is bash), tzdata (zoneinfo,
# which Wolfi's minimal base omits).
#
# `openssl-3.6`, not `openssl-4.0` or the bare `openssl` alias — tap#932/#933, L18.
#
# `libpq-18` is EXPLICITLY PINNED here too, corrected from an earlier, wrong claim in this
# comment that it "had not cut over" — checked directly, right now, it has: `postgresql-16-client`
# pulls `libpq-18` transitively, unpinned, which currently resolves to `18.6-r5` and links
# `libcrypto.so.4`/`libssl.so.4` (confirmed via `strings` on the installed `libpq.so.5`). This
# image is runtime-only (no `-dev` packages, no `cryptography`/psycopg build here), so this
# wouldn't poison a Python process the way it did on the web image — but `psql`/`pg_isready`
# (used by the healthcheck) are real libpq consumers in this same image, so pinning for
# consistency and to not leave a second, unpinned copy of the same hazard sitting here.
# A real, non-simulated `apk add` with this exact package set, `libpq-18=18.6-r4` and
# `openssl-3.6` resolves clean, no conflicts. See Dockerfile (web image) for the full writeup,
# including the from-scratch bare-Ubuntu reproduction that ruled out the raw version-mismatch as
# the cause of the original FIPS self-check failure. The lingering `libssl3`/`libcrypto3` (.so.3)
# belong to `apk-tools` itself regardless of any of this, and never share a process with postgres.
#
# `krb5-libs` pinned for the same reason as the web image (see Dockerfile there for the full
# writeup): `libpq.so.5` links GSSAPI/Kerberos support unconditionally, and `krb5-libs`'s own
# crypto backend (`libk5crypto.so.3`) floats to `openssl-4.0` independently of `libpq-18`'s own
# pin. Pinning for the same consistency reason as `libpq-18` above, not a confirmed live hazard
# in this specific image (no Python process here to poison), one revision before its own cutover.
RUN for i in 1 2 3; do \
      if apk add --no-cache \
    postgresql-16 \
    postgresql-16-client \
    postgresql-16-oci-entrypoint \
    libpq-18=18.6-r4 \
    krb5-libs=1.22.2-r4 \
    gosu \
    openssl-3.6=3.6.5-r1 \
    bash \
    tzdata \
      ; then break; fi; \
      echo "apk add failed (attempt $i/3)" >&2; \
      if [ "$i" -eq 3 ]; then exit 1; fi; \
      sleep $((i*10)); \
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
# 0755, not 1777 (SonarCloud docker:S2612). Stated precisely, because the finding is real
# about the INSTRUCTION and not about the running container: the upstream
# docker-entrypoint.sh does `chmod 03775 /var/run/postgresql` on every start, so this line
# was overridden at boot and the directory has never actually been world-writable at
# runtime (verified: 3775 on a live container). The 1777 was therefore both
# over-permissive AND dead — the worst combination, because it reads as the deployed
# posture and is not.
#
# 0755 is what this line should have said. postgres owns the directory after the chown
# above and is the only process that writes here (the socket and its lock file); clients
# such as pg_isready and psql only traverse it and open the socket FILE, whose permissions
# postgres sets itself. Confirmed by rebuilding and booting: healthy, and a socket
# connection (`psql -U tap`, no -h) still succeeds.
RUN mkdir -p "$PGDATA" /var/run/postgresql \
 && chown -R postgres:postgres "$PGDATA" /var/run/postgresql \
 && chmod 0755 /var/run/postgresql
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

# TAP_FIPS_ACTIVATION is meaningless when FIPS is off; see the web Dockerfile's matching
# aliases for why these exist (keeps the final stage's selection a single-level ARG
# template, which is what test_container_healthcheck.py's ancestry walker resolves).
FROM fips-0 AS fips-0-legacy
FROM fips-0 AS fips-0-system

# ============================================================================
# fips-1-base — shared prerequisite for both activation mechanisms below
# ============================================================================
FROM base AS fips-1-base

# Drop our pinned provider into the base's ossl-modules dir, then fipsinstall it
# in-image (self-tests + integrity MAC). Postgres links the SYSTEM libcrypto for TLS +
# cryptohash, so it inherits the activated provider with no rebuild (§5.4).
COPY --from=ossl-builder /usr/local/lib/ossl-modules/fips.so /usr/lib/ossl-modules/fips.so
RUN openssl fipsinstall -out /etc/ssl/fipsmodule.cnf -module /usr/lib/ossl-modules/fips.so

# ============================================================================
# fips-1-legacy — the ORIGINAL activation mechanism (separate generated file +
# OPENSSL_CONF). Kept as TAP_FIPS_ACTIVATION=legacy; see the web Dockerfile's matching
# stage and docs/misc/doc-fips-assessment-record.md for why "system" is now the default.
# ============================================================================
FROM fips-1-base AS fips-1-legacy

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
# fips-1-system — the DEFAULT activation mechanism: edits Wolfi's own stock
# /etc/ssl/openssl.cnf in place. See docker/activate-fips-system-wide.sh.
# ============================================================================
FROM fips-1-base AS fips-1-system

COPY docker/activate-fips-system-wide.sh /opt/ossl/activate-fips-system-wide.sh
RUN sh /opt/ossl/activate-fips-system-wide.sh

ENV TAP_FIPS_MODE=1
LABEL org.tap.fips="true"

# ============================================================================
# final — select the variant by TAP_FIPS and (when FIPS is on) TAP_FIPS_ACTIVATION, in
# ONE templated FROM (see the fips-0-legacy/fips-0-system aliases above for why).
# ============================================================================
FROM fips-${TAP_FIPS}-${TAP_FIPS_ACTIVATION} AS final
