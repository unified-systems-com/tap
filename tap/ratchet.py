"""Shared compare-and-report core for TAP's ratcheting baselines.

TAP-IMPLEMENTS: req-dev-validation-ratchet-harness@ee65fef30e27/72d556debdd3 (derivation) —
    the one compare-and-report core every ratcheting baseline calls.

A *ratchet* is a committed baseline plus a rule that it may only move one
direction — the house convention for honest coverage accounting
(`spec-dev-validation.md` `req-dev-validation-known-broken`,
`req-dev-validation-ratchet-harness`). The repository independently grew several
(log-site tokens, authz coverage, direct-write coverage, JSON-file naming, the
Gryphon branch-coverage floor, the cold-boot known-broken manifest), each
hand-rolling the same "load baseline → diff → fail on regression → fail/warn on an
unrecorded improvement" loop. This module is that loop, once.

Two directions:

- **ceiling-to-zero** (`ratchet_ceiling`) — a set of known-bad items that must
  never grow and shrinks as they are fixed. A *new* item fails (a regression); a
  *stale* baseline item that no longer occurs also fails, forcing its removal so
  the baseline ratchets toward empty. This second half is what keeps "green"
  honest — a fixed problem cannot silently linger as a permanent exception.
- **floor** (`ratchet_floor`) — a metric that must never regress below a committed
  integer floor; an improvement past the floor reports (or, with `lock_gains`,
  fails) so the gain is captured.

Deliberately Django-free and dependency-free so scripts and tests alike can call
it. Measurement (the AST scan, the coverage run) stays bespoke per surface and
lives in the caller; only the compare-and-report is shared.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from tap.source_scan import DEFAULT_EXCLUDE_DIRS


class RatchetError(AssertionError):
    """A ratchet regressed or carries a stale entry. AssertionError so pytest fails."""


def _out_of_repo_reason(entry: str) -> str | None:
    """Why `entry` references territory a committed baseline must never name, or None.

    Baselines are committed files, and the sync workflow copies locally-observed
    paths into them — which makes them a transport from "seen on a developer's
    machine" into public git history. This is the lexical tripwire on that
    transport: the leading path token of an entry (`path::qualname…`,
    `path:code:count`, or a bare path) must be repo-relative and must not name
    excluded territory — most critically `tap_secrets`, the live secrets mount.
    Lexical on purpose (no filesystem, no git): an escape via the store symlink
    necessarily spells its excluded directory name, and an absolute host path
    spells its leading slash or drive letter. Separator-agnostic: backslash
    entries (`..\\x`, `C:\\tap_secrets\\...`) are judged identically — a
    committed baseline is POSIX by convention, so a backslash path is at best
    foreign and at worst a tripwire dodge (flagged by AI review on PR #105).
    Entries with no separator in the token (RIDs, bare counts) carry no path
    and are not judged.
    """
    head = entry.split("::", 1)[0].strip()
    # Drive-letter check BEFORE the single-colon split: `C:\\x` would otherwise be
    # severed to a bare "C" by the path:code:count parse and slip the tripwire.
    if re.match(r"^[A-Za-z]:[\\/]", head):
        return "absolute path"
    token = head.split(":", 1)[0].strip()
    normalized = token.replace("\\", "/")
    if "/" not in normalized:
        return None
    if normalized.startswith("/"):
        return "absolute path"
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        return "path escapes the repo (`..`)"
    excluded = sorted(set(parts) & DEFAULT_EXCLUDE_DIRS)
    if excluded:
        return f"path under excluded territory ({', '.join(excluded)})"
    return None


def read_baseline_set(path: Path) -> set[str]:
    """Read a line-per-entry baseline file into a set, ignoring blanks and `#` comments.

    A missing file is an empty baseline (strict). This is the shape every
    ceiling ratchet's `_read_baseline` hand-rolled.

    Every entry passes the out-of-repo tripwire (`_out_of_repo_reason`): an
    absolute path, a `..` escape, or a path under `DEFAULT_EXCLUDE_DIRS`
    (`tap_secrets` above all) fails the read outright, so a baseline sync that
    captured forbidden territory turns the guards red before the promote gate
    can ever push it.
    """
    if not path.exists():
        return set()
    entries = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    offenders = sorted(f"{entry}  ({reason})" for entry in entries if (reason := _out_of_repo_reason(entry)))
    if offenders:
        listing = "\n  ".join(offenders)
        raise RatchetError(
            f"[baseline hygiene] {path} carries {len(offenders)} entr(y/ies) referencing territory a "
            f"committed baseline must never name (this file is committed to a public repository):\n  {listing}\n\n"
            "Remove the entries and fix the scanner's exclusions — never widen the baseline to cover them."
        )
    return entries


def ratchet_ceiling(
    *,
    current: set[str],
    baseline: set[str],
    surface: str,
    baseline_path: str | Path,
    new_hint: str,
) -> None:
    """Fail if `current` grows past `baseline`, or if `baseline` has stale entries.

    Args:
        current: the freshly measured set of flagged items.
        baseline: the committed permitted set.
        surface: human name of the validation surface (used in messages).
        baseline_path: where the baseline lives (named in the remediation text).
        new_hint: surface-specific guidance for fixing a NEW violation (the right
            fix first; baselining only as a last resort).

    Raises:
        RatchetError: with a uniform, actionable two-part message.
    """
    new = sorted(current - baseline)
    stale = sorted(baseline - current)
    if not new and not stale:
        return

    parts: list[str] = []
    if new:
        listing = "\n  ".join(new)
        parts.append(
            f"[{surface}] {len(new)} new item(s) not in the baseline:\n  {listing}\n\n"
            f"{new_hint}\n  Last resort: append the line(s) to {baseline_path}."
        )
    if stale:
        listing = "\n  ".join(stale)
        parts.append(
            f"[{surface}] {len(stale)} baseline entr(y/ies) no longer occur — remove them from "
            f"{baseline_path} so the baseline ratchets toward zero:\n  {listing}"
        )
    raise RatchetError("\n\n".join(parts))


def ratchet_floor(
    *,
    current: float,
    floor: int,
    surface: str,
    baseline_path: str | Path,
    lock_gains: bool = False,
) -> str | None:
    """Fail if `current` (integer-floored) is below `floor`.

    Sub-point wobble is not a regression: `current` is floored to a whole number
    before comparison. An improvement past the floor returns a bump-reminder
    string (or, with `lock_gains=True`, raises so the gain must be recorded).

    Returns:
        None when exactly at the floor; a bump-reminder string on improvement
        (unless `lock_gains` made it raise).

    Raises:
        RatchetError: on regression, or on improvement when `lock_gains`.
    """
    current_int = int(current)
    if current_int < floor:
        raise RatchetError(
            f"[{surface}] regressed below the ratchet floor: {current_int} < {floor}. "
            f"Restore the covered behavior, or — if this is a deliberate removal — lower the "
            f"floor in {baseline_path} with a reason."
        )
    if current_int > floor:
        message = (
            f"[{surface}] improved to {current_int} (floor {floor}). Ratchet up: bump the floor "
            f"in {baseline_path} to lock the gain."
        )
        if lock_gains:
            raise RatchetError(message)
        return message
    return None


def ratchet_count(
    *,
    current: int,
    ceiling: int,
    surface: str,
    baseline_path: str | Path,
    lock_gains: bool = True,
) -> str | None:
    """Fail if `current` is above `ceiling`; with `lock_gains`, also fail when it is below.

    The numeric twin of `ratchet_ceiling` for a COUNT of findings (a scanner's open
    issues, a linter's violations): up is a regression, down is a gain that must be
    recorded so the ceiling only ever moves toward zero. The two-sided form is the
    canonical ratchet (qntm; ESLint bulk suppressions): a fixing change lowers the
    number in the same PR, so the baseline can never quietly overstate the debt.

    Returns:
        None when exactly at the ceiling; a lower-the-ceiling reminder on improvement
        when `lock_gains` is False.

    Raises:
        RatchetError: on regression, or on improvement when `lock_gains`.
    """
    if current > ceiling:
        raise RatchetError(
            f"[{surface}] regressed above the ratchet ceiling: {current} > {ceiling}. "
            f"Fix the new findings, or — if this is a deliberate acceptance — raise the ceiling "
            f"in {baseline_path} with a reason."
        )
    if current < ceiling:
        message = (
            f"[{surface}] improved to {current} (ceiling {ceiling}). Ratchet down: lower the ceiling "
            f"in {baseline_path} to lock the gain."
        )
        if lock_gains:
            raise RatchetError(message)
        return message
    return None
