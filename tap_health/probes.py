"""Core (platform) health probes: db, cache, migrations, queue, http serving.

req-tap-health-probes (spec-tap-health-v0.md). Registered from
`TapHealthConfig.ready()`. Each probe exercises a real backend and returns a
`ProbeResult`; it never raises (the service isolates exceptions anyway, but
probes report cleanly with a stable `code`).

These are below the service boundary — a `SELECT 1`, a cache round-trip, a
table-name introspection — so they resolve no actor and stay runnable when
auth/DB is broken (req-tap-health-probe-actor).
"""

from __future__ import annotations

import logging
import uuid

from django.core.cache import cache
from django.db import DEFAULT_DB_ALIAS, connection, connections

from tap_health.results import ProbeResult, exception_detail

logger = logging.getLogger(__name__)


def probe_db() -> ProbeResult:
    """Trivial `SELECT 1` over the default connection."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[8c9e] health: db probe failed: %s", exc)
        return ProbeResult.unhealthy("db.query_failed", detail=exception_detail(exc))
    return ProbeResult.healthy()


def probe_cache() -> ProbeResult:
    """Real `cache.set` → `cache.get` round-trip; the value must match.

    A missing DatabaseCache table surfaces here as `unhealthy` with the
    `cache.unavailable` code instead of a 500 on first cache use. The detail is
    the exception TYPE, not its message (`exception_detail`) — the message is an
    unbounded string that would ride every projection, including the 120s
    HEALTHCHECK's `State.Health.Log` entry (tap#546).
    """
    probe_key = f"healthz-probe-{uuid.uuid4()}"
    token = uuid.uuid4().hex
    try:
        cache.set(probe_key, token, timeout=30)
        observed = cache.get(probe_key)
        cache.delete(probe_key)
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[f3b4] health: cache probe failed: %s", exc)
        return ProbeResult.unhealthy("cache.unavailable", detail=exception_detail(exc))
    if observed != token:
        logger.warning("[bd40] health: cache round-trip mismatch (set != get)")
        return ProbeResult.unhealthy("cache.roundtrip_mismatch", detail="cache set/get round-trip mismatch")
    return ProbeResult.healthy()


def probe_migrations() -> ProbeResult:
    """No unapplied migrations — the schema is fully current.

    Distinct from ``probe_db`` (reachability): the DB can be UP and the cache table
    present while ``migrate`` is still applying migrations, because the entrypoint runs
    ``createcachetable`` BEFORE ``migrate`` — so a reachability/cache probe goes green
    mid-migrate. A readiness consumer that then touches TAP-managed tables races the
    half-applied schema. That was the plugin-loading flake: boot's ``grid_infra`` granted
    ``SELECT`` on a registered entity type whose migration had not run yet (a different
    table each run). Critical: a stack with pending migrations is not ready to ACT on the
    grid, even though it is alive.
    """
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[648b] health: migrations probe failed: %s", exc)
        return ProbeResult.unhealthy("migrations.check_failed", detail=exception_detail(exc))
    if plan:
        return ProbeResult.unhealthy("migrations.pending", detail=f"{len(plan)} migration(s) not yet applied")
    return ProbeResult.healthy()


def probe_queue() -> ProbeResult:
    """Best-effort reachability of the DB-backed Steady Queue backend.

    Non-critical: an indeterminate result is `unknown`, never `unhealthy`. It
    does not probe worker liveness.
    """
    try:
        table_names = set(connections[DEFAULT_DB_ALIAS].introspection.table_names())
    except Exception as exc:  # noqa: BLE001 — non-critical; report unknown.
        logger.info("[bb90] health: queue probe indeterminate: %s", exc)
        return ProbeResult.unknown("queue.indeterminate", detail=exception_detail(exc))
    if "steady_queue_job" in table_names:
        return ProbeResult.healthy()
    return ProbeResult.unknown("queue.tables_missing", detail="steady_queue tables not found")


# --- HTTP serving probes (req-tap-health-probes-7) ------------------------------
#
# These answer the question a boot gate actually cares about and that no in-process
# probe can: "is the SERVER answering?" Every other probe runs in the calling
# process and stays green while the web worker is dead.
#
# No new unauthenticated surface is introduced to make this work — that would undo
# req-tap-health-exposure-4. Instead the probe reads the *authentication* responses
# as proof of life: an anonymous GET of a walled page returns 302 to the login flow,
# and an anonymous API GET returns 401. A redirect or a 401 is stronger evidence
# than a 200 from a bypass route: it proves the WSGI stack, the middleware chain,
# and the login wall are all executing.
#
# Timeouts are the probe's own responsibility. These are the first probes that can
# HANG (a wedged worker accepts the connection and never replies), and v0
# deliberately has no runner-level time budget (req-tap-health-probe-registry
# security considerations) — so the socket timeout below is what bounds a health
# run, and it is deliberately short.
_HTTP_TIMEOUT_SECONDS = 2.0

# Anonymous-expected statuses. A 5xx or a connection failure is the real signal.
_WEB_SERVING_STATUSES = frozenset({200, 302, 303})
_API_SERVING_STATUSES = frozenset({200, 401, 403})


def _probe_serving(path: str, expected: frozenset[int], code_prefix: str) -> ProbeResult:
    """GET `path` on this instance's own base URL and judge the response.

    Args:
        path: Absolute path to request (e.g. `/`).
        expected: Statuses that prove the stack is serving.
        code_prefix: Probe namespace for the machine `code`.

    Returns:
        A `ProbeResult`. `unknown` (never `unhealthy`) when no base URL is
        configured: a process that is not supposed to be serving must not be
        reported as broken.
    """
    from django.conf import settings

    base = (getattr(settings, "TAP_HEALTH_SELF_URL", "") or "").rstrip("/")
    if not base:
        return ProbeResult.unknown(
            f"{code_prefix}.not_configured",
            detail="TAP_HEALTH_SELF_URL is unset; serving is not probed",
        )

    url = f"{base}{path}"
    try:
        import requests

        response = requests.get(url, timeout=_HTTP_TIMEOUT_SECONDS, allow_redirects=False)
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[c14a] health: %s probe could not reach %s: %s", code_prefix, url, exc)
        return ProbeResult.unhealthy(
            f"{code_prefix}.unreachable",
            detail=f"{exception_detail(exc)} requesting {path}",
            context={"path": path, "timeout_seconds": _HTTP_TIMEOUT_SECONDS},
        )

    if response.status_code in expected:
        return ProbeResult.healthy(context={"path": path, "status": response.status_code})
    logger.warning(
        "[4d7f] health: %s probe got unexpected status %s from %s",
        code_prefix,
        response.status_code,
        url,
    )
    return ProbeResult.unhealthy(
        f"{code_prefix}.unexpected_status",
        detail=f"HTTP {response.status_code} from {path}",
        context={"path": path, "status": response.status_code},
    )


def probe_http_web() -> ProbeResult:
    """The web stack answers on `/` (200, or 302 into the login wall)."""
    return _probe_serving("/", _WEB_SERVING_STATUSES, "http.web")


def probe_http_api() -> ProbeResult:
    """The API stack answers on a real router path (401 when anonymous).

    Deliberately an authenticated route rather than the unauthenticated
    `openapi.json`: a 401 proves routing *and* the auth layer, and costs no
    schema generation on every poll.
    """
    return _probe_serving("/api/v1/entity-types/", _API_SERVING_STATUSES, "http.api")


__all__ = [
    "probe_cache",
    "probe_db",
    "probe_http_api",
    "probe_http_web",
    "probe_migrations",
    "probe_queue",
]
