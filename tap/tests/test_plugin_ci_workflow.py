"""The reusable plugin CI holds no write to code, and every caller can start it (tap#772).

Two defects in one family motivate these assertions. `plugin-ci.yml` once carried a job asking
for `contents: write` (the dependency-graph submission, tap#664). GitHub validates every job of a
called workflow against the caller's grant BEFORE creating any job — including a job whose `if:`
is false — so each caller that had not granted it got `startup_failure`: zero jobs, no log, and a
PR with no checks that looks the same as one that passed (tap#772; core's own nightly died three
nights running, tap#796). Then the ruling (George, 2026-09-25, Q20): no job in plugin CI may hold
`contents: write` at all.

The permission checks are DERIVED from the workflow, not a hand-kept list: the scopes a caller
must grant are whatever the jobs ask for, so a new job asking for a new scope fails the caller
check here, on the PR that adds it, instead of at startup in two dozen plugin repositories.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

from tap.guards.base import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PLUGIN_CI = WORKFLOWS / "plugin-ci.yml"
NIGHTLY_PLUGINS = WORKFLOWS / "nightly-plugins.yml"
RELEASE_TAGS = WORKFLOWS / "publish-release-tags.yml"

UPLOAD_JOB = "upload-dependency-sarif"
SCAN_JOB = "scan-dependencies"
TRIVY = "aquasecurity/trivy-action@"

_LEVEL = {"none": 0, "read": 1, "write": 2}


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


@pytest.fixture(name="workflow")
def _workflow() -> dict[str, Any]:
    return _load(PLUGIN_CI)


def _grants(permissions: Any) -> dict[str, str]:
    """A `permissions:` value as {scope: level}. Only mapping form is used in these files."""
    assert isinstance(permissions, dict), f"expected a scope mapping, got {permissions!r}"
    return {str(scope): str(level) for scope, level in permissions.items()}


def _effective(workflow: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    """A job's own block when it has one (it REPLACES the workflow's), else the workflow's."""
    return _grants(job["permissions"] if "permissions" in job else workflow["permissions"])


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = job.get("steps", [])
    return steps


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_no_job_in_plugin_ci_holds_contents_write(workflow: dict[str, Any]) -> None:
    """The ruling, stated as the property: not one scope anywhere reaches `contents: write`."""
    assert _grants(workflow["permissions"]).get("contents") == "read"
    offenders = sorted(
        name for name, job in workflow["jobs"].items() if _effective(workflow, job).get("contents") == "write"
    )
    assert not offenders, f"{offenders} hold contents: write in plugin-ci.yml (tap#772, Q20)"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_the_only_write_is_security_events_on_the_upload_job(workflow: dict[str, Any]) -> None:
    writers = {
        name: sorted(scope for scope, level in _effective(workflow, job).items() if level == "write")
        for name, job in workflow["jobs"].items()
    }
    writers = {name: scopes for name, scopes in writers.items() if scopes}
    assert writers == {UPLOAD_JOB: ["security-events"]}
    assert _grants(workflow["jobs"][UPLOAD_JOB]["permissions"]) == {"security-events": "write"}


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_the_upload_job_runs_no_plugin_code_and_checks_nothing_out(workflow: dict[str, Any]) -> None:
    uses = [step.get("uses", "") for step in _steps(workflow["jobs"][UPLOAD_JOB])]
    assert not any(step.get("run") for step in _steps(workflow["jobs"][UPLOAD_JOB])), "no shell in the write job"
    assert not any(ref.startswith("actions/checkout@") for ref in uses)
    assert [ref.split("@")[0] for ref in uses] == ["actions/download-artifact", "github/codeql-action/upload-sarif"]


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_the_upload_is_for_the_plugin_repos_default_branch_only(workflow: dict[str, Any]) -> None:
    condition = " ".join(str(workflow["jobs"][UPLOAD_JOB]["if"]).split())
    assert "inputs.plugin_repo == ''" in condition, "a cross-repo caller would file every plugin's findings on core"
    assert "github.event_name == 'schedule'" in condition
    assert "github.event_name == 'push'" in condition
    assert "github.event.repository.default_branch" in condition
    assert "pull_request" not in condition, "a pull request's findings are a proposal's, not the branch's"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_every_scope_a_job_asks_for_is_documented_for_callers(workflow: dict[str, Any]) -> None:
    """The header's caller example must grant what the jobs need, or new repos copy a startup_failure."""
    header = PLUGIN_CI.read_text(encoding="utf-8").split("\nname:", 1)[0]
    needed = _union(workflow)
    for scope, level in needed.items():
        assert f"#         {scope}: {level}" in header, f"the caller example does not grant {scope}: {level}"


def _union(workflow: dict[str, Any]) -> dict[str, str]:
    """Every scope any job asks for, at the highest level asked — what a caller must grant."""
    needed: dict[str, str] = {}
    for job in workflow["jobs"].values():
        for scope, level in _effective(workflow, job).items():
            if _LEVEL[level] > _LEVEL[needed.get(scope, "none")]:
                needed[scope] = level
    return needed


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-11")
def test_cores_nightly_caller_grants_exactly_what_plugin_ci_asks_for(workflow: dict[str, Any]) -> None:
    """tap#796's shape, derived: a grant short of any job's request is a startup_failure; more is a leak."""
    nightly = _load(NIGHTLY_PLUGINS)
    caller = next(job for job in nightly["jobs"].values() if str(job.get("uses", "")).endswith("plugin-ci.yml"))
    assert _grants(caller["permissions"]) == _union(workflow)
    assert _grants(caller["permissions"]).get("contents") != "write"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_the_scan_job_is_read_only_and_needs_the_walked_closure(workflow: dict[str, Any]) -> None:
    scan = workflow["jobs"][SCAN_JOB]
    assert _grants(scan["permissions"]) == {"contents": "read"}
    assert scan["needs"] == "boot-and-test"
    assert "needs.boot-and-test.outputs.closure_ready == 'true'" in str(scan["if"])
    walk = "\n".join(step.get("run", "") for step in _steps(workflow["jobs"]["boot-and-test"]))
    assert "tap.dependency_snapshot --format cyclonedx" in walk


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_the_gate_uses_the_release_gates_trivy_and_flags(workflow: dict[str, Any]) -> None:
    """One meaning of "fixable HIGH/CRITICAL" across TAP: same pin, same flags, same classifier."""
    steps = _steps(workflow["jobs"][SCAN_JOB])
    gate = next(step for step in steps if step.get("id") == "gate_scan")
    release_pin = next(
        step["uses"]
        for job in _load(RELEASE_TAGS)["jobs"].values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(TRIVY)
    )
    assert gate["uses"] == release_pin
    assert gate["with"]["severity"] == "HIGH,CRITICAL"
    assert gate["with"]["ignore-unfixed"] == "true"
    assert gate["with"]["exit-code"] == "1"
    # Without this the action builds SARIF at EVERY severity and `severity:` is silently ignored.
    assert gate["with"]["limit-severities-for-sarif"] == "true"
    assert gate.get("continue-on-error") is True, "the classifier, not Trivy's exit code, decides"
    classify = "\n".join(step.get("run", "") for step in steps)
    assert "release_cve_gate.py --gate plugin-closure" in classify
    assert '--scanner-outcome "$OUTCOME"' in classify
    assert "--check-waivers plugin/.trivyignore" in classify


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_the_summary_runs_whatever_the_verdict(workflow: dict[str, Any]) -> None:
    summary = next(step for step in _steps(workflow["jobs"][SCAN_JOB]) if "--markdown" in step.get("run", ""))
    assert summary.get("if") == "always()"
    assert "GITHUB_STEP_SUMMARY" in summary["run"]


def test_the_located_report_name_is_the_one_the_locator_derives(workflow: dict[str, Any]) -> None:
    """Mirror sites: the workflow tells Trivy the name, sarif_locate.py derives the same one."""
    spec = importlib.util.spec_from_file_location("sarif_locate", REPO_ROOT / "scripts" / "sbom" / "sarif_locate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    steps = _steps(workflow["jobs"][SCAN_JOB])
    report = next(
        step for step in steps if str(step.get("uses", "")).startswith(TRIVY) and step.get("id") != "gate_scan"
    )
    assert report["with"]["output"] == module.PLUGIN_CLOSURE_SARIF
    upload = _steps(workflow["jobs"][UPLOAD_JOB])[-1]
    assert upload["with"]["sarif_file"] == module.PLUGIN_CLOSURE_SARIF
