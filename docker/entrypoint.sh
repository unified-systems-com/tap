#!/bin/bash
# TAP Development Entrypoint Script
#
# Runs on container startup before the Django server. Handles:
# 1. Python dependency sync (idempotent; first start downloads, later starts no-op)
# 2. Database migrations
# 3. Django development server
#
# The dependency sync lives here (rather than in the Dockerfile) because
# /app/.venv and /root/.cache/uv are named volumes mounted at runtime —
# anything we install at build time is hidden at runtime. Doing it in the
# entrypoint means the install lands in the per-project container venv and
# uv cache volumes, which is what we actually want to use. The image ships a
# pre-compiled wheel cache at /opt/uv-cache-seed (Dockerfile deps-warm stage)
# that this script copies into an empty uv-cache volume first, so the sync
# installs from built wheels in seconds rather than compiling from source.
#
# Exit immediately if any command failsals
set -e

# Emit the reserved ABORT signal (req-tap-logging-abort-signal / req-boot-abort-signal)
# for the bash-driven standup steps, mirroring tap.logging.abort() for the Python
# ones. A supervising watcher (scripts/spawn-session.sh Step 5, scripts/gate-lean)
# tails the container log for this exact `TAP-ABORT:` prefix and fast-fails the
# instant it appears, instead of waiting out its readiness timeout.
emit_abort() { echo "TAP-ABORT: $1: $2" >&2; }

# Seed an EMPTY uv-cache volume from the image's pre-compiled wheel cache
# (/opt/uv-cache-seed, Dockerfile deps-warm stage) before syncing. The sync
# below then CREATES the venv itself (the long-proven runtime path) but installs
# the expensive FIPS-mandated source builds (cryptography --no-binary,
# psycopg[c]) from cached wheels in seconds instead of compiling for ~5 minutes.
# Only fires on an empty cache volume. Semantics split by presence
# (req-cicd-supply-chain-provenance-2): an ABSENT seed degrades cleanly — uv
# downloads/compiles with uv.lock hash verification; a PRESENT seed is verified
# against its build-time manifest first (full bidirectional reconciliation:
# mismatch, missing, extra), and present-but-INVALID is a fail-closed abort —
# inside an immutable image that means corruption or tamper, never staleness.
if [[ -z "$(ls -A /root/.cache/uv 2>/dev/null)" ]]; then
  if [[ -d /opt/uv-cache-seed && -f /opt/uv-cache-seed.manifest.json ]]; then
    # Verifier is taken from the TREE when running under the dev bind mount is
    # impossible here: this script itself runs from /app (compose entrypoint), but
    # the verifier + manifest + seed are IMAGE artifacts — use the baked copy.
    echo "==> Verifying wheel-cache seed against its build-time manifest..."
    if python3 /usr/local/lib/tap/seed_manifest.py verify /opt/uv-cache-seed /opt/uv-cache-seed.manifest.json; then
      echo "==> Seeding uv cache from image (/opt/uv-cache-seed -> /root/.cache/uv)..."
      cp -a /opt/uv-cache-seed/. /root/.cache/uv/
    else
      emit_abort seed-verify "wheel-cache seed does not match its build-time manifest (see above) — image corruption or tamper; refusing to seed or serve"
      exit 1
    fi
  elif [[ -d /opt/uv-cache-seed ]]; then
    # Seed present but NO manifest: a LEGACY image (built before manifests) under a
    # newer tree — a designed, normal state (compose runs this script from the bind
    # mount; the image lags until the next publish/pull). NOT tamper: anyone able to
    # strip the manifest from an image could modify the seed too — image immutability
    # is that boundary. The invariant preserved is NEVER SEED UNVERIFIED BYTES: skip
    # the seed, warn loudly, and let uv take the slow path (every download re-verified
    # against uv.lock hashes). Converges back to the fast path once the image carries
    # a manifest. First proved the hard way: the original abort-on-absent semantics
    # bricked every lean-boot/dev boot of a legacy image (PR #86 gate red).
    echo "==> WARN: wheel-cache seed has NO manifest (legacy image predating seed verification)."
    echo "==>       Refusing to seed unverified bytes; uv will download/compile instead"
    echo "==>       (slow path, uv.lock hash-verified). Pull a newer image to restore the fast path."
  else
    echo "==> No wheel-cache seed in image — uv will download/compile (slow path, uv.lock hash-verified)."
  fi
fi

echo "==> Syncing Python dependencies (uv sync --all-packages)..."
# --all-packages installs every workspace member and its deps into the venv,
# so plugin-local third-party requirements (declared in
# plugins/<slug>/pyproject.toml under req-tap-plugin-arch-python-deps) land in
# the runtime env. Without this flag, members' deps stay in uv.lock but never
# get installed.
uv sync --all-packages

# ---------------------------------------------------------------------------
# FIPS boot self-check (req-cicd-base-image-lifecycle-6, decision D15) — fail closed.
# ---------------------------------------------------------------------------
# The image DECLARES its FIPS posture (org.tap.fips label + TAP_FIPS_MODE env); this PROVES
# the declared mode is the mode actually enforced by executing crypto and observing a refusal
# — never by inspecting files, because the FIPS boundary is the OpenSSL config, not the
# modules directory (doc-fips-assessment-record.md L13). Runs AFTER uv sync so `cryptography`
# (the webauthn/passkey integration point, built --no-binary against the system OpenSSL) is
# present. `tap.fips` prints its own `TAP-ABORT: fips: …` on a mismatch; this covers a hard
# process death. A FIPS-declared image that fails to refuse MD5 is the L1 fail-open trap, and
# a new bare hashlib.md5()/SELECT md5() in a dependency is a boot-breaking regression under
# FIPS — both are caught here before any schema mutation.
echo "==> FIPS self-check (assert declared mode is actually enforced)..."
if ! uv run python -m tap.fips; then
    emit_abort fips "FIPS self-check failed: declared mode not enforced (see above); refusing to serve"
    exit 1
fi

# ---------------------------------------------------------------------------
# Bootstrap-tier secret-source providers (req-tap-plugin-depres-bootstrap, Decision B).
# ---------------------------------------------------------------------------
# A plugin's git-install credential can be routed to an external store (e.g. AWS Secrets
# Manager) whose provider distribution must be importable BEFORE pre-boot resolves that
# credential. TAP_SECRET_SOURCE_DISTS is a space-separated list of `uv pip install` targets
# (local paths or requirements) installed into the venv here, ahead of pre-boot. It is
# UNSET in normal/dev boots, so no cloud SDK enters the default venv — this is the CI
# preinstall hook, not the general two-phase install engine (that stays deferred). Like
# pre-boot's own plugin installs, these persist across the subsequent `uv run` (its implicit
# sync is additive, not exact).
if [ -n "${TAP_SECRET_SOURCE_DISTS:-}" ]; then
    echo "==> Installing secret-source provider(s): ${TAP_SECRET_SOURCE_DISTS}"
    # shellcheck disable=SC2086  # intentional word-splitting on the space-separated list
    # --python names the venv DIRECTORY outright — both uv-pip env discovery and
    # the interpreter-path form mistarget the seeded venv's symlinked python on
    # the CI runner (see tap/preboot.py _VENV_DIR).
    uv pip install --python /app/.venv ${TAP_SECRET_SOURCE_DISTS} || { emit_abort preboot "secret-source provider install failed"; exit 1; }
fi

# ---------------------------------------------------------------------------
# Pre-boot stage (settings-free; runs BEFORE Django reads settings).
# ---------------------------------------------------------------------------
# tap/preboot.py reads the boot profile as plain JSON, uv-installs the profile's
# `install` plugins (idempotent — a reboot is a fast no-op, no re-pull), verifies
# each plugin's entry-point key == slug, runs the static coherence guard, and takes
# a verified pre-migrate DB snapshot (switch defaults true; dev disables it via
# TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE=false in .env.local). It prints the
# resolved package-mode AppConfig paths on stdout as TAP_PLUGINS, which settings.py
# consumes (splicing them into INSTALLED_APPS before tap_api). This runs before
# createcachetable/migrate so the snapshot precedes ALL schema changes and so
# TAP_PLUGINS is set for migrate + the server. A pre-boot failure is fatal and
# aborts here, before any schema mutation, leaving the DB untouched (req-boot-preboot).
# It is the Kubernetes initContainers shape: a run-to-completion stage before the
# main process. `manage.py boot` (population) still runs at spawn time.
# Resolve the boot profile ONCE. Pre-boot (which installs the plugins) and the FIPS
# gate (which reads that profile's fips_waivers) MUST agree on which profile booted;
# resolving `unset -> core_dev` separately at each site is one edit away from gating
# a different profile than the one installed. Empty means the lean core_dev baseline —
# spawn's documented contract (scripts/spawn-session.sh, req-boot-minimal-baseline),
# whose peer default writes the resolved id into .env.local — edit one, check the other.
BOOT_PROFILE_ID="${TAP_BOOT_PROFILE:-core_dev}"

echo "==> Pre-boot: installing declared plugins + pre-migrate snapshot (profile: ${BOOT_PROFILE_ID})..."
if ! TAP_PLUGINS="$(uv run python -m tap.preboot --profile "$BOOT_PROFILE_ID")"; then
    # tap.preboot already emits its own `TAP-ABORT: preboot: …` on a PrebootError;
    # this covers the case where the process died without one (e.g. uv itself failed).
    emit_abort preboot "pre-boot stage failed; aborting standup before migrate (DB untouched)"
    exit 1
fi
export TAP_PLUGINS
# Persist the resolved set so sibling execs (manage.py boot, import_plugin_grift, pytest)
# that do NOT inherit this shell's env read the SAME authoritative plugin set, instead of
# racing live entry-point discovery (importlib.metadata's mtime cache can disagree across
# processes → a registered type with no migrated table, the plugin-loading race 2026-08-11).
# /run is tmpfs; rewritten every boot, so never stale. Best-effort: the export above covers
# the server; a persist failure only degrades sibling execs back to the warned fallback.
printf '%s' "${TAP_PLUGINS}" > /run/tap-plugins \
    || echo "==> WARN: could not persist TAP_PLUGINS to /run/tap-plugins (sibling execs fall back to discovery)" >&2
echo "==> Pre-boot complete. TAP_PLUGINS=[${TAP_PLUGINS:-<none>}]"

# ---------------------------------------------------------------------------
# System FIPS-provider gate (req-fips-crypto-bom-system-gate) — global validation, fail-closed.
# ---------------------------------------------------------------------------
# tap.fips proves the OpenSSL-backed Python layer is enforced, but it is blind to a plugin (or dep)
# that carries its OWN crypto — a Go binary, a Rust crate on ring/aws-lc-rs, a libsodium/pynacl wheel,
# a JVM — which ignores OPENSSL_CONF and would silently run non-FIPS crypto. When TAP_FIPS_MODE=1 this
# scans the WHOLE assembled environment (core + every installed plugin) and refuses to serve if any
# crypto provider is non-validated, UNLESS the operator has excused it with a justified `fips_waivers`
# entry in the boot profile (a plugin cannot excuse itself — only the deployer, with a reason). No-op
# when FIPS is off. MUST run AFTER pre-boot: plugins are git/editable-installed by pre-boot, not by
# `uv sync`, so scanning before pre-boot would miss every plugin — the exact thing this gate exists to
# catch (a plugin leaking non-FIPS crypto). Still before migrate/serve, so a leak refuses to serve.
echo "==> System FIPS-provider gate (crypto-BOM: core + all plugins)..."
if ! uv run python -m tap.crypto_bom --gate --profile "$BOOT_PROFILE_ID"; then
    emit_abort crypto-bom "system FIPS-provider gate failed: a non-validated, un-waived crypto provider is present (see above); refusing to serve"
    exit 1
fi

# Provision the DatabaseCache table (settings.CACHES LOCATION="tap_cache").
# This is DB-schema provisioning, the same category as migrate — "fresh DB →
# schema current" — not instance state, so it lives here next to migrate rather
# than in `manage.py boot` (which converges instance state above the schema) or
# in spawn-session.sh (dev-env orchestration only). createcachetable is
# idempotent: it no-ops when the table already exists, so it is safe on every
# container start. Without it the first cache read (e.g. allauth login
# rate-limiting) fails with relation "tap_cache" does not exist.
#
# This MUST run BEFORE migrate: the `tap_health.E001` Tags.database system check
# (tap_health/checks.py) fires during migrate's check phase and hard-fails when
# the cache table is missing, so on a fresh DB `migrate` would abort before this
# step ever ran (chicken-and-egg → container restart loop). createcachetable
# itself has `requires_system_checks = []`, so it runs no checks and is safe
# against an as-yet-unmigrated DB; it creates the table via the schema editor
# independently of migration state.
echo "==> Provisioning the DatabaseCache table (createcachetable)..."
uv run python manage.py createcachetable || { emit_abort migrate "createcachetable failed"; exit 1; }

echo "==> Running database migrations..."
# The canonical fatal spot for a core->plugin-dep import leak (req-dev-validation-lean-boot):
# migrate runs django.setup(), which imports every INSTALLED_APPS module; a core module
# reaching a plugin-only dependency raises ModuleNotFoundError here. The sentinel turns that
# from a 300s readiness-timeout into a seconds-long fast-fail with the reason.
uv run python manage.py migrate --noinput || { emit_abort migrate "database migration failed (see traceback above)"; exit 1; }

# Note: tailwindcss is NOT rebuilt at container start. The committed
# tap_web/static/tap_web/css/tailwind.css is served as-is. Dev work that
# touches Tailwind utility classes is expected to invoke the
# /tailwind-rebuild skill (tap_web/skills/tailwind-rebuild/SKILL.md), which
# orchestrates an on-demand install + build inside this container and
# commits the regenerated file alongside the template change. See
# tap_web/specs/spec-web-tailwind-pipeline.md.

# Start the Steady Queue supervisor as a background process. It runs both
# the once-per-minute scheduler tick (declared as a @recurring task in
# tap_cares/task_backend.py) and the collector execution tasks. The
# supervisor forks one worker process per Configuration.Worker in
# settings.STEADY_QUEUE — one for the scheduler queue, one for the default
# queue — giving OS-level isolation between the clock and collector
# execution (req-tap-cares-task-backend-queue-isolation). Trap kills it on
# exit. Steady Queue does NOT auto-reload; restart the container if you
# edit task or scheduler code (req-tap-cares-task-backend-deployment-3).
echo "==> Starting Steady Queue supervisor..."
uv run python manage.py steady_queue &
STEADY_QUEUE_PID=$!

trap "kill ${STEADY_QUEUE_PID} 2>/dev/null || true" EXIT

echo "==> Starting Django development server (no-store on static for live JS/CSS)..."
exec uv run python manage.py runserver_nocache 0.0.0.0:8000
