"""Testability-floor ratchet — `req-tap-traceability-acid-floor`.

A requirement declared built with zero acceptance criteria has no attachment point for a
test marker: `Verified` is structurally unreachable for it, and the tests that already
exercise its behavior are stranded with nothing to cite. Measured when this landed
(2026-08-22): 166 of 536 built requirements — 30% of the built corpus, including most of
`spec-fips` — sat below the floor, an authoring-style split between spec generations
rather than a decision anyone made.

The debt is grandfathered in the committed baseline and only shrinks (backfill a
requirement's ACID table and its line leaves forever); a requirement newly declared
built without at least one ACID fails immediately. Same discipline as the Unaccounted
ratchet: the gap drains, it never grows.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, CeilingRatchet


class AcidFloorRatchet(CeilingRatchet):
    slug = "acid-floor"
    map_row = "Requirement testability floor (zero-ACID ratchet)"
    rid = "req-tap-traceability-acid-floor"
    baseline_path = REPO_ROOT / "tap" / "guards" / "baselines" / "zero_acid_rids.txt"
    description = (
        "A requirement declared built with no acceptance criteria can never earn Verified "
        "and gives its existing tests nothing to cite — untestable-by-construction canon, "
        "growing silently unless counted."
    )
    new_hint = (
        "Author at least one acceptance criterion for the requirement (an ACID table row: "
        "a concrete, testable condition — the requirement's existing tests usually name it "
        "already). Never add the RID to the baseline: it is grandfathered debt, not a "
        "place for new entries. See req-tap-traceability-acid-floor."
    )

    def measure(self) -> set[str]:
        from tap.spec_trace import zero_acid_built

        return zero_acid_built(REPO_ROOT)
