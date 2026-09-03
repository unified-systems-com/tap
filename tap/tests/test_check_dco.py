"""Behavioral tests for `scripts/check-dco` (req-cicd-dco-signoff).

The DCO check gates every road to `main`, so its verdicts are load-bearing: a
false GREEN publishes uncertified work, and a false RED blocks a promote. Each
test builds a THROWAWAY git repository and runs the real script against it —
never the session repo — so the assertions exercise the shipped artifact end to
end (exit code included) rather than a reimplementation of its logic.

Covers the four dispositions the policy defines: signed passes, unsigned fails,
bot-authored is exempt, and an individual remediation commit retroactively
certifies an earlier unsigned commit without rewriting history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_DCO = REPO_ROOT / "scripts" / "check-dco"

# The throwaway-repo fixture is shared with test_check_issue_link.py (one copy, so the suites cannot drift).
from tap.tests.throwaway_repo import (  # noqa: E402, F401
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    run_script,  # noqa: E402
    throwaway_repo,  # noqa: E402, F401 — registers the `repo` fixture
)
from tap.tests.throwaway_repo import commit as _commit  # noqa: E402
from tap.tests.throwaway_repo import git as _git  # noqa: E402, F401


def _check(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the real scripts/check-dco against the throwaway repo, base ref `base`."""
    return run_script(repo, ["bash", str(CHECK_DCO)])


@pytest.mark.spec("req-cicd-dco-signoff-2")
def test_signed_commit_passes(repo: Path) -> None:
    _commit(repo, "signed work", signed=True)
    assert _check(repo).returncode == 0


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_unsigned_commit_fails(repo: Path) -> None:
    _commit(repo, "unsigned work", signed=False)
    result = _check(repo)
    assert result.returncode == 1
    assert "missing Signed-off-by" in result.stderr


@pytest.mark.spec("req-cicd-dco-signoff-2")
def test_bot_authored_commit_is_exempt(repo: Path) -> None:
    """A bot must not certify the DCO, so its unsigned commits cannot be violations."""
    _commit(repo, "bot bump", signed=False, author="renovate[bot] <bot@users.noreply.github.com>")
    assert _check(repo).returncode == 0


@pytest.mark.spec("req-cicd-dco-signoff-4")
def test_remediation_commit_certifies_earlier_unsigned_commit(repo: Path) -> None:
    """History stays intact: a later signed declaration certifies the earlier commit."""
    target = _commit(repo, "unsigned work", signed=False)
    _commit(
        repo,
        f"I, {AUTHOR_NAME} <{AUTHOR_EMAIL}>, hereby add my Signed-off-by to this commit: {target}",
        signed=True,
    )
    result = _check(repo)
    assert result.returncode == 0, result.stderr
    assert "remediated" in result.stdout


@pytest.mark.spec("req-cicd-dco-signoff-4")
def test_remediation_by_a_different_identity_is_rejected(repo: Path) -> None:
    """Individual remediation certifies your OWN work — not somebody else's."""
    target = _commit(repo, "unsigned work", signed=False)
    _commit(
        repo,
        f"I, Someone Else <else@example.com>, hereby add my Signed-off-by to this commit: {target}",
        signed=True,
        author="Someone Else <else@example.com>",
    )
    result = _check(repo)
    assert result.returncode == 1
    assert "missing Signed-off-by" in result.stderr
