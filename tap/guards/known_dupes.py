"""Known-dupe group integrity guard — `req-tap-known-dupes`.

TAP-IMPLEMENTS: req-tap-known-dupes@fb68deb20642/00562c03b3cb (enforcement) — the guard
    that fails an undeclared duplicate-derivation group.

Intentional duplicate derivations (an import boundary forbids one shared
function) are tagged ``TAP-KNOWN-DUPE(<group-id>)`` at every site. This guard
keeps the tags honest: every group id found in code must have at least two code
sites (a singleton means the partner was deleted or never tagged — the tag is
lying either way) and at least one spec mention (an undocumented group is
untracked). Collapsing a group to one true source therefore requires deleting
every tag and its spec mention in the same change — loudly, not silently.

The tag needle is assembled by concatenation so this module and its tests never
match their own scan.
"""

from __future__ import annotations

import re
from collections import defaultdict

from tap.guards.base import REPO_ROOT, Guard

_EXCLUDE_DIRS = frozenset(
    {".venv", "node_modules", "__pycache__", ".git", ".claude", ".mypy_cache", ".pytest_cache", "vendor", "tap_secrets"}
)

_TAG_RE = re.compile("TAP-KNOWN" + r"-DUPE\(([a-z0-9][a-z0-9-]*)\)")


def _walk(pattern: str) -> list[str]:
    rels: list[str] = []
    for path in REPO_ROOT.rglob(pattern):
        if any(part in _EXCLUDE_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.is_file():
            rels.append(path.relative_to(REPO_ROOT).as_posix())
    return rels


def _tag_groups(rels: list[str], *, skip: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for rel in rels:
        if rel in skip:
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        for match in _TAG_RE.finditer(text):
            groups[match.group(1)].append(rel)
    return groups


def groups_by_file() -> dict[str, set[str]]:
    """Repo-relative Python path -> the `TAP-KNOWN-DUPE` group ids it carries.

    The public read of this convention, for other guards that need to ask "are these two
    sites a *declared* duplicate?". The traceability uniqueness guard
    (`req-tap-traceability-uniqueness-2`) is the first consumer: two implementation claims
    for one `(requirement, role)` are permitted exactly when both sites name the same
    known-dupe group — which this convention's own guard independently requires be
    documented in a spec. That composition is what makes "duplicate with an explanation"
    free, instead of a second escape hatch with its own vocabulary.

    Exposed rather than letting a caller re-derive the tag pattern: a second copy of
    `_TAG_RE` is exactly the anti-pattern both conventions exist to prevent.
    """
    by_file: dict[str, set[str]] = defaultdict(set)
    for group_id, rels in _tag_groups(_walk("*.py")).items():
        for rel in rels:
            by_file[rel].add(group_id)
    return dict(by_file)


class KnownDupesGuard(Guard):
    slug = "known-dupes"
    map_row = "Known-dupe group integrity"
    rid = "req-tap-known-dupes"
    description = (
        "An intentional duplicate derivation is tagged TAP-KNOWN-DUPE(<id>) at every site so editing one "
        "side finds the partner. This asserts every group id has >=2 code sites (a singleton tag is stale "
        "or the partner is untagged) and >=1 spec mention (an undocumented group is untracked)."
    )

    def check(self) -> None:
        own = frozenset({"tap/guards/known_dupes.py", "tap/tests/test_known_dupes.py"})
        code_groups = _tag_groups(_walk("*.py"), skip=own)
        spec_rels = [rel for rel in _walk("*.md") if "specs/" in rel or rel.startswith("specs/")]
        spec_groups = _tag_groups(spec_rels)

        problems: list[str] = []
        for group_id, sites in sorted(code_groups.items()):
            if len(sites) < 2:
                problems.append(
                    f"group '{group_id}' has only one code site ({sites[0]}) — partner deleted or never tagged"
                )
            if group_id not in spec_groups:
                problems.append(f"group '{group_id}' is not documented in any spec (no spec names its tag)")
        for group_id in sorted(set(spec_groups) - set(code_groups)):
            problems.append(f"group '{group_id}' is named in specs but has no code sites — stale documentation")

        assert not problems, (
            f"Known-dupe group integrity violations ({len(problems)}):\n  "
            + "\n  ".join(problems)
            + "\n\nEvery TAP-KNOWN-DUPE group needs >=2 tagged code sites and a spec mention; collapsing a "
            "group means removing its tags AND its spec mention together (req-tap-known-dupes)."
        )
