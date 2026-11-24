"""The version links of core's own types and of the spine (``req-grid-entity-model-version`` rules 9 to
17, ``req-grid-entity-spine-version`` rule 5). Read by ``tap_grid.version_links``.

A step takes what one record asserts at version N and returns it at N+1. It never imports a model.
"""

from __future__ import annotations

from typing import Any

from tap_grid.version_links import SPINE, Step, TypeLinks


def _unchanged(record: dict[str, Any]) -> dict[str, Any]:
    """A version whose change no record asserts: the record is the same at the next version."""
    return record


LINKS: dict[str, TypeLinks] = {
    # Spine 1 to 2 (Issue# 1288 - tap): the typed row's ``batch_id`` was removed and the two spine copies
    # added (req-grid-entity-spine-copies). Neither is in a GRIFT envelope: the copies are never
    # exported (rule 15) and ``batch_id`` was never an envelope field, so an envelope is the same at
    # both versions.
    SPINE: TypeLinks({2: Step(upgrade=_unchanged)}),
    # batch 1 to 2: an event-time declaration (none) where there was none, by the owner's ruling on
    # Issue# 1284 - tap (2026-11-23). No field changes and nothing was derived before, so no record does.
    "batch": TypeLinks({2: Step(upgrade=_unchanged)}),
}
