"""WOG name-uniqueness guard — `specs/spec-wog.md` (`req-wog-identity`).

One entry, one name, wherever it lives. `WOG-Oneness` applied to WOG itself.
"""

from __future__ import annotations

from collections import defaultdict

from tap.guards._wog_scan import entries
from tap.guards.base import Guard


class WogNameUniquenessGuard(Guard):
    slug = "wog-name-uniqueness"
    map_row = "WOG entry names"
    rid = "req-wog-identity"
    description = (
        "The entry name is the citation's identity, so a duplicate name makes a citation ambiguous — "
        "and across tiers it makes an entry's authority ambiguous too, since the same citation would "
        "both govern and merely argue. The usual cause is a promotion that copied instead of moved, "
        "which also leaves the stale copy to drift."
    )

    def check(self) -> None:
        """TAP-IMPLEMENTS: req-wog-identity@92026303e0c9/825afe656579 (enforcement) — the build-time
        assertion that a name identifies exactly one entry across every tier.
        """
        by_name: dict[str, list[str]] = defaultdict(list)
        for entry in entries():
            by_name[entry.name].append(f"{entry.path.name}:{entry.line} ({entry.tier})")

        dupes = {name: locs for name, locs in by_name.items() if len(locs) > 1}
        if dupes:
            raise AssertionError(
                "WOG entry name is not unique across tiers (req-wog-identity-1) — a promotion moves an "
                "entry, it never copies it:\n  "
                + "\n  ".join(f"{name!r}: {', '.join(locs)}" for name, locs in sorted(dupes.items()))
            )
