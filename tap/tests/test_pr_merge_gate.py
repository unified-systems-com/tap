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

These tests hit `tap.pr_review_verdict` directly and therefore run everywhere,
including the container the lanes boot (which has no `jq`). The HOOK that consumes
this verdict is authored in `unified-systems-com/tap-dev-hooks` under `payload/` —
locally-executing code is reviewed in its own repository by someone other than its
author — and is tested there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tap.pr_review_verdict import EXIT_OK, EXIT_UNANSWERED, FINDING_RE, _load, findings, verdict

REPO_ROOT = Path(__file__).resolve().parents[2]

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


@pytest.mark.spec("req-dev-localexec-merge-gate-2")
def test_the_json_read_is_validated_at_the_sink(tmp_path: Path) -> None:
    """The one place a caller-supplied string becomes a file read refuses by name."""
    good = tmp_path / "reviews.json"
    good.write_text("[]")
    assert _load(str(good)) == []

    wrong_suffix = tmp_path / "reviews.txt"
    wrong_suffix.write_text("[]")
    with pytest.raises(ValueError, match="non-JSON path"):
        _load(str(wrong_suffix))

    with pytest.raises(ValueError, match="not a readable file"):
        _load(str(tmp_path / "missing.json"))


@pytest.mark.spec("req-dev-localexec-merge-gate-2")
def test_a_timeout_and_a_clean_review_are_different_states() -> None:
    """The measured cause of the original miss, pinned as a contract.

    `--wait` used to default to 180s while the review arrived at 4m39s-9m59s on five
    PRs of the tap#363 epic — 5 of 5 past the ceiling. An expired poll printed an
    empty section that read exactly like a clean review. So two things must hold and
    are asserted here against the script's operator-visible text: the default ceiling
    is 600s, and a timeout says in words that it does NOT mean clean.
    """
    script = (REPO_ROOT / "scripts" / "pr-review-triage").read_text()
    assert 'WAIT="${2:-600}"' in script, "the --wait ceiling must be 600s, not the 180s that caused the miss"
    # And it polls with a backoff rather than one long sleep, so it returns as soon as
    # the review exists instead of always paying the ceiling.
    assert "interval=15" in script and "interval * 2" in script, "--wait must poll with a backoff"
    assert "does NOT mean clean" in script, "a timeout must say it is not a clean verdict"
    assert "--assert-answered" in script, "the timeout message must point at the thing that settles it"

    # And the verdict itself keeps them distinct: nothing posted is UNKNOWN, not answered.
    code, _found, msg = verdict([], [])
    assert code == EXIT_UNANSWERED
    assert "UNKNOWN" in msg


@pytest.mark.spec("req-dev-localexec-merge-gate-1")
@pytest.mark.parametrize(
    ("text", "matches"),
    [
        ("## high — something", True),  # a severity heading at line start
        ("## medium — something", True),
        ("intro\n## high — something", True),  # ... on any line, not just the first
        ("xx## high — something", False),  # NOT a heading: the anchor must bind here
        ("  ## high — indented", False),
        ("Verdict: merge-blocker until settled", True),  # mid-line, deliberately unanchored
        ("> **SEAT ABSENT** — no verdict", True),
        ("nothing to see here", False),
        ("## low — cosmetic", False),  # low is not a finding this gate blocks on
    ],
)
def test_the_finding_pattern_binds_its_anchor_where_it_means_to(text: str, matches: bool) -> None:
    """`^` binds to its own alternative, not the whole pattern — so say which.

    Unparenthesised, `^## (high|medium)|merge-blocker|SEAT ABSENT` happens to mean what
    is intended, but only by precedence, and the next alternative added inherits the
    trap — in the one expression that decides whether a merge is blocked (SonarCloud
    S5850). These cases pin the semantics rather than the spelling.
    """
    assert bool(FINDING_RE.search(text)) is matches
