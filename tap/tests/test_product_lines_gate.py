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
