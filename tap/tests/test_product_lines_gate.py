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


@pytest.mark.spec("req-cicd-dco-signoff-3")
def test_every_job_is_folded_into_the_gate(workflow: dict[str, Any]) -> None:
    """Derived, so the next lane cannot be added outside the one required context unnoticed."""
    jobs = set(workflow["jobs"]) - {"gate"}
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


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((WORKFLOW.parent / name).read_text(encoding="utf-8"))
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    raw: Any = workflow  # PyYAML reads the bare `on:` key as the boolean True, not "on"
    triggers: dict[str, Any] = raw.get("on", raw.get(True)) or {}
    return triggers


def _core_ci_calls(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every job in ``workflow`` that calls core-ci.yml, by job id."""
    return {
        job_id: job for job_id, job in workflow["jobs"].items() if job.get("uses") == "./.github/workflows/core-ci.yml"
    }


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_the_core_ci_line_requires_the_gryphon_corpus_to_execute() -> None:
    """The corpus runs on every PR: the core_ci line passes it to --require, by name."""
    job = _load("core-ci.yml")["jobs"]["line"]
    lane = next(s for s in job["steps"] if str(s.get("name", "")).startswith("Test lane"))
    assert 'require="gryphon_playground"' in lane["run"] and "--require" in lane["run"]
    assert "--record boot/core_ci.boot.json" in lane["run"]


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_cold_boot_boots_core_ci_on_the_full_and_boot_tiers(workflow: dict[str, Any]) -> None:
    """cold-boot proves core's own set, on every tier that can move boot — never the union."""
    caller = workflow["jobs"]["cold-boot"]
    assert "tier == 'full'" in caller["if"] and "tier == 'boot'" in caller["if"]
    assert caller["with"]["lane"] == "cold-boot"
    job = _load("core-ci.yml")["jobs"]["cold-boot"]
    assert job["env"]["TAP_BOOT_PROFILE"] == "core_ci"
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

    The `line` job is a call to core-ci.yml, not a matrix: there is no row a product line
    could be added back into without it showing up here.
    """
    calls = _core_ci_calls(workflow)
    assert {job_id: job["with"]["lane"] for job_id, job in calls.items()} == {"line": "line", "cold-boot": "cold-boot"}
    assert "strategy" not in workflow["jobs"]["line"]
    assert "matrix" not in workflow["jobs"]["setup"].get("outputs", {})
    assert not (_triggers(workflow)["workflow_dispatch"] or {}).get("inputs"), "one line: nothing to choose"


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_core_ci_is_defined_once_and_fails_closed_on_an_unknown_lane() -> None:
    """One definition, selected per call — and a call whose every job skipped must not read green."""
    core = _load("core-ci.yml")
    assert set(_triggers(core)) == {"workflow_call"}
    jobs = core["jobs"]
    assert jobs["line"]["if"] == "inputs.lane == 'line'"
    assert jobs["cold-boot"]["if"] == "inputs.lane == 'cold-boot'"
    check = jobs["lane-check"]
    assert check["if"] == "inputs.lane != 'line' && inputs.lane != 'cold-boot'"
    assert "exit 1" in "\n".join(step.get("run", "") for step in check["steps"])
    for job_id in ("line", "cold-boot"):
        checkout = jobs[job_id]["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert (
            checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"
        ), f"{job_id} must validate the ref it is given"
    # No copy of the job bodies survives in the PR workflow: nothing there runs them itself.
    runs = [
        str(step.get("run", ""))
        for job in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"].values()
        for step in job.get("steps") or []
    ]
    assert not [r for r in runs if "tap.lane_run" in r or re.search(r"scripts/gate(?!-lean)", r)]


@pytest.mark.spec("req-dev-validation-product-line-lanes-11")
def test_a_release_gates_on_core_ci_not_on_the_union() -> None:
    """publish-release-tags.yml runs both core_ci lanes on the tag's commit, and retag needs them."""
    release = _load("publish-release-tags.yml")
    calls = _core_ci_calls(release)
    assert sorted(job["with"]["lane"] for job in calls.values()) == ["cold-boot", "line"]
    for job in calls.values():
        assert job["with"]["ref"] == "${{ github.ref }}", "the release candidate is the tag's own commit"
        assert job["permissions"] == {"contents": "read"}
    for gated in ("candidate", "retag"):
        needs = release["jobs"][gated]["needs"]
        needs = [needs] if isinstance(needs, str) else needs
        assert set(calls) <= set(needs), f"{gated} does not wait for core_ci: {needs}"
    used = {str(job.get("uses", "")) for job in release["jobs"].values()}
    assert not any("bom-boot" in u for u in used), "a tap release gates on core only, never the test_all union"
