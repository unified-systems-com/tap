"""The PreToolUse hook that refuses a hand-run `gh pr create` (req-dev-multisession-pr-open-redirect).

The hook is a local-execution surface (specs/spec-dev-local-execution.md), so it is tested the
way its header promises it behaves: it refuses exactly the invocation it names, aimed at this
repository; it allows everything else, including every input it cannot resolve; and it is
wired by a settings file that holds only a pointer.

Each case runs the real script in a subprocess against a throwaway repository, the same way
Claude Code runs it: the PreToolUse payload on stdin, CLAUDE_PROJECT_DIR in the environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pr-open-redirect"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"

PROJECT_SLUG = "example-org/tap"


def _make_repo(path: Path, origin: str) -> Path:
    (path / ".git").mkdir(parents=True)
    (path / ".git" / "config").write_text(
        f'[core]\n\tbare = false\n[remote "origin"]\n\turl = {origin}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n',
        encoding="utf-8",
    )
    return path


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, Path]:
    """A project repository with a plugin checkout nested inside it, as `_dev-plugins/` is."""
    project = _make_repo(tmp_path / "project", f"https://github.com/{PROJECT_SLUG}.git")
    plugin = _make_repo(project / "_dev-plugins" / "github_core", "git@github.com:example-org/github-core-tap.git")
    (project / "tap").mkdir()
    return {"project": project, "plugin": plugin, "subdir": project / "tap"}


def _run(payload: object, project_dir: Path | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project_dir is not None:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed hook under the test's own interpreter IS the test; argv list, no shell  # nosec B603  # noqa: S603
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, env=env, timeout=30
    )


def _decision(command: str, cwd: Path, project: Path) -> str:
    result = _run({"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}, project)
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return "allow"
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    if "permissionDecision" in out:
        assert "open-a-pr" in out["permissionDecisionReason"]
        return str(out["permissionDecision"])
    assert "pr-review-triage" in out["additionalContext"], out
    return "remind"


# The verb under test is assembled at runtime so that this file never contains the literal
# invocation at a line start — a reader's grep, and the hook itself, should find only data here.
VERB = " ".join(["gh", "pr", "create"])

DENIED = [
    f"{VERB} --title x --body y",
    f"{VERB} -f",
    f"git push -u origin HEAD && {VERB} -f",
    f"git status; {VERB} --fill",
    f"FOO=1 BAR=2 {VERB} -f",
    f"echo $({VERB} -f)",
    f"/opt/homebrew/bin/{VERB} -f",
    f"cd tap\n{VERB} -f",
]

ALLOWED = [
    f'rg -n "x|{VERB}" specs/',
    f"echo '{VERB}'",
    f"# {VERB}",
    f'bash -c "{VERB} -f"',
    "gh pr view 1004",
    "gh pr list --state open",
    "scripts/promote-to-main.sh",
    "gh api repos/example-org/tap/pulls -X POST",
    f"cat <<'EOF'\n{VERB} --title from-a-heredoc\nEOF",
    f"cat <<EOF > notes.md\nline\n{VERB} -f\nEOF\nls",
    'echo "unbalanced',
]


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-1")
@pytest.mark.parametrize("command", DENIED)
def test_a_hand_run_pr_create_in_this_repo_is_denied(repos: dict[str, Path], command: str) -> None:
    assert _decision(command, repos["project"], repos["project"]) == "deny"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-2")
@pytest.mark.parametrize("command", ALLOWED)
def test_mentions_and_other_commands_are_allowed(repos: dict[str, Path], command: str) -> None:
    assert _decision(command, repos["project"], repos["project"]) == "allow"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-1")
def test_a_subdirectory_of_this_repo_is_still_this_repo(repos: dict[str, Path]) -> None:
    assert _decision(f"{VERB} -f", repos["subdir"], repos["project"]) == "deny"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-3")
def test_a_plugin_checkout_inside_the_worktree_is_not_refused(repos: dict[str, Path]) -> None:
    """Plugin repositories have no promote; their PRs still open by hand (open-a-pr step 5)."""
    assert _decision(f"{VERB} -f", repos["plugin"], repos["project"]) == "remind"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-3")
def test_cd_moves_the_target(repos: dict[str, Path]) -> None:
    into_plugin = f"cd {repos['plugin']} && {VERB} -f"
    into_project = f"cd {repos['subdir']} && {VERB} -f"
    assert _decision(into_plugin, repos["project"], repos["project"]) == "remind"
    assert _decision(into_project, repos["plugin"], repos["project"]) == "deny"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-3")
def test_an_explicit_repo_flag_decides_the_target(repos: dict[str, Path]) -> None:
    assert _decision(f"{VERB} -R {PROJECT_SLUG} -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision(f"{VERB} --repo=Example-Org/TAP -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision(f"{VERB} -R example-org/github-core-tap -f", repos["project"], repos["project"]) == "remind"
    # gh also takes the flag before the subcommand, between its words, and attached;
    # each form was confirmed against the installed gh with `--help`.
    assert _decision(f"gh -R {PROJECT_SLUG} pr create -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision(f"gh pr -R {PROJECT_SLUG} create -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision(f"{VERB} -R{PROJECT_SLUG} -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision("gh -R example-org/github-core-tap pr create -f", repos["project"], repos["project"]) == "remind"
    # A flag value that happens to read "create" is not the subcommand.
    assert _decision("gh pr view --title create", repos["project"], repos["project"]) == "allow"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-3")
def test_a_repo_flag_host_must_match_origin_when_given(repos: dict[str, Path]) -> None:
    # origin is https://github.com/example-org/tap.git: a host-qualified -R must name that host.
    assert _decision(f"{VERB} -R github.com/{PROJECT_SLUG} -f", repos["plugin"], repos["project"]) == "deny"
    assert _decision(f"{VERB} -R ghe.example.com/{PROJECT_SLUG} -f", repos["project"], repos["project"]) == "remind"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-5")
def test_other_repositories_get_the_triage_reminder_and_no_decision(repos: dict[str, Path]) -> None:
    result = _run({"tool_name": "Bash", "cwd": str(repos["plugin"]), "tool_input": {"command": f"{VERB} -f"}}, repos["project"])
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert "permissionDecision" not in out, "a plugin PR must never be refused or auto-approved"
    assert "scripts/pr-review-triage" in out["additionalContext"]
    # A command that opens no PR gets nothing at all, reminder included.
    assert _decision("gh pr list", repos["plugin"], repos["project"]) == "allow"


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-4")
@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "",
        {"tool_name": "Read", "tool_input": {"file_path": "x"}},
        {"tool_name": "Bash", "tool_input": {}},
        {"tool_name": "Bash", "tool_input": {"command": 42}},
    ],
)
def test_anything_it_cannot_read_is_allowed(repos: dict[str, Path], payload: object) -> None:
    result = _run(payload, repos["project"])
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.spec("req-dev-multisession-pr-open-redirect-4")
def test_unresolvable_targets_are_allowed(repos: dict[str, Path]) -> None:
    assert _decision(f'cd "$SOMEWHERE" && {VERB} -f', repos["project"], repos["project"]) == "allow"
    no_project = _run({"tool_name": "Bash", "cwd": str(repos["project"]), "tool_input": {"command": f"{VERB} -f"}}, None)
    assert no_project.returncode == 0 and no_project.stdout.strip() == ""


@pytest.mark.spec("req-dev-localexec-config-not-logic-1")
def test_settings_hold_only_a_pointer_to_the_hook() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    assert set(settings) == {"hooks"}
    assert set(settings["hooks"]) == {"PreToolUse"}, "the PostToolUse triage nudge is retired"
    (group,) = settings["hooks"]["PreToolUse"]
    assert group["matcher"] == "Bash"
    (handler,) = group["hooks"]
    assert handler["type"] == "command"
    assert handler["command"] == '"$CLAUDE_PROJECT_DIR/scripts/hooks/pr-open-redirect"'


@pytest.mark.spec("req-dev-localexec-config-not-logic-2")
def test_the_hook_states_its_limits_and_is_executable() -> None:
    assert os.access(HOOK, os.X_OK)
    header = HOOK.read_text(encoding="utf-8").split('"""')[1]
    for claim in ("It reads its stdin payload", "fails open", "only refuses PRs against this repository"):
        assert claim in header, claim
