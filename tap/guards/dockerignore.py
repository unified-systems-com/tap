"""Image build-context guard — `specs/spec-cicd-hardening.md` (`req-cicd-image-context-4`).

The repository's `.dockerignore` keeps test inputs that name vulnerable software on purpose out of the
published images (`req-cicd-image-context`). Every line of it is there for a numbered reason of the
section's Reason Register, so this guard parses the file and fails on:

* a pattern outside a block, or in a block with no reason comment line;
* a block whose last comment line is not `# spec: <RID>`;
* a `# spec:` line naming a RID that is not a row of the Reason Register
  (`req-cicd-image-context-reason-<n>`);
* a `#` on a pattern line (Docker reads it as part of the pattern, not as a comment);
* a pattern that matches no path of the tree (a stale line).

A block is one or more comment lines, then the patterns they explain, then a blank line
(`req-cicd-image-context-3`). The pattern matcher follows Docker's own rules closely enough for the
shapes this file uses: `*` and `?` stay inside one path segment, `**` crosses segments, a leading `!`
re-includes, a leading `/` is dropped (the context root is the repository root), and a pattern that
names a directory matches everything below it.

The tree is read with a filesystem walk rather than `git ls-files`, so the guard runs in the container
(a worktree's `.git` file points at a host path the container cannot see) and in a plain checkout alike.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable

from tap.guards.base import REPO_ROOT, Guard, defined_requirement_rids

REASON_PREFIX = "req-cicd-image-context-reason-"
_SPEC_LINE = re.compile(r"^#\s*spec:\s*(\S+)\s*$")
_REASON_RID = re.compile(r"^req-cicd-image-context-reason-\d+$")

# Directories that are never part of the tracked tree; pruned from the walk.
_PRUNE = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _pattern_regex(pattern: str) -> re.Pattern[str]:
    """Translate one Docker ignore pattern into a regex over a `/`-separated repository path."""
    pattern = pattern.lstrip("!").lstrip("/").rstrip("/")
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    # A pattern also covers everything below a directory it names.
    return re.compile("^" + "".join(out) + "(?:/.*)?$")


def lint_dockerignore(text: str, reasons: set[str], paths: Iterable[str]) -> list[str]:
    """Return one message per defect in a `.dockerignore` text; an empty list means it conforms.

    TAP-IMPLEMENTS: req-cicd-image-context@634a87edbeb7/de10a7d209d6 (enforcement) — the one predicate
        deciding whether a `.dockerignore` line has its reason and spec line, names a Reason Register
        row, carries no trailing `#`, and matches a path of the tree.

    Args:
        text: The file's contents.
        reasons: The RIDs of the Reason Register's rows.
        paths: Repository-relative `/`-separated paths a pattern may match.
    """
    defects: list[str] = []
    path_list = list(paths)
    comments: list[str] = []
    patterns: list[tuple[int, str]] = []

    def close_block() -> None:
        if not patterns:
            comments.clear()
            return
        first_line, first_pattern = patterns[0]
        if not comments:
            defects.append(f"line {first_line}: pattern {first_pattern!r} has no reason comment line above it")
        else:
            spec = _SPEC_LINE.match(comments[-1])
            if spec is None:
                defects.append(
                    f"line {first_line}: the block of {first_pattern!r} does not end its comment lines with "
                    f"'# spec: <RID>' naming a Reason Register row"
                )
            else:
                if spec.group(1) not in reasons:
                    defects.append(
                        f"line {first_line}: '# spec: {spec.group(1)}' names no row of the Reason Register "
                        f"(known: {', '.join(sorted(reasons)) or 'none'})"
                    )
                if len(comments) < 2:
                    defects.append(
                        f"line {first_line}: the block of {first_pattern!r} has a spec line but no reason "
                        f"sentence above it"
                    )
        comments.clear()
        patterns.clear()

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            close_block()
        elif line.startswith("#"):
            if patterns:
                # A comment after patterns starts a new block.
                close_block()
            comments.append(line)
        else:
            patterns.append((number, line))
            if "#" in line:
                defects.append(
                    f"line {number}: '#' on pattern line {line!r}; Docker reads it as part of the pattern, "
                    f"so a trailing comment silently breaks the match"
                )
    close_block()

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#") or "#" in line:
            continue
        regex = _pattern_regex(line)
        if not any(regex.match(p) for p in path_list):
            defects.append(f"line {number}: pattern {line!r} matches no path of the tree (a stale line)")
    return defects


def _tree_paths() -> list[str]:
    paths: list[str] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = sorted(d for d in dirs if d not in _PRUNE)
        rel_root = os.path.relpath(root, REPO_ROOT)
        prefix = "" if rel_root == "." else rel_root.replace(os.sep, "/") + "/"
        paths.extend(prefix + f for f in files)
    return paths


class DockerignoreGuard(Guard):
    slug = "dockerignore-reasons"
    map_row = "Image build context (.dockerignore)"
    rid = "req-cicd-image-context-4"
    description = (
        "A scanner reads an image as an inventory and cannot tell a fixture that names vulnerable software "
        "on purpose from an install, so the .dockerignore keeps those out, and a list nobody can explain "
        "rots. This fails a line with no reason or spec line, a spec line naming no Reason Register row, a "
        "trailing # that Docker would read as pattern text, or a pattern that matches nothing."
    )

    def check(self) -> None:
        reasons = {rid for rid in defined_requirement_rids() if _REASON_RID.match(rid)}
        text = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
        defects = lint_dockerignore(text, reasons, _tree_paths())
        assert not defects, (  # nosec B101
            ".dockerignore breaks req-cicd-image-context-3/-4:\n  "
            + "\n  ".join(defects)
            + "\n\nEach block is a reason sentence, a '# spec: req-cicd-image-context-reason-<n>' line naming a "
            "row of the Reason Register in specs/spec-cicd-hardening.md, then its patterns. Add the reason "
            "to the register before citing it."
        )
