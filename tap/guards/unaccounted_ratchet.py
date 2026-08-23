"""Unaccounted-requirements ratchet — `req-tap-traceability-accounting`.

TAP-IMPLEMENTS: req-tap-traceability-accounting@aa39264f56c6/3d1698b8fa4d (enforcement) —
    the ratchet that lets the Unaccounted set only shrink.

The Definition of Done made mechanical: every requirement in the corpus lands in exactly
one bucket — mapped, excluded, doctrine, disputed, or Unaccounted — and the Unaccounted
set may only shrink. Existing debt is grandfathered in the committed baseline (the
referenced-RID pattern); an entry that leaves cannot return; and a requirement ADDED
without any disposition fails immediately. The gap drains; it never grows.

The baseline is keyed by RID alone — location is navigation, never the key
(`spec-tap-callsite-identity.md`) — so moving a requirement between specs neither clears
nor manufactures debt.

A grandfathered entry is debt, not license: every baselined RID still needs a mapping or
a documented exclusion before the project's Definition of Done is met.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, CeilingRatchet


class UnaccountedRatchet(CeilingRatchet):
    slug = "unaccounted-requirements"
    map_row = "Requirement accounting (Unaccounted ratchet)"
    rid = "req-tap-traceability-accounting"
    baseline_path = REPO_ROOT / "tap" / "guards" / "baselines" / "unaccounted_rids.txt"
    description = (
        "A requirement landing with neither evidence nor a documented exclusion silently "
        "grows the very gap the traceability project exists to drain — unnoticed, because "
        "nothing counted it."
    )
    new_hint = (
        "Give the new requirement a disposition: map it (mint a claim with "
        "`scripts/implements-tag <rid>`, or cite an acceptance criterion from a test with "
        "`@pytest.mark.spec`), or document the exclusion with a `Trace:` line beside its "
        "`Status:` line (categories: process | narrative | non-python <path> | external <name> — "
        "see req-tap-traceability-disposition). Never add it to the baseline: the baseline is "
        "grandfathered debt, not a place for new entries."
    )

    def measure(self) -> set[str]:
        from tap.spec_trace import unaccounted_rids

        return unaccounted_rids(REPO_ROOT)
