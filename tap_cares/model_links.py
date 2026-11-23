"""The version links of ``tap_cares``'s types (``req-grid-entity-model-version`` rules 9 to 17).

Read by ``tap_grid.version_links``. A step takes what one record asserts at version N and returns it
at N+1, and never imports a model.
"""

from __future__ import annotations

from typing import Any

from tap_grid.version_links import Step, TypeLinks


def _unchanged(record: dict[str, Any]) -> dict[str, Any]:
    """A version whose change no record asserts: the record is the same at the next version."""
    return record


# 1 to 2 for each: an event-time declaration (none) where there was none, by the owner's ruling on
# Issue# 1284 - tap (2026-11-23): a run, a schedule and a fire are TAP's own doings, timed by grid and
# collection time. No field changes and nothing was derived before, so no record does.
LINKS: dict[str, TypeLinks] = {
    "collection_job": TypeLinks({2: Step(upgrade=_unchanged)}),
    "schedule": TypeLinks({2: Step(upgrade=_unchanged)}),
    "schedule_fire": TypeLinks({2: Step(upgrade=_unchanged)}),
}
