"""Fitness checks for `architecture.md` — the orientation surface read first by cold readers.

`architecture.md` is prose, and prose has no tests, so its claims rot silently while
every other surface is guarded. The 2026-09 refresh found the doc four months stale
with four Django apps (`tap_boot`, `tap_auth`, `tap_health`, the `tap` core) missing
entirely and four load-bearing claims false — and nothing had flagged any of it,
because the only check a document gets is somebody happening to read it closely.

This guard is the mechanical half of that class: not "is the prose good" (it cannot
know) but "do the claims the prose makes still resolve". Three states, never two — a
path, an app or a requirement is present, absent, or the doc never mentioned it; the
guard speaks only to what the doc actually asserts.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings

from tap.guards.base import REPO_ROOT, Guard
from tap.spec_trace import load_corpus

ARCHITECTURE_DOC = REPO_ROOT / "architecture.md"

# Rows the Subsystems table carries that are NOT Django apps in INSTALLED_APPS.
# Each is a deliberate, named exception; adding one is a visible decision.
_NON_APP_ROWS: dict[str, str] = {
    # The project package: settings, logging, serving, runtime secrets, the guards
    # themselves. Real, load-bearing, and not an installed app.
    "tap": "the project core package, not an installed app",
}

# `tap_secrets` is a spawn-created symlink to the host secret store, not an app, and
# the doc says so in prose. It must never appear as a Subsystems row.
_FORBIDDEN_ROWS: dict[str, str] = {
    "tap_secrets": "a symlink to the host secret store (~/tap-secrets), not an app",
}

# A row in the Subsystems table: | `tap_grid` | The core data model… |
_ROW_APP = re.compile(r"^\|\s*`(tap(?:_[a-z0-9_]+)?)`\s*\|")
# A backticked repo path: `specs/spec-fips.md`, `tap/guards/base.py`, `plan/road-products.md`.
_CITED_PATH = re.compile(r"`([A-Za-z0-9_./-]+\.(?:md|py|json|toml|yml|yaml))`")
# A requirement id in prose or a link.
_CITED_RID = re.compile(r"\b(req-[a-z0-9-]+)\b")
# A file:line citation — banned outright: line numbers rot on the next edit to that
# file, and a citation that no longer resolves reads as verification.
_LINE_CITATION = re.compile(r"`[A-Za-z0-9_./-]+\.(?:py|md|json|toml|yml|yaml):\d+`")


def _installed_tap_apps() -> set[str]:
    """The `tap*` apps this instance actually installs, by package name."""
    apps: set[str] = set()
    for entry in settings.INSTALLED_APPS:
        package = entry.split(".")[0]
        if package == "tap" or package.startswith("tap_"):
            apps.add(package)
    return apps


def _subsystem_rows(text: str) -> set[str]:
    """App names named as rows of the Subsystems table."""
    return {match.group(1) for line in text.splitlines() if (match := _ROW_APP.match(line))}


class ArchitectureDocGuard(Guard):
    """Asserts `architecture.md`'s checkable claims still resolve."""

    slug = "architecture-doc-fitness"
    map_row = "architecture.md fitness"
    rid = "req-docs-architecture-fitness"
    description = (
        "architecture.md is the first thing a cold reader — human or AI assistant — reads, and it is "
        "the one surface in the tree whose claims nothing tests. Left unguarded it goes quietly false: "
        "the 2026-09 refresh found four installed apps undocumented and four load-bearing claims wrong, "
        "months after the fact. A doc that is wrong is worse than one that is missing, because nobody "
        "goes looking for the thing the record says is handled."
    )

    def check(self) -> None:
        """TAP-IMPLEMENTS: req-docs-architecture-fitness (enforcement) — every checkable claim
        architecture.md makes about apps, paths and requirements resolves against this tree.
        """
        text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
        failures: list[str] = []

        documented = _subsystem_rows(text)
        installed = _installed_tap_apps()

        for app in sorted(installed - documented - set(_NON_APP_ROWS)):
            failures.append(
                f"{app} is in INSTALLED_APPS but has no row in architecture.md's Subsystems table. "
                "A subsystem nobody documented is one nobody can find: add a row saying what it OWNS."
            )
        for row in sorted(documented - installed - set(_NON_APP_ROWS)):
            reason = _FORBIDDEN_ROWS.get(row)
            failures.append(
                f"architecture.md's Subsystems table has a row for {row}, which is not an installed app"
                + (f" — {reason}." if reason else ". Remove the row, or add it to _NON_APP_ROWS with a reason.")
            )

        for path in sorted({m.group(1) for m in _CITED_PATH.finditer(text)}):
            if not (REPO_ROOT / path).exists():
                failures.append(
                    f"architecture.md cites `{path}`, which does not exist. A citation that does not "
                    "resolve reads as verification — repoint it or drop it."
                )

        # `defined` is the flat union a citation must resolve against — requirements,
        # ACIDs (`req-x-1`) and bare table-row ids alike.
        known_rids = set(load_corpus(REPO_ROOT).defined)
        for rid in sorted({m.group(1) for m in _CITED_RID.finditer(text)}):
            if rid not in known_rids:
                failures.append(
                    f"architecture.md cites `{rid}`, which is not defined in any spec. RIDs are the "
                    "stable, searchable anchors this doc is allowed to lean on; a dangling one is a lie."
                )

        for match in _LINE_CITATION.finditer(text):
            failures.append(
                f"architecture.md cites {match.group(0)} with a line number. Line numbers rot on the "
                "next edit to that file: cite the path, or better, the requirement id."
            )

        assert not failures, "architecture.md fitness:\n  - " + "\n  - ".join(failures)


def architecture_doc_path() -> Path:
    """The guarded document, for tests and the update-architecture skill."""
    return ARCHITECTURE_DOC
