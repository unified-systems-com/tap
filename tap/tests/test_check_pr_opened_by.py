"""`scripts/check-pr-opened-by` — the server-side half of the gh pr create redirect
(req-dev-multisession-session-author-scope-3).

A session account's PR from a `session/<name>` branch must carry the marker the promote writes;
anyone else, and any other branch, passes. The marker text must be identical in the check and in
both places the promote writes it, or the check would fail every promote.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check-pr-opened-by"
MARKER = "<!-- tap:opened-by=promote-to-main -->"


def _run(head: str, body: str, login: str, ident: str, kind: str = "User") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PR_BODY": body}
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed check IS the test; argv list, no shell  # nosec B603  # noqa: S603
        [sys.executable, str(CHECK), "--head-ref", head, "--pr-author", login, "--pr-author-id", ident,
         "--pr-author-type", kind],
        capture_output=True, text=True, timeout=30, env=env,
    )


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_a_hand_opened_session_pr_fails_with_the_way_back() -> None:
    result = _run("session/idea-factory", "Opened by hand.", "notgeorge", "286052")
    assert result.returncode == 1
    assert "promote-to-main.sh" in result.stderr


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_a_promote_opened_session_pr_passes() -> None:
    assert _run("session/idea-factory", f"body\n{MARKER}\n", "notgeorge", "286052").returncode == 0


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
@pytest.mark.parametrize(("login", "ident"), [("octocat", "583231"), ("criticalsec", "25269251")])
def test_outside_authors_never_meet_it(login: str, ident: str) -> None:
    assert _run("session/anything", "", login, ident).returncode == 0


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_a_session_account_on_a_non_session_branch_passes() -> None:
    """The promote opens only session/<name>; a maintainer's spike branch (as #1002 was) is not held to it."""
    assert _run("spike/fips-3.5.8", "", "notgeorge", "286052").returncode == 0


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_a_missing_author_id_fails_closed_on_a_session_branch() -> None:
    assert _run("session/x", "", "someone", "").returncode == 1


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_the_marker_is_identical_in_the_check_and_both_promote_writers() -> None:
    check_src = CHECK.read_text(encoding="utf-8")
    body_src = (REPO_ROOT / "scripts" / "promote-pr-body").read_text(encoding="utf-8")
    promote_src = (REPO_ROOT / "scripts" / "promote-to-main.sh").read_text(encoding="utf-8")
    assert re.search(r'^MARKER = "' + re.escape(MARKER) + '"$', check_src, re.M)
    assert re.search(r'^OPENED_BY_MARKER = "' + re.escape(MARKER) + '"$', body_src, re.M)
    assert MARKER in promote_src


@pytest.mark.spec("req-dev-multisession-session-author-scope-3")
def test_the_workflow_reads_the_current_body_through_the_environment() -> None:
    """The body comes from the API (so a re-run sees a promote's refreshed body) and reaches the
    script through the environment, never interpolated into the shell."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "product-lines.yml").read_text(encoding="utf-8")
    step = workflow[workflow.index("Check a session PR was opened by the promote") :]
    step = step[: step.index("\n\n")]
    assert 'gh api "repos/$REPO/pulls/$PR_NUMBER"' in step
    assert "scripts/check-pr-opened-by" in step
    assert "${{ github.event.pull_request.body" not in step
