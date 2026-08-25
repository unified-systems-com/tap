"""WOG citation-resolution guard — `specs/spec-wog.md` (`req-wog-resolution`).

Every `WOG-*` citation in tracked text resolves to an entry in one of the tier files.
The direct analogue of the RID-integrity guard: a cited name that does not exist points a
reader at canon that is not there.
"""

from __future__ import annotations

from tap.guards._wog_scan import citations, entries
from tap.guards.base import Guard


class WogCitationResolutionGuard(Guard):
    slug = "wog-citation-resolution"
    map_row = "WOG citations"
    rid = "req-wog-resolution"
    description = (
        "A dangling WOG citation sends a reader — human or agent — to canon that does not exist, and it "
        "is exactly what a renamed or deleted entry produces silently. Renaming is the common cause: the "
        "entry moves tiers safely, but changing its NAME breaks every citation, because the name is the "
        "identity."
    )

    def check(self) -> None:
        known = {entry.citation: entry for entry in entries()}
        assert known, "No WOG entries parsed — the corpus is missing or the tier files moved."

        dangling = {name: locs for name, locs in citations().items() if name not in known}
        if not dangling:
            return

        lines = []
        for name, locs in sorted(dangling.items()):
            near = sorted(k for k in known if k.lower().startswith(name.split("-")[1][:3].lower()) or name in k)
            hint = f"  did you mean: {', '.join(near[:3])}" if near else ""
            lines.append(f"{name} cited at {', '.join(locs[:4])}{hint}")

        raise AssertionError(
            "WOG citation does not resolve to any entry (req-wog-resolution-1). An entry's NAME is its "
            "identity — moving it between tiers is safe, renaming it is not:\n  " + "\n  ".join(lines)
        )
