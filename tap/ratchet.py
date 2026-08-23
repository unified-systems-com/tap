"""Shared compare-and-report core for TAP's ratcheting baselines.

TAP-IMPLEMENTS: req-dev-validation-ratchet-harness@08c0ee3cb084/ed2447ee1873 (derivation) —
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

from pathlib import Path


class RatchetError(AssertionError):
    """A ratchet regressed or carries a stale entry. AssertionError so pytest fails."""


def read_baseline_set(path: Path) -> set[str]:
    """Read a line-per-entry baseline file into a set, ignoring blanks and `#` comments.

    A missing file is an empty baseline (strict). This is the shape every
    ceiling ratchet's `_read_baseline` hand-rolled.
    """
    if not path.exists():
        return set()
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


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
