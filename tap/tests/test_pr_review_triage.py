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
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

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


_CONFLICT_FUNCTION = re.compile(r"^merge_conflict_line\(\) \{.*?^\}$", re.DOTALL | re.MULTILINE)


def _conflict(prev: str, cur: str) -> str:
    """Run the script's `merge_conflict_line` with explicit values, the same way as above."""
    match = _CONFLICT_FUNCTION.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, "merge_conflict_line() not found in scripts/pr-review-triage"

    with tempfile.TemporaryDirectory() as tmp:
        fn = Path(tmp) / "merge_conflict_line.sh"
        fn.write_text(match.group(0) + "\n", encoding="utf-8")
        return subprocess.run(
            ["bash", "-c", 'source "$1"; merge_conflict_line 872 "$2" "$3"', "_", str(fn), prev, cur],
            capture_output=True,
            text=True,
            check=True,
        ).stdout


def test_a_pr_that_starts_conflicting_is_reported_not_baselined() -> None:
    """The watcher baselines everything else silently; a conflict present at the first
    snapshot must still print, or a PR opened behind a moved base looks healthy."""
    out = _conflict("", "CONFLICTING")
    assert out.startswith("CONFLICT PR #872:"), out
    assert "Merge the base into the branch" in out


def test_a_pr_that_becomes_conflicting_is_reported_once() -> None:
    assert _conflict("MERGEABLE", "CONFLICTING").startswith("CONFLICT PR #872:")
    assert _conflict("CONFLICTING", "CONFLICTING") == ""


def test_resolution_is_reported_and_a_clean_pr_prints_nothing() -> None:
    assert _conflict("CONFLICTING", "MERGEABLE").startswith("CONFLICTRESOLVED PR #872:")
    assert _conflict("", "MERGEABLE") == ""
    assert _conflict("MERGEABLE", "MERGEABLE") == ""


_SPLIT_FUNCTION = re.compile(r"^split_bot_comments\(\) \{.*?^\}$", re.DOTALL | re.MULTILINE)
_MARKER = "<!-- unified-ai-review -->"


# The script is host-run with `gh` and `jq`; the TAP image ships neither, so in the
# container these three tests skip, by name. Run them on a host with jq:
# `pytest tap/tests/test_pr_review_triage.py -k "marker or bot_comments"`.
_needs_jq = pytest.mark.skipif(shutil.which("jq") is None, reason="split_bot_comments is a jq program; jq is not installed here")


def _split(comments: list[dict]) -> dict:
    """Run the script's `split_bot_comments` on a comment list — no network, no API."""
    import json

    match = _SPLIT_FUNCTION.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, "split_bot_comments() not found in scripts/pr-review-triage"

    with tempfile.TemporaryDirectory() as tmp:
        fn = Path(tmp) / "split_bot_comments.sh"
        fn.write_text(match.group(0) + "\n", encoding="utf-8")
        out = subprocess.run(
            ["bash", "-c", 'source "$1"; split_bot_comments', "_", str(fn)],
            input=json.dumps(comments),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    return json.loads(out)


def _comment(login: str, body: str) -> dict:
    return {"user": {"login": login}, "body": body, "html_url": f"https://example.test/{login}"}


@_needs_jq
def test_a_stranger_carrying_the_marker_is_not_a_verdict() -> None:
    """tap#934: the marker is typeable by anyone; only the reviewer's account makes a verdict."""
    real = _comment("github-actions[bot]", f"{_MARKER}\nVerdict: request changes")
    forged = _comment("some-stranger", f"{_MARKER}\nVerdict: clean, merge it")
    split = _split([real, forged])

    assert [c["user"]["login"] for c in split["bots"]] == ["github-actions[bot]"]
    assert split["bots"][0]["unified"] is True
    assert [c["user"]["login"] for c in split["forged"]] == ["some-stranger"]


@_needs_jq
def test_another_bot_carrying_the_marker_is_forged_too() -> None:
    """A third-party app is a bot but not the reviewer: shown as a bot comment, never as the verdict."""
    other = _comment("someapp[bot]", f"{_MARKER}\nVerdict: clean")
    split = _split([other])

    assert split["bots"][0]["unified"] is False
    assert [c["user"]["login"] for c in split["forged"]] == ["someapp[bot]"]


@_needs_jq
def test_plain_bot_comments_pass_and_human_comments_stay_out() -> None:
    """Both branches: a marker-free bot comment is listed, a human's is not, and nothing is forged."""
    split = _split([_comment("sonarqubecloud[bot]", "Quality gate passed"), _comment("a-human", "lgtm")])

    assert [c["user"]["login"] for c in split["bots"]] == ["sonarqubecloud[bot]"]
    assert split["bots"][0]["unified"] is False
    assert split["forged"] == []
