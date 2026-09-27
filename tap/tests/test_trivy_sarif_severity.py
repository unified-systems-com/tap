"""A severity-scoped Trivy step that writes SARIF must say so twice (req-cicd-base-image-lifecycle-2).

The pinned `aquasecurity/trivy-action` (v0.36.0, `ed142fd0`) ignores its `severity` input for
SARIF output. Its `entrypoint.sh` runs, before invoking Trivy::

    if [ "${TRIVY_FORMAT:-}" = "sarif" ]; then
      if [ "${INPUT_LIMIT_SEVERITIES_FOR_SARIF:-false,,}" != "true" ]; then
        echo "Building SARIF report with all severities"
        unset TRIVY_SEVERITY

so `severity: HIGH,CRITICAL` with `format: sarif` scans at EVERY severity, and `exit-code: "1"`
fires on a fixable LOW. The release CVE gate reads that SARIF with `scripts/release_cve_gate.py`,
which counts every result as blocking, so the ruling "block a release on a fixable High/Critical"
silently became "block on anything fixable" (tap#824; run 36062129201 logs the line above).

The check is DERIVED over every workflow rather than pinned to one job, so the next
severity-scoped SARIF step cannot reintroduce it. Report-only scans that set no `severity` are
deliberately untouched: all severities is what the Security tab should show.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
TRIVY_ACTION = "aquasecurity/trivy-action@"


def _trivy_steps() -> list[tuple[str, str, dict[str, Any]]]:
    """Every trivy-action step in every workflow, as (workflow file, job id, step `with:`)."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                if str(step.get("uses", "")).startswith(TRIVY_ACTION):
                    found.append((path.name, job_id, step.get("with") or {}))
    return found


def _severity_scoped_sarif(inputs: dict[str, Any]) -> bool:
    return str(inputs.get("format", "")).lower() == "sarif" and bool(inputs.get("severity"))


def _limits_sarif(inputs: dict[str, Any]) -> bool:
    # The entrypoint compares the literal string "true"; Actions renders a YAML boolean as that too.
    value = inputs.get("limit-severities-for-sarif")
    return value is True or value == "true"


@pytest.mark.spec("req-cicd-base-image-lifecycle-2")
def test_every_severity_scoped_sarif_scan_limits_the_sarif() -> None:
    offenders = sorted(
        f"{name} job {job}"
        for name, job, inputs in _trivy_steps()
        if _severity_scoped_sarif(inputs) and not _limits_sarif(inputs)
    )
    assert not offenders, (
        f'{offenders} set `severity:` with `format: sarif` but not `limit-severities-for-sarif: "true"`'
        " — the pinned trivy-action then scans and exits at EVERY severity, so the severity scope is"
        " decoration and a gate reading that SARIF blocks on a fixable LOW (tap#824)."
    )


@pytest.mark.spec("req-cicd-base-image-lifecycle-2")
def test_the_release_gate_is_one_of_the_steps_checked() -> None:
    """Non-vacuity: the blocking release scan must stay severity-scoped, or the test above says nothing."""
    release = [
        inputs
        for name, job, inputs in _trivy_steps()
        if name == "publish-release-tags.yml" and job == "release-cve-scan"
    ]
    assert len(release) == 1, "publish-release-tags.yml release-cve-scan must carry exactly one Trivy scan"
    inputs = release[0]
    assert _severity_scoped_sarif(inputs), "the release gate must scope its SARIF to the gated severities"
    assert {s.strip() for s in str(inputs["severity"]).split(",")} == {"HIGH", "CRITICAL"}
    assert _limits_sarif(inputs)
