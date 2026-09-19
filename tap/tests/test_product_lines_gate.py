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
