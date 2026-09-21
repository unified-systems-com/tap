"""The triage script must say WHICH COMMIT an AI verdict covers (tap#721).

The unified reviewer edits its comment in place, so `created_at` never moves and a
stale verdict renders identically to a fresh one. Reporting one as current tells the
maintainer that fixed findings are still open — or, in the other direction, that a PR
is clean when no seat has seen it. Both happened in one session before this landed.

Both branches are asserted here: a check that can only ever print one of its outcomes
has not been tested.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "pr-review-triage"

_FUNCTION = re.compile(r"^verdict_coverage\(\) \{.*?^\}$", re.DOTALL | re.MULTILINE)


def _coverage(verdict_at: str, capture_at: str, sha: str = "abc1234567") -> str:
    """Run the script's `verdict_coverage` with explicit values — no network, no API.

    The function is extracted in Python and sourced from a real file rather than a
    process substitution: `source <(...)` is not portable across the environments
    this suite runs in, and it failed silently when it was tried.
    """
    match = _FUNCTION.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, "verdict_coverage() not found in scripts/pr-review-triage"

    with tempfile.TemporaryDirectory() as tmp:
        fn = Path(tmp) / "verdict_coverage.sh"
        fn.write_text(match.group(0) + "\n", encoding="utf-8")
        return subprocess.run(
            ["bash", "-c", 'source "$1"; verdict_coverage "$2" "$3" "$4"', "_", str(fn), verdict_at, capture_at, sha],
            capture_output=True,
            text=True,
            check=True,
        ).stdout


def test_verdict_newer_than_the_review_of_this_head_reads_as_covering_it() -> None:
    out = _coverage("2026-09-21T19:06:48Z", "2026-09-21T19:03:19Z")
    assert "VERDICT COVERAGE: covers abc12345" in out
    assert "STALE" not in out


def test_verdict_older_than_the_review_of_this_head_is_called_stale() -> None:
    out = _coverage("2026-09-21T18:58:15Z", "2026-09-21T18:59:42Z")
    assert "*** VERDICT IS STALE ***" in out
    assert "describe an EARLIER commit" in out


def test_a_three_second_gap_still_decides_rather_than_shrugging() -> None:
    """The ambiguous case that cost a round: seconds apart, and it must still rule."""
    assert "STALE" in _coverage("2026-09-21T18:58:15Z", "2026-09-21T18:58:18Z")
    assert "covers" in _coverage("2026-09-21T18:58:21Z", "2026-09-21T18:58:18Z")
