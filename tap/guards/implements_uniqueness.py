"""Implementation-claim uniqueness guard — `req-tap-traceability-uniqueness`.

TAP-IMPLEMENTS: req-tap-traceability-uniqueness@d2f65eaa2072/39193e03c3fc (enforcement) —
    the guard that fails duplicate claims lacking a shared known-dupe group.

**Two modules claiming the same `(requirement, role)` is the anti-pattern this whole
convention exists to make structural.** One fact, one authoritative derivation.

The escape hatch is composition, not new vocabulary: the duplicate is permitted exactly
when both sites name the *same* `TAP-KNOWN-DUPE(<group>)` group — and that convention's own
guard independently requires every group to have at least two code sites and at least one
spec mention. So a permitted duplicate derivation is, by construction, one that is
documented in a spec. "Duplicate with an explanation" falls out of machinery that already
exists, and neither guard grows an escape vocabulary of its own.

Why this guard is worth more than referential integrity: a tag travels with the code it is
attached to, so copy-pasting a tagged function copies its claim. Clippy's original
safety-comment request anticipated exactly this hazard and never implemented a check for
it; OpenFastTrace names it twice in its status vocabulary ("copy-paste error", "copy-paste
error likely"). Uniqueness is the countermeasure.
"""

from __future__ import annotations

from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.spec_trace import Claim


def undeclared_duplicates(
    duplicates: dict[tuple[str, str], list[Claim]],
    tagged: dict[str, set[str]],
    repo_root: Path,
) -> list[str]:
    """Duplicate claim groups that are NOT covered by a shared known-dupe group.

    Pure, so the composition rule is testable without a live tree: a duplicate is permitted
    exactly when every module in the group names the *same* `TAP-KNOWN-DUPE` group id.
    Requiring the same id (not merely "each site has some tag") is what makes the escape a
    declaration about *this* pair rather than two unrelated exemptions that happen to
    coincide.
    """
    offenders: list[str] = []
    for (rid, role), claims in sorted(duplicates.items()):
        modules = [c.path.relative_to(repo_root).as_posix() for c in claims]
        shared = set.intersection(*(tagged.get(module, set()) for module in modules))
        if shared:
            continue
        offenders.append(
            f"{rid} ({role}) claimed by {len(modules)} modules:\n      "
            + "\n      ".join(c.where(repo_root) for c in claims)
        )
    return offenders


class ImplementsUniquenessGuard(Guard):
    slug = "implements-claim-uniqueness"
    map_row = "Implementation claim uniqueness"
    rid = "req-tap-traceability-uniqueness"
    description = (
        "Two modules claiming one requirement-and-role is the derive-the-same-fact-twice "
        "anti-pattern; it is also how a copy-pasted function silently duplicates its claim."
    )

    def check(self) -> None:
        from tap.guards.known_dupes import groups_by_file
        from tap.spec_trace import duplicate_claim_groups

        duplicates = duplicate_claim_groups(REPO_ROOT)
        if not duplicates:
            return

        offenders = undeclared_duplicates(duplicates, groups_by_file(), REPO_ROOT)
        assert not offenders, (
            "One requirement-and-role, more than one authoritative implementation. Collapse "
            "them to a single derivation every consumer reads — or, if both must exist, tag "
            "every site with the same `TAP-KNOWN" + "-DUPE(<group>)` and document that group "
            "in a spec:\n    " + "\n    ".join(offenders)
        )
