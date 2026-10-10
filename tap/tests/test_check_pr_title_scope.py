"""`scripts/check-pr-title` applies only to the maintainer's session accounts
(req-dev-multisession-session-author-scope-2).

Before 2026-10-09 the check failed every non-bot pull request whose title lacked `[via <session>]`,
so an outside contributor's first PR went red on a convention of our agent sessions. Each case
runs the real script with the identity GitHub's authenticated event would pass.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check-pr-title"


def _run(title: str, login: str, ident: str, kind: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed check IS the test; argv list, no shell  # nosec B603  # noqa: S603
        [sys.executable, str(CHECK), "--title", title, "--pr-author", login, "--pr-author-id", ident,
         "--pr-author-type", kind],
        capture_output=True, text=True, timeout=30,
    )


@pytest.mark.spec("req-dev-multisession-session-author-scope-2")
def test_the_session_account_needs_a_session_title() -> None:
    assert _run("fix: thing", "notgeorge", "286052", "User").returncode == 1
    assert _run("fix: thing [via idea-factory]", "notgeorge", "286052", "User").returncode == 0
    assert _run("promote: idea-factory → main", "notgeorge", "286052", "User").returncode == 0


@pytest.mark.spec("req-dev-multisession-session-author-scope-2")
@pytest.mark.parametrize(
    ("login", "ident"),
    [("octocat", "583231"), ("criticalsec", "25269251"), ("notgeorge", "424242")],
)
def test_an_outside_author_writes_their_own_title(login: str, ident: str) -> None:
    result = _run("Fix a typo in the README", login, ident, "User")
    assert result.returncode == 0, result.stderr
    assert "not a session account" in result.stdout


@pytest.mark.spec("req-dev-multisession-session-author-scope-2")
def test_a_missing_author_id_fails_closed() -> None:
    assert _run("fix: thing", "someone", "", "User").returncode == 1


@pytest.mark.spec("req-dev-multisession-session-author-scope-2")
def test_the_failure_points_at_the_promote_not_a_hand_run_create() -> None:
    message = _run("fix: thing", "notgeorge", "286052", "User").stderr
    assert "promote-to-main.sh" in message
    assert "gh pr create" not in message
