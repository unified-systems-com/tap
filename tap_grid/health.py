"""The `grid.tables` health probe (req-tap-health-probes-8).

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

from tap_health.results import ProbeResult

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
        return ProbeResult.unhealthy("grid.tables_check_failed", detail=str(exc))

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


__all__ = ["probe_grid_tables"]
