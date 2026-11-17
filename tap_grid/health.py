"""The `grid.tables` health probe (req-tap-health-probes-8), and `grid.history_agreement`
(req-grid-history-optout-9), which is described on its function.

Owned by `tap_grid` and registered from its own `ready()` (the dependency
inversion of req-tap-health-probe-registry-3).

**What it answers:** does every table the grid classifies as TAP-managed actually
exist in the database? That is the **fail-closed grid-integrity invariant** of
`tap_plugins/specs/spec-tap-plugin-lifecycle-v1.md`
(req-tap-plugin-lifecycle-v1-grid-invariant) evaluated *continuously* rather than
only at a plugin transition, and it is the exact fingerprint of the
plugin-loading race: a registered type whose migration never ran. Same assertion,
two consumers, one implementation (`grid_tables.classified_but_absent`) — the
search-role grant skips absent tables, this probe reports them. It is never
re-derived; that duplication is the class of bug it watches for.

**Two things this deliberately does NOT check**, because measurement showed the
assumptions behind them were false or undefined:

- *Registered-type vs catalog-row agreement.* The in-code model registry
  (`list_entity_types()`) and the `EntityType` DB catalog are **different
  populations, not a duplication**: on a healthy booted instance they measured 30
  and 87 with neither a subset of the other (the catalog carries plugin-declared
  types, including rows outliving an evicted plugin). Asserting a relationship
  between them would be a permanently-red critical probe. Their relationship is
  the open question behind duplicate-derivation audit item #7 and needs a design
  decision before anything can gate on it.
- *Boot's `population` phase completion.* Boot has a literal `population` phase
  (seeding steps from the profile); whether it ran to completion is a different
  claim, answered by the boot record, and is not covered here. Hence the name
  `grid.tables` rather than anything implying "populated".

The read runs below the service boundary under `unguarded_read()`: the probe
resolves no actor, so it must not depend on a CallerContext holding `grid.read`
(req-tap-health-probe-actor-2). It would pass today either way — the read guard
allows a context-free read — but would start failing the moment health is served
from inside a request, which is the trap the explicit escape hatch avoids.
"""

from __future__ import annotations

import logging

from django.db import connection

from tap_health.results import ProbeResult, exception_detail

logger = logging.getLogger(__name__)


def probe_grid_tables() -> ProbeResult:
    """Every classified grid table exists in the database."""
    from tap_grid.grid_tables import classified_but_absent, grid_tables
    from tap_grid.read_guard import unguarded_read

    try:
        with unguarded_read(), connection.cursor() as cursor:
            absent = classified_but_absent(cursor)
        classified_count = len(grid_tables())
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[9f31] health: grid tables probe failed: %s", exc)
        return ProbeResult.unhealthy("grid.tables_check_failed", detail=exception_detail(exc))

    if absent:
        return ProbeResult.unhealthy(
            "grid.tables_absent",
            detail=f"{len(absent)} classified table(s) absent: {', '.join(absent)}",
            reasoning=(
                "A model classified as TAP-managed whose table does not exist is "
                "schema/registry divergence — the plugin-loading race's fingerprint. Grid "
                "reads and writes for it fail at the database instead of at a legible "
                "boundary, and the search-role grant silently skips it."
            ),
            context={"absent_tables": absent, "classified_tables": classified_count},
        )
    return ProbeResult.healthy(context={"classified_tables": classified_count})


def probe_history_agreement() -> ProbeResult:
    """Every node type's history status agrees between class, catalog row and history model.

    Reported, not gating (``critical=False``, req-grid-history-optout-9). Every consumer that
    acts on history asks the class-built answer (``is_history_enabled``) and degrades
    explicitly with ``HistoryNotTracked``, so no disagreement this finds makes a consumer
    answer wrongly: a stale ``EntityType.track_history`` misdescribes the type in the
    catalog, and a class whose history model disagrees with its ``TRACK_HISTORY`` still
    behaves as its model says. ``grid.tables`` already fails readiness when a history table
    the model needs is absent. A mismatch makes the verdict ``degraded`` and names the
    types; it does not take the instance out of service.
    """
    from tap_grid.history import history_agreement_problems
    from tap_grid.read_guard import unguarded_read

    try:
        with unguarded_read():
            problems = history_agreement_problems()
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[c4e2] health: history agreement probe failed: %s", exc)
        return ProbeResult.unhealthy("grid.history_agreement_check_failed", detail=exception_detail(exc))

    if problems:
        return ProbeResult.unhealthy(
            "grid.history_disagreement",
            detail=f"{len(problems)} node type(s) disagree: " + "; ".join(str(p) for p in problems),
            reasoning=(
                "A node type's TRACK_HISTORY, its EntityType.track_history and the presence of its "
                "Historical model should say the same thing. The class is the authority; a row that "
                "disagrees was not re-stamped by registration, and a history model that disagrees "
                "with its class was attached outside TapHistoricalRecords."
            ),
            context={"disagreements": [p.entity_type for p in problems]},
        )
    return ProbeResult.healthy()


__all__ = ["probe_grid_tables", "probe_history_agreement"]
