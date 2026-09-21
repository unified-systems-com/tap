"""The triage script must say WHICH COMMIT an AI verdict covers (tap#721).

The unified reviewer edits its comment in place, so `created_at` never moves and a
stale verdict renders identically to a fresh one. Reporting one as current tells the
maintainer that fixed findings are open — or, in the other direction, that a PR is
clean when no seat has seen it. This asserts both branches, because a check that can
only print one outcome has not been tested.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr-review-triage"


def _coverage(verdict_at: str, capture_at: str, sha: str = "abc1234567") -> str:
    """Call the script's `verdict_coverage` with explicit values, no API."""
    extract = f"sed -n '/^verdict_coverage()/,/^}}$/p' {SCRIPT!s}"
    return subprocess.run(
        ["bash", "-c", f'source <({extract}); verdict_coverage "$1" "$2" "$3"', "_", verdict_at, capture_at, sha],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_verdict_newer_than_the_review_of_this_head_reads_as_covering_it() -> None:
    out = _coverage("2026-09-21T19:06:48Z", "2026-09-21T19:03:19Z")
    assert "VERDICT COVERAGE: covers abc12345" in out
    assert "STALE" not in out


def test_verdict_older_than_the_review_of_this_head_is_called_stale() -> None:
    # The real shape from tap#721: comment 18:58:15Z, capture for that head 18:59:42Z.
    out = _coverage("2026-09-21T18:58:15Z", "2026-09-21T18:59:42Z")
    assert "*** VERDICT IS STALE ***" in out
    assert "describe an EARLIER commit" in out
    assert "covers" not in out.split("STALE")[0]


def test_a_three_second_gap_still_decides_rather_than_shrugging() -> None:
    """The ambiguous case that cost a round: seconds apart, and it must still rule."""
    assert "STALE" in _coverage("2026-09-21T18:58:15Z", "2026-09-21T18:58:18Z")
    assert "covers" in _coverage("2026-09-21T18:58:21Z", "2026-09-21T18:58:18Z")
