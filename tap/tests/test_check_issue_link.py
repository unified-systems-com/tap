"""Behavioral tests for `scripts/check-issue-link` (req-cicd-issue-link).

The issue-link check gates every road to `main` beside the DCO check, so its verdicts are
load-bearing: a false GREEN lands work whose issue stays open, a false RED blocks a promote.
Each test builds a THROWAWAY git repository and runs the real script against it — never the
session repo — so the assertions exercise the shipped artifact end to end, exit code included.

Covers: a qualified `Closes:` passes and is emitted in GitHub's form; `Part-of:` and `No-issue:`
pass; a range with no trailer fails; a bare `#n` fails with the qualified-form hint; an approved bot
IDENTITY (numeric id + type Bot from the authenticated event, tap#342) is exempt while a spoofed
author string, a matching login with the wrong id, a matching id with the wrong type, and the stock
`renovate[bot]` are not; the verdict is per range (one trailer covers fix-up commits); `--emit`
prints closes first and deduplicates.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tap.jsonfiles import load_json_file

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check-issue-link"
APPROVED = REPO_ROOT / "tap" / "tap.pr-bots.json"
APPROVED_SCHEMA = REPO_ROOT / "tap" / "schemas" / "pr-bots.schema.json"

# Verified against GitHub's /users/<login> on 2026-09-08 (tap#342); the allowlist file is the record.
TAP_RENOVATE = ("tap-renovate[bot]", "315114127")
STOCK_RENOVATE = ("renovate[bot]", "29139614")

# The throwaway-repo fixture is shared with test_check_dco.py (one copy, so the suites cannot drift).
from tap.tests.throwaway_repo import commit as _commit  # noqa: E402
from tap.tests.throwaway_repo import run_script  # noqa: E402


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
def test_a_spoofed_bot_author_string_is_not_an_exemption(repo: Path) -> None:
    """Codex/Grok on PR #328: git author metadata is contributor-controlled. A range whose
    commits claim to be renovate's still needs a trailer unless GitHub says the PR is renovate's."""
    _commit(repo, "chore(deps): bump x", author="renovate[bot] <renovate@example.com>")
    _commit(repo, "chore(deps): bump y", author="dependabot-helper <me@example.com>")
    result = _run(repo)
    assert result.returncode == 1 and "names its issue" in result.stdout


def _as(repo: Path, login: str, ident: str, kind: str = "Bot") -> subprocess.CompletedProcess[str]:
    return _run(repo, "--pr-author-id", ident, "--pr-author-type", kind, "--pr-author", login)


@pytest.mark.spec("req-cicd-issue-link-6")
def test_the_approved_bot_identity_exempts_the_range(repo: Path) -> None:
    """tap#342: PR# 339's real author is tap-renovate[bot]; the exemption is its id + Bot type."""
    _commit(repo, "chore(deps): bump x")
    result = _as(repo, *TAP_RENOVATE)
    assert result.returncode == 0 and "approved bot tap-renovate[bot] (id 315114127)" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-6")
@pytest.mark.parametrize(
    ("login", "ident", "kind", "why"),
    [
        (TAP_RENOVATE[0], "424242", "Bot", "matching login, wrong id"),
        (TAP_RENOVATE[0], TAP_RENOVATE[1], "User", "matching id, wrong type"),
        (STOCK_RENOVATE[0], STOCK_RENOVATE[1], "Bot", "stock renovate[bot] is not ours"),
        ("github-actions[bot]", "41898282", "Bot", "never authored a PR here; removed from the list"),
        ("octocat", "583231", "User", "a human"),
        ("tap-renovate[bot]", "", "Bot", "no id at all"),
        ("tap-renovate[bot]", "not-a-number", "Bot", "malformed id"),
    ],
)
def test_anything_but_an_approved_id_and_bot_type_needs_a_trailer(
    repo: Path, login: str, ident: str, kind: str, why: str
) -> None:
    _commit(repo, "chore(deps): bump x")
    result = _as(repo, login, ident, kind)
    assert result.returncode == 1, why
    assert "names its issue" in result.stdout and login in result.stdout, why
    # A trailer still passes for the same identity: the identity only decides the exemption.
    _commit(repo, "chore(deps): bump y\n\nNo-issue: dependency bump carried by a human review")
    assert _as(repo, login, ident, kind).returncode == 0


@pytest.mark.spec("req-cicd-issue-link-6")
def test_a_human_pr_carrying_bot_authored_commits_still_needs_a_trailer(repo: Path) -> None:
    _commit(
        repo, "chore(deps): bump x", author="tap-renovate[bot] <315114127+tap-renovate[bot]@users.noreply.github.com>"
    )
    result = _as(repo, "octocat", "583231", "User")
    assert result.returncode == 1 and "octocat" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-6")
def test_legacy_login_only_invocation_is_not_an_exemption(repo: Path) -> None:
    """The old `--pr-author <login>` shape alone authorizes nothing — login is diagnostics."""
    _commit(repo, "chore(deps): bump x")
    result = _run(repo, "--pr-author", TAP_RENOVATE[0])
    assert result.returncode == 1 and "no authenticated author id" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-6")
def test_allowlist_validates_against_its_schema_and_the_stdlib_reader_agrees() -> None:
    data = load_json_file(APPROVED, schema=APPROVED_SCHEMA)  # jsonschema — the full contract
    ids = {e["id"] for e in data["approved"]}
    assert 315114127 in ids and 29139614 not in ids and 41898282 not in ids
    # The script's stdlib reader (what CI actually runs) sees the same identities.
    out = subprocess.run(
        [
            "python3",
            "-c",
            "import runpy,sys,json; m=runpy.run_path(sys.argv[1], run_name='lib'); "
            "print(json.dumps(sorted(m['load_approved_bots']())))",
            str(CHECK),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(json.loads(out.stdout)) == ids


@pytest.mark.spec("req-cicd-issue-link-6")
def test_a_malformed_allowlist_fails_closed(repo: Path, tmp_path: Path) -> None:
    """A broken allowlist is a configuration error (exit 2), never a wider exemption."""
    _commit(repo, "chore(deps): bump x")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"approved": [{"login": "x[bot]", "id": "315114127", "type": "Bot"}]}))
    out = subprocess.run(
        [
            "python3",
            "-c",
            f"import runpy,sys; m=runpy.run_path(sys.argv[1], run_name='lib'); m['load_approved_bots'](__import__('pathlib').Path({str(bad)!r}))",
            str(CHECK),
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode != 0 and "must be a positive integer" in out.stderr


@pytest.mark.spec("req-cicd-issue-link-3")
def test_issue_number_zero_is_not_a_reference(repo: Path) -> None:
    _commit(repo, "fix: z\n\nCloses: o/r#0")
    result = _run(repo)
    assert result.returncode == 1 and "names no issue reference" in result.stdout


@pytest.mark.spec("req-cicd-issue-link-4")
def test_emit_fails_on_a_malformed_trailer_rather_than_printing_half(repo: Path) -> None:
    _commit(repo, "a\n\nCloses: o/r#5\nPart-of: #7")
    result = _run(repo, "--emit")
    assert result.returncode == 1 and "bare #7" in result.stderr


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
