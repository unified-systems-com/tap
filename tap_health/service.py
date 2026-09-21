"""The health service entrypoint — `run_health()`.

req-tap-health-service (spec-tap-health-v0.md).

`run_health()` is a **pure producer**: it takes no caller and no actor, runs
every registered probe, and returns a `HealthReport`. The v0 probes resolve no
actor, so the liveness path stays runnable when auth/DB/grid is broken
(req-tap-health-probe-actor). Projection and any caller authorization are a
*surface* concern (the CLI / a future API), never parameters here.

Per-probe execution is isolated: a probe that raises is reported as an
`unhealthy` outcome with a generic code, never propagated — one probe can
neither crash the run nor stop the others (req-tap-health-probe-registry-6).
"""

from __future__ import annotations

import logging

from tap_health.registry import HealthProbe, health_probe_registry
from tap_health.results import HealthReport, ProbeOutcome, ProbeResult, exception_detail
from tap_health.selection import resolve_selection, selects

logger = logging.getLogger(__name__)

PROBE_RAISED_CODE = "probe.raised"


def _run_one(entry: HealthProbe) -> ProbeOutcome:
    try:
        result = entry.probe()
    except Exception as exc:  # noqa: BLE001 — the runner reports, never propagates.
        logger.warning("[6880] health: probe %s raised: %s", entry.name, exc)
        result = ProbeResult.unhealthy(PROBE_RAISED_CODE, detail=f"probe raised: {exception_detail(exc)}")
    return ProbeOutcome(name=entry.name, group=entry.group, critical=entry.critical, result=result)


def run_health(*, selection: str) -> HealthReport:
    """Run the probes in `selection` and return a `HealthReport`.

    A non-selected probe is **not executed** — that is what keeps a liveness run
    from querying the database (req-tap-health-selection). The verdict is
    therefore aggregated over the selected probes only: a critical probe outside
    the selection cannot sink the answer to a question it was not asked.

    Args:
        selection: The selection set to run — `liveness`, `readiness`, or `all`.
            Mandatory: the caller states which question it is asking rather than
            inheriting a default it cannot see.

    Returns:
        A `HealthReport`. Project it with `.full()` (trusted) or `.scorecard()`
        (coarse) at the consuming surface.

    Raises:
        ValueError: `selection` is not a known selection name; the message lists
            the valid names.
    """
    chosen = resolve_selection(selection)
    # Report in deterministic (group, name) order so a group's probes cluster
    # (req-tap-health-probe-registry-8). The registry keys() sorts by name only.
    probes = sorted(
        (health_probe_registry.get(name) for name in health_probe_registry.keys()),
        key=lambda p: (p.group, p.name),
    )
    selected = tuple(p for p in probes if selects(p.sets, chosen.name))
    outcomes = tuple(_run_one(p) for p in selected)
    report = HealthReport(outcomes=outcomes, selection=chosen.name)
    logger.info(
        "[af5e] health: ran %d probe(s) for selection %s; overall=%s",
        len(outcomes),
        chosen.name,
        report.status.value,
    )
    return report


__all__ = ["run_health", "PROBE_RAISED_CODE"]
