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

#: Where citations are looked for. Text surfaces only; the corpus itself is excluded so an
#: entry naming another entry is scanned like any other prose, not treated as a definition.
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
        """The `WOG-<Name>` form this entry is cited by (`req-wog-citation`)."""
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
        # Guard against a body line that happens to precede a dash rule: a title never
        # follows a non-blank line.
        if i > 0 and lines[i - 1].strip():
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
    """
    out: list[Entry] = []
    for filename, tier in TIER_FILES.items():
        path = WOG_DIR / filename
        if path.exists():
            out.extend(_parse(path, tier))
    return out


def citations() -> dict[str, list[str]]:
    """Every `WOG-*` citation in tracked text → the sorted locations citing it.

    Locations are repo-relative `path:line` strings so a failure names where to look.
    """
    hits: dict[str, list[str]] = {}
    for path in sorted(REPO_ROOT.rglob("*")):
        if path.suffix not in CITATION_SUFFIXES or not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(part in SKIP_DIRS for part in path.parts) or rel.startswith(SKIP_PATHS):
            continue
        if path.parent == WOG_DIR:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "WOG-" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name in CITATION_RE.findall(line):
                hits.setdefault(name, []).append(f"{rel}:{lineno}")
    return {name: sorted(set(locs)) for name, locs in hits.items()}
