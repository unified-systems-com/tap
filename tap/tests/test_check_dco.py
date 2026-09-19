"""Behavioral tests for `scripts/check-dco` (req-cicd-dco-signoff).

The DCO check gates every road to `main`, so its verdicts are load-bearing: a
false GREEN publishes uncertified work, and a false RED blocks a promote. Each
test builds a THROWAWAY git repository and runs the real script against it —
never the session repo — so the assertions exercise the shipped artifact end to
end (exit code included) rather than a reimplementation of its logic.

Covers the dispositions the policy defines: signed passes, unsigned fails, an individual
remediation commit retroactively certifies an earlier unsigned commit without rewriting
history, and the bot exemption — which is keyed off the AUTHENTICATED pull-request author
(tap#335), so the negative control matters as much as the positive one: a commit whose
author string merely CLAIMS to be a bot must be REFUSED, or the suite passes for the wrong
reason.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_DCO = REPO_ROOT / "scripts" / "check-dco"

#: Our self-hosted Renovate App, the one approved bot identity used here (tap/tap.pr-bots.json).
TAP_RENOVATE = ("tap-renovate[bot]", "315114127")

# The throwaway-repo fixture is shared with test_check_issue_link.py (one copy, so the suites cannot drift).
from tap.tests.throwaway_repo import (  # noqa: E402
    AUTHOR_EMAIL,
    AUTHOR_NAME,
    run_script,
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
def test_a_spoofed_bot_author_string_is_not_an_exemption(repo: Path) -> None:
    """THE negative control (tap#335). `%an <%ae>` is text the committer sets, so a commit that
    CLAIMS to be renovate's proves nothing. Before the fix this returned 0 — an unsigned change
    passed the DCO gate by lying about its author, leaving a certification in the record that
    nobody made."""
    _commit(repo, "chore(deps): bump x", signed=False, author="renovate[bot] <bot@users.noreply.github.com>")
    result = _check(repo)
    assert result.returncode == 1
    assert "missing Signed-off-by" in result.stderr


def _as(repo: Path, login: str, ident: str, kind: str = "Bot") -> subprocess.CompletedProcess[str]:
    """Run the check the way CI does: with GitHub's authenticated pull-request author."""
    return run_script(
        repo,
        ["bash", str(CHECK_DCO), "--pr-author-id", ident, "--pr-author-type", kind, "--pr-author", login],
    )


@pytest.mark.spec("req-cicd-dco-signoff-2")
def test_an_approved_bot_pull_request_is_exempt(repo: Path) -> None:
    """The exemption survives, keyed off authority: a maintainer certifies the bot's PR at merge."""
    _commit(repo, "chore(deps): bump x", signed=False)
    result = _as(repo, *TAP_RENOVATE)
    assert result.returncode == 0, result.stderr
    assert "approved bot tap-renovate[bot] (id 315114127)" in result.stdout


@pytest.mark.spec("req-cicd-dco-signoff-2")
@pytest.mark.parametrize(
    ("login", "ident", "kind", "why"),
    [
        (TAP_RENOVATE[0], "424242", "Bot", "matching login, wrong id"),
        (TAP_RENOVATE[0], TAP_RENOVATE[1], "User", "matching id, wrong type"),
        ("renovate[bot]", "29139614", "Bot", "stock renovate[bot] is not ours"),
        ("github-actions[bot]", "41898282", "Bot", "never authored a PR here; not on the list"),
        ("octocat", "583231", "User", "a human"),
        ("tap-renovate[bot]", "", "Bot", "no id at all — a login authorizes nothing"),
        ("tap-renovate[bot]", "not-a-number", "Bot", "malformed id"),
    ],
)
def test_anything_but_an_approved_id_and_bot_type_needs_a_sign_off(
    repo: Path, login: str, ident: str, kind: str, why: str
) -> None:
    _commit(repo, "chore(deps): bump x", signed=False)
    result = _as(repo, login, ident, kind)
    assert result.returncode == 1, why
    assert "missing Signed-off-by" in result.stderr, why


@pytest.mark.spec("req-cicd-dco-signoff-2")
def test_a_human_pull_request_carrying_bot_authored_commits_still_needs_a_sign_off(repo: Path) -> None:
    """A human's PR is not the bot's PR: the range is checked however the commits are authored."""
    _commit(
        repo,
        "chore(deps): bump x",
        signed=False,
        author="tap-renovate[bot] <315114127+tap-renovate[bot]@users.noreply.github.com>",
    )
    assert _as(repo, "octocat", "583231", "User").returncode == 1


@pytest.mark.spec("req-cicd-dco-signoff-2")
def test_a_local_run_passes_no_identity_and_exempts_nothing(repo: Path) -> None:
    """The local promote lane has no pull request yet, so it cannot ask GitHub who opened one.
    It therefore exempts nothing — strictly stricter than the server gate, never quieter."""
    _commit(repo, "chore(deps): bump x", signed=False, author="dependabot[bot] <bot@example.com>")
    assert _check(repo).returncode == 1


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
