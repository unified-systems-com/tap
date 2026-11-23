"""The PostToolUse hook that tells a session to arm the review watch
(req-dev-multisession-review-triage-check, Issue# 1317 - tap).

It is a local-execution surface (specs/spec-dev-local-execution.md), so it is tested the way its
header promises it behaves: it speaks after the two commands that open a pull request, it says
nothing after anything else, it still delivers the instruction when it cannot find the pull
request number, and it is wired by a settings file that holds only a pointer.

Each case runs the real script in a subprocess against a throwaway repository, the same way
Claude Code runs it: the PostToolUse payload on stdin, CLAUDE_PROJECT_DIR in the environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pr-watch-prompt"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"

PROJECT_SLUG = "example-org/tap"

# Assembled at runtime so this file never holds the literal invocations at a line start.
PROMOTE = "scripts/" + "promote-to-main.sh"
PR_CREATE = " ".join(["gh", "pr", "create"])


def _make_repo(path: Path, origin: str) -> Path:
    (path / ".git").mkdir(parents=True)
    (path / ".git" / "config").write_text(
        f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {origin}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, Path]:
    """A session checkout beside a `main` checkout, with a plugin checkout nested inside it."""
    sessions = tmp_path / "tap-sessions"
    project = _make_repo(sessions / "idea", f"https://github.com/{PROJECT_SLUG}.git")
    (project / ".git" / "HEAD").write_text("ref: refs/heads/session/idea\n", encoding="utf-8")
    main = _make_repo(sessions / "main", f"https://github.com/{PROJECT_SLUG}.git")
    plugin = _make_repo(project / "_dev-plugins" / "github_core", "git@github.com:example-org/github-core-tap.git")
    return {"project": project, "main": main, "plugin": plugin}


def _run(payload: object, project_dir: Path | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed hook under the test's own interpreter is the test
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


def _said(command: str, cwd: Path, project: Path, response: object = "") -> str:
    """The additionalContext the hook emitted for this call, or "" when it said nothing."""
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}, "tool_response": response}
    result = _run(payload, project)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if not result.stdout.strip():
        return ""
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert set(out) == {"hookEventName", "additionalContext"}, "it makes no permission decision"
    assert out["hookEventName"] == "PostToolUse"
    return str(out["additionalContext"])


@pytest.mark.spec("req-dev-multisession-review-triage-check-9")
@pytest.mark.parametrize(
    "command",
    [
        PROMOTE,
        f"./{PROMOTE} 2>&1 | tee /tmp/promote.log",
        f"bash {PROMOTE}",
        f"cd /somewhere && {PROMOTE}",
        f"TAP_X=1 {PROMOTE} > /tmp/p.log 2>&1",
        f"git status\n{PROMOTE}",
    ],
)
def test_a_promote_gets_the_instruction_to_arm_the_watch(repos: dict[str, Path], command: str) -> None:
    said = _said(command, repos["project"], repos["project"], {"stdout": "PR #1317 opened", "stderr": ""})
    assert "scripts/pr-review-triage 1317 --watch" in said
    assert "as a Monitor" in said
    assert "BLOCKS until it merges" in said
    assert f"`{repos['main']}`" in said and "never from this worktree" in said
    assert "--post <file>" in said


@pytest.mark.spec("req-dev-multisession-review-triage-check-9")
def test_a_plugin_pull_request_gets_it_too_with_its_number(repos: dict[str, Path]) -> None:
    url = "https://github.com/example-org/github-core-tap/pull/42\n"
    said = _said(f"{PR_CREATE} --fill", repos["plugin"], repos["project"], {"stdout": url})
    assert "pr-review-triage 42 --watch" in said
    assert "plugin checkout" in said
    assert "BLOCKS" not in said, "a plugin repository has no promote"


@pytest.mark.spec("req-dev-multisession-review-triage-check-9")
def test_the_tool_response_may_be_plain_text(repos: dict[str, Path]) -> None:
    said = _said(PROMOTE, repos["project"], repos["project"], "… https://github.com/example-org/tap/pull/77 …")
    assert "pr-review-triage 77 --watch" in said


@pytest.mark.spec("req-dev-multisession-review-triage-check-10")
@pytest.mark.parametrize("response", ["", {"stdout": "started in background", "stderr": ""}, None, 7])
def test_without_a_pull_request_number_it_says_so_and_still_instructs(repos: dict[str, Path], response: object) -> None:
    said = _said(PROMOTE, repos["project"], repos["project"], response)
    assert "number is not in this call's output" in said
    assert "gh pr list --head session/idea --state open" in said
    assert "scripts/pr-review-triage <pr> --watch" in said and "as a Monitor" in said


@pytest.mark.spec("req-dev-multisession-review-triage-check-10")
def test_without_a_main_checkout_beside_it_the_instruction_still_names_a_trusted_one(tmp_path: Path) -> None:
    alone = _make_repo(tmp_path / "alone", f"https://github.com/{PROJECT_SLUG}.git")
    (alone / ".git" / "HEAD").write_text("ref: refs/heads/session/alone\n", encoding="utf-8")
    said = _said(PROMOTE, alone, alone)
    assert "a trusted checkout of the default branch" in said


@pytest.mark.spec("req-dev-multisession-review-triage-check-11")
@pytest.mark.parametrize(
    "command",
    [
        f"{PROMOTE} --dry-run",
        f"{PROMOTE} --help",
        "grep -n promote-to-main.sh AGENTS.md",
        f'echo "{PROMOTE}"',
        f"# {PROMOTE}",
        f"cat <<'EOF'\n{PROMOTE}\nEOF",
        f"cat {PROMOTE}",
        "scripts/promote-all-sessions.sh",
        "gh pr view 12",
        "ls",
    ],
)
def test_a_command_that_opens_no_pull_request_gets_nothing(repos: dict[str, Path], command: str) -> None:
    assert _said(command, repos["project"], repos["project"], "PR #12") == ""


@pytest.mark.spec("req-dev-multisession-review-triage-check-11")
def test_a_refused_pr_create_in_this_repository_gets_nothing(repos: dict[str, Path]) -> None:
    assert _said(f"{PR_CREATE} --fill", repos["project"], repos["project"]) == ""


@pytest.mark.spec("req-dev-multisession-review-triage-check-11")
def test_outside_a_spawned_session_it_says_nothing(tmp_path: Path) -> None:
    clone = _make_repo(tmp_path / "clone", f"https://github.com/{PROJECT_SLUG}.git")
    (clone / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert _said(PROMOTE, clone, clone, "PR #5") == ""
    (clone / ".env.local").write_text("COMPOSE_PROJECT_NAME=tap_idea\n", encoding="utf-8")
    assert "pr-review-triage 5 --watch" in _said(PROMOTE, clone, clone, "PR #5")


@pytest.mark.spec("req-dev-multisession-review-triage-check-11")
@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        {"tool_name": "Read", "tool_input": {"file_path": "x"}},
        {"tool_name": "Bash", "tool_input": {"command": 7}},
        {"tool_name": "Bash", "tool_input": "x"},
        {"tool_name": "Bash", "tool_input": {"command": PROMOTE + " 'unbalanced"}},
    ],
)
def test_anything_it_cannot_read_is_silence_and_exit_zero(repos: dict[str, Path], payload: object) -> None:
    result = _run(payload, repos["project"])
    assert (result.returncode, result.stdout, result.stderr) == (0, "", "")


@pytest.mark.spec("req-dev-multisession-review-triage-check-11")
def test_without_a_project_directory_it_says_nothing(repos: dict[str, Path]) -> None:
    payload = {"tool_name": "Bash", "cwd": str(repos["project"]), "tool_input": {"command": PROMOTE}}
    result = _run(payload, None)
    assert (result.returncode, result.stdout) == (0, "")


@pytest.mark.spec("req-dev-localexec-config-not-logic-1")
def test_settings_hold_only_a_pointer_to_this_hook() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    (group,) = settings["hooks"]["PostToolUse"]
    assert set(group) == {"matcher", "hooks"}
    assert group["matcher"] == "Bash"
    (handler,) = group["hooks"]
    assert set(handler) == {"type", "command", "timeout"}
    assert handler["type"] == "command"
    assert handler["command"] == '"$CLAUDE_PROJECT_DIR/scripts/hooks/pr-watch-prompt"'


@pytest.mark.spec("req-dev-localexec-config-not-logic-2")
def test_the_hook_states_its_limits_and_is_executable() -> None:
    assert os.access(HOOK, os.X_OK)
    header = HOOK.read_text(encoding="utf-8").split('"""')[1]
    for claim in (
        "It reads its stdin payload",
        "never runs a command, writes a file, opens a socket",
        "It makes no permission decision",
        "still delivers the instruction",
        "outputs nothing",
        "only inside a spawned TAP session",
    ):
        assert claim in header, claim


@pytest.mark.spec("req-dev-localexec-owned-1")
def test_the_hook_and_the_check_are_code_owned() -> None:
    rules = [line.split()[0] for line in CODEOWNERS.read_text(encoding="utf-8").splitlines() if line.startswith("/")]
    assert "/scripts/hooks/" in rules, "the directory rule covers the new hook"
    assert "/.claude/" in rules
    assert "/scripts/check-ai-review-triage" in rules
    assert "/.github/workflows/" in rules or "/.github/" in rules
