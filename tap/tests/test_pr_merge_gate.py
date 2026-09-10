"""The AI-review merge gate: the verdict rule, and the PreToolUse hook that uses it.

Spec: specs/spec-dev-local-execution.md (req-dev-localexec-merge-gate).

Why these tests exist (tap#390): a subagent reported "no seat findings" for
PR# 384 - tap while the Grok seat had posted three, one of them
`Verdict: merge-blocker`; the summary was relayed as fact and nothing in the
machinery could object. A sweep then found PR# 386 with an unanswered `## high`
and PR# 371 already MERGED with a `SEAT ABSENT` nobody answered. The gate turns
"somebody says they read the review" into an exit code, so what is pinned here is
the rule itself — it blocks an unanswered finding, it clears once an answer exists,
and it fails closed when it cannot tell.

The VERDICT tests hit `tap.pr_review_verdict` directly and therefore run
everywhere, including the container the lanes boot (which has no `jq`). The HOOK
tests exercise the shell wrapper and skip where `jq` is absent — stated here rather
than left to be discovered, since a test that silently skips in the only place it
runs is the failure mode this repo already names.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tap.pr_review_verdict import EXIT_OK, EXIT_UNANSWERED, findings, verdict

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pr-merge-gate"

_UNIFIED_FINDING = (
    "<!-- unified-ai-review -->\n## Unified AI Review (advisory)\n"
    "## high — installed-distribution scan runs in the validator process\n"
    "Verdict: merge-blocker until this is settled.\n"
)
_UNIFIED_ABSENT = (
    "<!-- unified-ai-review -->\n## Unified AI Review (advisory)\n"
    "### Codex seat (OpenAI)\n"
    "> **SEAT ABSENT** — this seat produced no verdict (rate limit, outage, or error).\n"
)
_UNIFIED_CLEAN = (
    "<!-- unified-ai-review -->\n## Unified AI Review (advisory)\n"
    "No security-class findings.\nconsidered and rejected: prompt injection — none present.\n"
)


def _bot(body: str, at: str) -> dict[str, Any]:
    return {"user": {"login": "github-actions[bot]"}, "body": body, "created_at": at, "updated_at": at}


def _human(body: str, at: str) -> dict[str, Any]:
    return {"user": {"login": "notgeorge"}, "body": body, "created_at": at, "updated_at": at}


# --- the verdict rule (runs everywhere) -------------------------------------


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_an_unanswered_finding_blocks() -> None:
    code, found, _msg = verdict([], [_bot(_UNIFIED_FINDING, "2026-09-11T01:00:00Z")])
    assert code == EXIT_UNANSWERED
    assert any("## high" in line for line in found)
    assert any("merge-blocker" in line for line in found)


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_a_later_answer_clears_it() -> None:
    """A written dismissal counts — that is what the triage discipline already asks for."""
    code, _found, _msg = verdict(
        [],
        [
            _bot(_UNIFIED_FINDING, "2026-09-11T01:00:00Z"),
            _human("Triaged: unobservable in the tooling env by design; evidence on the PR.", "2026-09-11T02:00:00Z"),
        ],
    )
    assert code == EXIT_OK


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_an_answer_that_predates_the_review_does_not_count() -> None:
    """The reviewer edits its comment in place; a reply older than the newest edit is stale."""
    code, _found, _msg = verdict(
        [],
        [
            _human("looks good to me", "2026-09-11T00:30:00Z"),
            _bot(_UNIFIED_FINDING, "2026-09-11T01:00:00Z"),
        ],
    )
    assert code == EXIT_UNANSWERED


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_a_clean_bot_comment_after_the_answer_does_not_re_block() -> None:
    """Sonar/Codacy post "gate passed" long after a review; that must not un-answer a finding.

    Observed on PR# 392 itself: the reply was posted, a clean scanner comment landed
    after it, and measuring against the newest artefact of ANY kind re-blocked the PR.
    A gate that re-blocks for no reason is one people learn to override.
    """
    code, _found, _msg = verdict(
        [],
        [
            _bot(_UNIFIED_FINDING, "2026-09-11T01:00:00Z"),
            _human("Triaged: refuted with the settling evidence, see above.", "2026-09-11T02:00:00Z"),
            _bot("Quality Gate Passed. 0 new issues.", "2026-09-11T03:00:00Z"),
        ],
    )
    assert code == EXIT_OK


@pytest.mark.spec("req-dev-localexec-merge-gate-2")
def test_an_absent_seat_is_not_a_clean_verdict() -> None:
    """A seat that produced no verdict blocks by construction: missing is never clean."""
    code, found, _msg = verdict([], [_bot(_UNIFIED_ABSENT, "2026-09-11T01:00:00Z")])
    assert code == EXIT_UNANSWERED
    assert any("SEAT ABSENT" in line for line in found)


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_a_clean_review_does_not_block() -> None:
    code, found, _msg = verdict([], [_bot(_UNIFIED_CLEAN, "2026-09-11T01:00:00Z")])
    assert code == EXIT_OK
    assert found == []


@pytest.mark.spec("req-dev-localexec-merge-gate-2")
def test_no_review_yet_is_unknown_not_clean() -> None:
    code, _found, msg = verdict([], [])
    assert code == EXIT_UNANSWERED
    assert "UNKNOWN" in msg


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_a_finding_in_a_review_body_counts_too() -> None:
    """Copilot and Codacy post REVIEW objects; findings hide in those bodies as well."""
    code, found, _msg = verdict(
        [
            {
                "user": {"login": "copilot[bot]"},
                "body": "## medium — unchecked input",
                "submitted_at": "2026-09-11T01:00:00Z",
            }
        ],
        [],
    )
    assert code == EXIT_UNANSWERED
    assert found == ["## medium — unchecked input"]


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
def test_findings_are_deduplicated_across_reruns() -> None:
    """The unified comment is edited in place, but a rerun can leave the same line twice."""
    body = _UNIFIED_FINDING
    assert len(findings([], [_bot(body, "2026-09-11T01:00:00Z"), _bot(body, "2026-09-11T03:00:00Z")])) == 2


# --- the hook (shell; needs jq) ----------------------------------------------

_needs_jq = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("bash") is None,
    reason="the hook is a bash script that parses its payload with jq (absent in the app container; present on CI runners)",
)


def _hook(command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"command": command}})
    base = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/tmp"}
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        env={**base, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


def _decision(proc: subprocess.CompletedProcess[str]) -> str:
    if not proc.stdout.strip():
        return "allow"
    return str(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"])


def _reason(proc: subprocess.CompletedProcess[str]) -> str:
    return str(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"])


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-3")
@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        'echo "run gh pr merge 386 later"',  # a mention is not an invocation
        "git commit -m 'gh pr merge'",
    ],
)
def test_the_hook_is_a_no_op_for_everything_that_is_not_a_merge(command: str) -> None:
    proc = _hook(command)
    assert proc.returncode == 0
    assert _decision(proc) == "allow"


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-3")
def test_a_merge_naming_no_pr_is_denied() -> None:
    """`gh pr merge` with the number inferred from the branch cannot be checked, so it is refused."""
    proc = _hook("gh pr merge --merge")
    assert _decision(proc) == "deny"
    assert "names no PR number" in _reason(proc)
    assert "TAP_PR_MERGE_GATE=off" in _reason(proc)


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-2")
def test_the_hook_fails_closed_without_gh() -> None:
    """No `gh` means the verdict cannot be read, and unknown must deny — not allow."""
    proc = _hook("gh pr merge 42 --repo unified-systems-com/tap --merge", env={"PATH": "/usr/bin:/bin"})
    assert _decision(proc) == "deny"
    assert "not on PATH" in _reason(proc)
    assert "UNKNOWN" in _reason(proc)


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-3")
def test_the_override_is_honoured() -> None:
    proc = _hook("gh pr merge 42 --repo unified-systems-com/tap --merge", env={"TAP_PR_MERGE_GATE": "off"})
    assert _decision(proc) == "allow"


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-3")
@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge --merge",
        "/usr/bin/gh pr merge --merge",  # a path-spelled gh is still gh
        "command gh pr merge --merge",
        "env gh pr merge --merge",
    ],
)
def test_the_matcher_covers_the_cheap_spellings(command: str) -> None:
    """A naive matcher is bypassed by a path or a `command` prefix; these are folded in.

    Out of scope and stated in the hook: a raw `curl` to the merge API, or an alias.
    This is a seatbelt against a forgotten review, not a containment boundary.
    """
    assert _decision(_hook(command)) == "deny"


@_needs_jq
@pytest.mark.spec("req-dev-localexec-merge-gate-3")
def test_the_async_merge_endpoint_is_matched_too() -> None:
    """GitHub refuses `gh pr merge` on a stacked PR, so the async endpoint is a merge road too."""
    proc = _hook(
        "gh api -X PUT repos/unified-systems-com/tap/pulls/42/merge-async -f merge_method=merge",
        env={"PATH": "/usr/bin:/bin"},
    )
    assert _decision(proc) == "deny"
