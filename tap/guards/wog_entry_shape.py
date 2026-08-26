"""WOG entry-shape guard — `specs/spec-wog.md` (`req-wog-entry-shape`).

Every entry is a title over an underline of matching length, with a non-empty body.
"""

from __future__ import annotations

from tap.guards._wog_scan import entries
from tap.guards.base import Guard


class WogEntryShapeGuard(Guard):
    slug = "wog-entry-shape"
    map_row = "WOG entry shape"
    rid = "req-wog-entry-shape"
    description = (
        "An entry whose underline does not match its title length is ambiguous to the parser — a body "
        "line followed by dashes can masquerade as a title, silently splitting one entry into two or "
        "hiding one entirely. An empty entry is a title citing nothing. Both make citations resolve to "
        "the wrong text rather than failing loudly."
    )

    def check(self) -> None:
        """TAP-IMPLEMENTS: req-wog-entry-shape@beb301406415/151afd84f1df (enforcement) — the build-time
        assertion that every entry parses as title + matching underline + body.
        """
        found = entries()
        if not found:
            raise AssertionError("No WOG entries parsed — the corpus is missing or the tier files moved.")

        mismatched = [
            f"{e.path.name}:{e.line} {e.name!r} title={len(e.name)} underline={len(e.underline)}"
            for e in found
            if len(e.underline) != len(e.name)
        ]
        if mismatched:
            raise AssertionError(
                "WOG entry underline must be exactly as long as its title (req-wog-entry-shape-1):\n  "
                + "\n  ".join(mismatched)
            )

        empty = [f"{e.path.name}:{e.line} {e.name!r}" for e in found if not e.body]
        if empty:
            raise AssertionError(
                "WOG entry has no body (req-wog-entry-shape-2) — write it or remove the title:\n  " + "\n  ".join(empty)
            )
