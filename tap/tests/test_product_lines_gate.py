"""The `gate` aggregator really aggregates (req-cicd-dco-signoff-3, req-cicd-branch-protection).

`gate` is the ONE GitHub Actions context the `main-required-checks` ruleset requires, so a job
that is not folded into it is advisory no matter how red it goes. That is not a hypothetical:
from 2026-08-12 to 2026-09-18 the `dco` job — DCO sign-off plus issue-link trailers — ran on
every PR, could go red, and blocked nothing, while CONTRIBUTING.md, CLAUDE.md and two specs all
said the checks were enforcing (tap#353). A declaration that exists but is false passes any check
that only tests presence.

The assertion is therefore DERIVED, not a hand-kept list of lane names: every job the workflow
defines must be in `gate.needs` and its result must reach gate's verdict step. A new lane added
outside the aggregator fails here on the PR that adds it, which is the only moment anyone is
looking.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "product-lines.yml"


@pytest.fixture(name="workflow")
def _workflow() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return data


def _gate(workflow: dict[str, Any]) -> dict[str, Any]:
    gate: dict[str, Any] = workflow["jobs"]["gate"]
    return gate


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_the_dco_job_is_required_through_the_gate(workflow: dict[str, Any]) -> None:
    """The named defect (tap#353): `dco` outside `gate.needs` is a check that changes nothing."""
    assert "dco" in _gate(workflow)["needs"]


# Jobs that run AFTER gate and so cannot be among its inputs. The set is exact, not a pattern: a
# second entry is a deliberate edit here, and `test_the_owner_issue_job_is_report_only` pins the
# one member to a shape that cannot weaken the verdict (schedule-only, needs gate, issues: write,
# no checkout).
DOWNSTREAM_OF_GATE = frozenset({"owner-issue"})


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_every_job_is_folded_into_the_gate(workflow: dict[str, Any]) -> None:
    """Derived, so the next lane cannot be added outside the one required context unnoticed."""
    jobs = set(workflow["jobs"]) - {"gate"} - DOWNSTREAM_OF_GATE
    missing = sorted(jobs - set(_gate(workflow)["needs"]))
    assert not missing, (
        f"{missing} run in product-lines.yml but are not in `gate`'s needs — `gate` is the only "
        "context the main-required-checks ruleset requires, so a red in those jobs blocks nothing."
    )


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_every_needed_jobs_result_reaches_the_verdict(workflow: dict[str, Any]) -> None:
    """Being in `needs` only makes a job RUN first; gate must also read its result.

    `if: always()` means gate executes even when a lane fails, so an unread result is a silent
    pass — the same presence-not-correctness shape one level down.
    """
    gate = _gate(workflow)
    assert gate.get("if") == "always()", "gate must not be skippable into a false green"
    rendered = yaml.safe_dump(gate["steps"])
    unread = sorted(job for job in gate["needs"] if f"needs.{job}.result" not in rendered)
    assert not unread, f"gate needs {unread} but never reads their result — a failure there is invisible"


def _setup_matrix_entry(workflow: dict[str, Any], line: str) -> dict[str, Any]:
    """The matrix row `setup` emits for ``line``, parsed from the JSON literal in its script."""
    import json
    import re

    script = "\n".join(step.get("run", "") for step in workflow["jobs"]["setup"]["steps"])
    match = re.search(rf"^\s*{line}='(\{{.*\}})'\s*$", script, re.MULTILINE)
    assert match, f"setup defines no {line} matrix row"
    entry: dict[str, Any] = json.loads(match.group(1))
    return entry


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_the_core_ci_line_requires_the_gryphon_corpus_to_execute(workflow: dict[str, Any]) -> None:
    """The corpus runs on every PR: the core_ci row names it, and the lane passes it to --require."""
    assert _setup_matrix_entry(workflow, "core_ci")["require"] == "gryphon_playground"
    lane = next(s for s in workflow["jobs"]["line"]["steps"] if str(s.get("name", "")).startswith("Test lane"))
    assert "matrix.require" in lane["run"] and "--require" in lane["run"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_cold_boot_boots_core_ci_on_the_full_and_boot_tiers(workflow: dict[str, Any]) -> None:
    """cold-boot proves core's own set, on every tier that can move boot — never the union."""
    job = workflow["jobs"]["cold-boot"]
    assert job["env"]["TAP_BOOT_PROFILE"] == "core_ci"
    assert "tier == 'full'" in job["if"] and "tier == 'boot'" in job["if"]
    cache = next(s for s in job["steps"] if "actions/cache" in str(s.get("uses", "")))
    assert cache["with"]["key"].startswith("uv-ci-core_ci-")


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_gate_accepts_a_cold_boot_skip_only_on_the_tier(workflow: dict[str, Any]) -> None:
    """No other job's result can buy cold-boot's skip: the verdict's cold-boot arm never reads bom-boot."""
    rendered = "\n".join(step.get("run", "") for step in _gate(workflow)["steps"])
    arm = rendered[rendered.index('case "$R_COLD" in') :]
    arm = arm[: arm.index("esac")]
    assert "R_BOM" not in arm, "cold-boot's skip must be justified by the tier alone"


@pytest.mark.spec("req-dev-validation-product-line-lanes-1")
def test_core_ci_is_the_only_line_in_tap_checks(workflow: dict[str, Any]) -> None:
    """Product lines are proven in their own repos (tap#638): no product profile rides tap's PR checks.

    The `samsite` line staged its record through the bootstrap pointer at a rev read from the
    union's pin — core CI depending on a product's release. Removing it must remove every step
    only it used, or a stale `if: matrix.line == ...` step is dead code that reads as coverage.
    """
    script = "\n".join(step.get("run", "") for step in workflow["jobs"]["setup"]["steps"])
    rows = re.findall(r"""^\s*(\w+)='\{"line":""", script, re.MULTILINE)
    assert rows == ["core_ci"], f"setup defines matrix rows {rows}; tap's checks run the core_ci line only"
    raw: Any = workflow  # PyYAML reads the bare `on:` key as the boolean True, not "on"
    triggers = raw.get("on", raw.get(True))
    dispatch = triggers["workflow_dispatch"]["inputs"]["line"]["options"]
    assert dispatch == ["core_ci", "all"]
    conditional = [
        step.get("name") for step in workflow["jobs"]["line"]["steps"] if "matrix.line" in str(step.get("if", ""))
    ]
    assert not conditional, f"steps gated on a line that no longer exists: {conditional}"


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    raw: Any = workflow  # PyYAML reads the bare `on:` key as the boolean True, not "on"
    triggers: dict[str, Any] = raw.get("on", raw.get(True))
    return triggers


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_the_battery_runs_nightly_against_main(workflow: dict[str, Any]) -> None:
    """tap#791: a `schedule`, so main's own content is tested — and no `push` trigger (maintainer's call)."""
    triggers = _triggers(workflow)
    assert triggers["schedule"] == [{"cron": "23 8 * * *"}]
    assert "push" not in triggers
    # The nightly must not be able to name a narrower lane: setup's dispatch-only branch is keyed
    # on the event, so a schedule falls through to the full matrix.
    pick = next(s for s in workflow["jobs"]["setup"]["steps"] if s.get("id") == "pick")
    assert '[ "$EVENT" = "workflow_dispatch" ]' in pick["run"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_the_nightly_cron_is_clear_of_every_other_cron() -> None:
    """Derived from the workflow directory, so a later cron cannot land on the same minute unnoticed."""
    ours = "23 8 * * *"
    others: list[str] = []
    for path in sorted(WORKFLOW.parent.glob("*.yml")):
        if path == WORKFLOW:
            continue
        others += re.findall(r"""^\s*-\s*cron:\s*["']([^"']+)["']""", path.read_text(encoding="utf-8"), re.MULTILINE)
    assert others, "found no other cron at all — the scan is not reading the workflows"
    assert ours not in others


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_an_empty_diff_does_not_require_the_bom_lane() -> None:
    """On `schedule` HEAD is main, so gate's BOM step pipes an empty list — it must answer `no-boot`.

    An unanswered verdict would require bom-boot, which only the `boot` tier runs: every nightly
    would go red on a lane it never scheduled. Pairs with `test_empty_diff_is_full`
    (test_change_tier.py), which proves the same empty diff runs the whole battery.
    """
    repo_root = WORKFLOW.parents[2]
    # nosemgrep — a literal interpreter plus the repo's own module path; no input reaches argv.
    out = subprocess.run(  # nosemgrep
        ["python3", str(repo_root / "tap" / "bom_inputs.py"), "--classify", "--root", str(repo_root)],
        input="\n",  # gate runs `printf '%s\n' "$files"`, so an empty diff is one empty line
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "no-boot"


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_the_owner_issue_job_is_report_only(workflow: dict[str, Any]) -> None:
    """The one job outside gate: after it, schedule-only, `issues: write` only, and no repo code checked out."""
    assert DOWNSTREAM_OF_GATE <= set(workflow["jobs"])
    job = workflow["jobs"]["owner-issue"]
    assert job["needs"] == ["gate"]
    assert job["if"] == "always() && github.event_name == 'schedule'"
    assert job["permissions"] == {"issues": "write"}
    assert not [s for s in job["steps"] if "uses" in s], "the owner-issue job must not check out or run actions"
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "owner-issue" not in _gate(workflow)["needs"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_the_owner_issue_is_found_by_author_and_marker_not_title(workflow: dict[str, Any]) -> None:
    """Anyone can open an issue titled "Nightly red: tap main"; only the Actions bot's, carrying the marker, is ours."""
    job = workflow["jobs"]["owner-issue"]
    script = job["steps"][0]["run"]
    marker = job["env"]["MARKER"]
    assert marker.startswith("<!--") and marker.endswith("-->")
    listing = script[script.index("gh issue list") : script.index("existing=")]
    assert '--limit "$LIMIT"' in listing
    assert '"$count" -ge "$LIMIT"' in script, "a listing that hit --limit must fail, not read as 'no issue'"
    selector = script[script.index("existing=") : script.index("case ")]
    assert 'author.login == "app/github-actions"' in selector and "is_bot == true" in selector
    assert "contains($m)" in selector and '--arg m "$MARKER"' in selector
    assert "title" not in selector.lower(), "the existing issue must never be matched by title"
    create = script[script.index("gh issue create") - 600 : script.index("gh issue create")]
    assert '"$MARKER"' in create, "a filed issue must carry the marker, or the next night cannot find it"


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_the_owner_issue_opens_only_on_failure_and_closes_only_on_success(workflow: dict[str, Any]) -> None:
    """A cancelled or skipped gate proved nothing, so it neither files nor closes."""
    script = workflow["jobs"]["owner-issue"]["steps"][0]["run"]
    arms = script[script.index('case "$GATE_RESULT" in') :]
    success = arms[arms.index("success)") : arms.index("failure)")]
    failure = arms[arms.index("failure)") : arms.index("*)")]
    other = arms[arms.index("*)") : arms.index("esac")]
    assert "gh issue close" in success and "gh issue create" not in success
    assert "gh issue create" in failure and "gh issue close" not in failure
    assert "gh issue" not in other
