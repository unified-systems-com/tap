"""Behavioral tests for `scripts/check-issue-link` (req-cicd-issue-link).

The issue-link check gates every road to `main` beside the DCO check, so its verdicts are
load-bearing: a false GREEN lands work whose issue stays open, a false RED blocks a promote.
Each test builds a THROWAWAY git repository and runs the real script against it — never the
session repo — so the assertions exercise the shipped artifact end to end, exit code included.

Covers: a qualified `Closes:` passes and is emitted in GitHub's form; `Part-of:` and `No-issue:`
pass; a range with no trailer fails; a bare `#n` fails with the qualified-form hint; a bot-authored
commit is exempt; the verdict is per range (one trailer covers fix-up commits); `--emit` prints
closes first and deduplicates.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check-issue-link"

# The throwaway-repo fixture is shared with test_check_dco.py (one copy, so the suites cannot drift).
from tap.tests.throwaway_repo import commit as _commit  # noqa: E402
from tap.tests.throwaway_repo import (
    run_script,  # noqa: E402
)


def _run(repo: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return run_script(repo, ["python3", str(CHECK), *args], **env)


@pytest.mark.spec("req-cicd-issue-link-1")
def test_qualified_closes_passes_and_emits_githubs_form(repo: Path) -> None:
    _commit(repo, "feat: x\n\nCloses: unified-systems-com/tap#327\nSigned-off-by: Ada <ada@example.com>")
    result = _run(repo)
    assert result.returncode == 0, result.stdout
    emitted = _run(repo, "--emit")
    assert emitted.stdout.splitlines() == ["Closes unified-systems-com/tap#327"]


@pytest.mark.spec("req-cicd-issue-link-1")
def test_part_of_and_no_issue_pass(repo: Path) -> None:
    _commit(repo, "docs: a\n\nPart-of: unified-systems-com/tap#211")
    _commit(repo, "chore: b\n\nNo-issue: whitespace-only reflow of a comment")
    result = _run(repo)
    assert result.returncode == 0, result.stdout
    emitted = _run(repo, "--emit").stdout.splitlines()
    assert emitted == ["Part of unified-systems-com/tap#211", "No issue: whitespace-only reflow of a comment"]


@pytest.mark.spec("req-cicd-issue-link-3")
def test_no_issue_needs_a_reason_of_some_length(repo: Path) -> None:
    """`No-issue: fix` is a shrug, not a reason; the threshold is the script's named constant."""
    _commit(repo, "chore: c\n\nNo-issue: fix")
    result = _run(repo)
    assert result.returncode == 1 and "needs a reason" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-4")
def test_emit_sorts_issue_numbers_numerically(repo: Path) -> None:
    _commit(repo, "a\n\nCloses: o/r#10, o/r#2, o/r#9")
    assert _run(repo, "--emit").stdout.splitlines() == ["Closes o/r#2", "Closes o/r#9", "Closes o/r#10"]


@pytest.mark.spec("req-cicd-issue-link-2")
def test_range_without_a_trailer_fails(repo: Path) -> None:
    _commit(repo, "feat: quietly lands something")
    result = _run(repo)
    assert result.returncode == 1
    assert "names its issue" in result.stdout
    assert "Closes: owner/repo#n" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-3")
def test_bare_number_is_rejected_with_the_qualified_hint(repo: Path) -> None:
    _commit(repo, "fix: y\n\nCloses: #12")
    result = _run(repo)
    assert result.returncode == 1
    assert "bare #12" in result.stdout and "owner/repo#n" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-2")
def test_one_trailer_covers_the_whole_range(repo: Path) -> None:
    """The verdict is per range: a fix-up commit need not repeat the trailer."""
    _commit(repo, "feat: z\n\nCloses: unified-systems-com/tap#1")
    _commit(repo, "fix: review round")
    _commit(repo, "fix: another round")
    assert _run(repo).returncode == 0


@pytest.mark.spec("req-cicd-issue-link-2")
def test_bot_authored_commit_is_exempt(repo: Path) -> None:
    _commit(repo, "chore(deps): bump x", author="renovate[bot] <renovate@example.com>")
    result = _run(repo)
    assert result.returncode == 0 and "nothing to check" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-2")
def test_report_only_escape_hatch_lists_but_does_not_fail(repo: Path) -> None:
    _commit(repo, "feat: unlinked")
    result = _run(repo, TAP_ISSUE_LINK_REPORT_ONLY="1")
    assert result.returncode == 0 and "reporting only" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-4")
def test_emit_puts_closes_first_and_deduplicates(repo: Path) -> None:
    _commit(repo, "a\n\nPart-of: o/r#2\nCloses: o/r#9")
    _commit(repo, "b\n\nCloses: o/r#9, https://github.com/o/r/issues/3")
    emitted = _run(repo, "--emit").stdout.splitlines()
    assert emitted == ["Closes o/r#3", "Closes o/r#9", "Part of o/r#2"]
