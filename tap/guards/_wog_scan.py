"""WOG corpus scan — the single parse behind every WOG guard (`specs/spec-wog.md`).

One parser, three consumers (`wog_entry_shape`, `wog_name_uniqueness`,
`wog_citation_resolution`), so the entry grammar is derived once rather than
re-implemented per guard.

The grammar is deliberately minimal (`req-wog-entry-shape`): a title line, an underline of
`-` exactly as long as the title, then body text until the next entry. Files open with their
own title over a `=` underline, which is skipped. Stdlib-only — this reads plain text and
never boots Django.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# tap/guards/_wog_scan.py → parents[2] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[2]

WOG_DIR = REPO_ROOT / "wog"

#: Tier file → the tier label reported to a reader (`req-wog-tiers`).
TIER_FILES: dict[str, str] = {
    "wog.txt": "settled",
    "wog-in-process.txt": "in process",
    "wog-apocrypha.txt": "apocrypha",
}

#: A citation: `WOG-` plus a dash-joined name (`req-wog-citation`). Requires a letter or
#: digit first so a placeholder like `WOG-<Name>` is not mistaken for a real citation.
CITATION_RE = re.compile(r"\bWOG-[A-Za-z0-9][A-Za-z0-9-]*")

#: Where citations are looked for. Text surfaces only. The corpus is scanned like anything
#: else: `req-wog-resolution-1` says every citation in tracked text resolves, with no carve-out,
#: and an entry pointing at a sibling that does not exist is the same defect anywhere else.
#: Entry titles are bare names rather than `WOG-` forms, so a definition is never read as a
#: citation of itself.
CITATION_SUFFIXES = frozenset({".md", ".py", ".txt", ".toml", ".yml", ".yaml"})

#: Directories never scanned: VCS internals, virtualenvs, build output, and dated evidence
#: (a historical scan artifact must stay byte-stable, so it cannot be held to today's corpus).
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
SKIP_PATHS = ("docs/security/scans/", "docs/aar/", "docs/handoff/")


@dataclass(frozen=True)
class Entry:
    """One WOG entry: its name, the tier it currently sits in, and where it lives."""

    name: str
    tier: str
    path: Path
    line: int
    underline: str
    body: str

    @property
    def citation(self) -> str:
        """The `WOG-<Name>` form this entry is cited by (`req-wog-citation`).

        TAP-IMPLEMENTS: req-wog-citation@06feaba702b3/b653d6b74c9c (derivation) — the one place a
        name becomes a citation; resolution compares against this rather than re-deriving the form.
        """
        return "WOG-" + self.name.replace(" ", "-")


def _parse(path: Path, tier: str) -> list[Entry]:
    lines = path.read_text(encoding="utf-8").splitlines()
    found: list[tuple[int, str, str]] = []
    for i in range(len(lines) - 1):
        title, under = lines[i].rstrip(), lines[i + 1]
        # A file's own header uses `=`; entries use `-`. Skip anything that is not a
        # dash rule, and require a non-empty title above it.
        if not title or not under or set(under) != {"-"}:
            continue
        # Disambiguate a title from a body line that happens to precede a dash rule. The
        # spec's rule is the matching length (`req-wog-entry-shape`), so that alone is
        # enough; a preceding blank line is the *other* sufficient signal, which is what
        # keeps a mis-underlined entry visible for `wog-entry-shape` to complain about
        # rather than silently unparsed. Requiring the blank line unconditionally would
        # drop the first entry in a file, which sits directly under the `=` header rule.
        if i > 0 and lines[i - 1].strip() and len(under) != len(title):
            continue
        found.append((i, title, under))

    entries: list[Entry] = []
    for idx, (i, title, under) in enumerate(found):
        end = found[idx + 1][0] if idx + 1 < len(found) else len(lines)
        body = "\n".join(lines[i + 2 : end]).strip()
        entries.append(Entry(name=title, tier=tier, path=path, line=i + 1, underline=under, body=body))
    return entries


def entries() -> list[Entry]:
    """Every entry across every tier file, in file then document order.

    The resolver reads all three tiers and reports which one an entry occupies
    (`req-wog-resolution-2`), so a citation never has to encode its own tier.

    TAP-IMPLEMENTS: req-wog-tiers@386bade0f0db/c2ddccd5689d (derivation) — the one place an entry
    acquires its tier: status is read from the file it lives in (via `TIER_FILES`), never from
    anything stored on the entry itself, so a promotion is a move and nothing else.
    """
    out: list[Entry] = []
    for filename, tier in TIER_FILES.items():
        path = WOG_DIR / filename
        if path.exists():
            out.extend(_parse(path, tier))
    return out


def _candidate_files() -> list[Path]:
    """Text files a citation could live in, in a stable order.

    Skipped trees are pruned *during* the walk rather than filtered after it. This runs on
    every commit, and `.git`/`.venv`/`node_modules` are the overwhelming majority of the
    tree — descending into them to discard the results is the expensive way to get the same
    answer.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        here = Path(dirpath)
        for name in filenames:
            path = here / name
            if path.suffix not in CITATION_SUFFIXES:
                continue
            if path.relative_to(REPO_ROOT).as_posix().startswith(SKIP_PATHS):
                continue
            out.append(path)
    return sorted(out)


def citations() -> dict[str, list[str]]:
    """Every `WOG-*` citation in tracked text → the sorted locations citing it.

    Locations are repo-relative `path:line` strings so a failure names where to look.
    """
    hits: dict[str, list[str]] = {}
    for path in _candidate_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        # Unparenthesized except group: valid since PEP 758 (Python 3.14, our floor), and
        # black rewrites it to this form, so the parenthesized version cannot be kept. Static
        # analysers trained on older grammars read it as Python 2 and call it a SyntaxError.
        except UnicodeDecodeError, OSError:
            continue
        if "WOG-" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name in CITATION_RE.findall(line):
                hits.setdefault(name, []).append(f"{rel}:{lineno}")
    return {name: sorted(set(locs)) for name, locs in hits.items()}
