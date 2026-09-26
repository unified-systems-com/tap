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
PLUGIN_NIGHTLY = WORKFLOWS / "plugin-nightly.yml"
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
    """One Trivy, one classifier, one severity floor across TAP. NOT one `ignore-unfixed` — see
    the test below, which holds that divergence on purpose so this one cannot be read as
    asserting it."""
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


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-10")
def test_the_plugin_gate_does_not_ignore_unfixed_and_the_release_gate_does(workflow: dict[str, Any]) -> None:
    """The one flag the two gates deliberately disagree on (ruling George, 2026-09-26, Q94d).

    The RELEASE gate scans a base-image closure: OS packages we do not pick, cannot patch and
    cannot drop, where `no fix available` genuinely means no lever exists — zlib CVE-2026-85091
    (tap#491) would otherwise refuse every release forever. That ruling (2026-09-17,
    req-cicd-base-image-lifecycle-2) stands unchanged.

    The PLUGIN gate scans a plugin's OWN Python dependency closure: packages we chose. An
    unfixable HIGH there almost always still has a lever — pin around it, drop it, swap it — and
    `--ignore-unfixed` is precisely the flag that stops anyone having to consider one. So the
    plugin road blocks on ANY unwaived HIGH/CRITICAL, fixed or not, on every event including a
    pull request: ship a fix, a workaround, or a waiver carrying its reason.

    Asserted in BOTH directions in one test, because the risk here is not that a flag is wrong —
    it is that a later reader sees two gates with different flags, reads it as drift, and
    reconciles them. This test is the note saying it was meant.
    """
    gate = next(step for step in _steps(workflow["jobs"][SCAN_JOB]) if step.get("id") == "gate_scan")
    assert "ignore-unfixed" not in gate["with"], (
        "the plugin closure gate must block on unfixable HIGH/CRITICAL too (Q94d); "
        "waive it in the plugin repo's .trivyignore with a reason, or fix it"
    )
    release = next(
        step
        for job in _load(RELEASE_TAGS)["jobs"].values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(TRIVY)
    )
    assert release["with"]["ignore-unfixed"] is True, "the release road keeps the 2026-09-17 ruling"


@pytest.fixture(name="plugin_nightly")
def _plugin_nightly() -> dict[str, Any]:
    return _load(PLUGIN_NIGHTLY)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-12")
def test_the_reusable_nightlys_reporter_cannot_be_steered(plugin_nightly: dict[str, Any]) -> None:
    """The three defects this file was written to remove, held here so they cannot come back.

    All three were live in 15 plugin repositories on 2026-09-26, in a hand-written copy of this
    job. The third is the one that is not merely noisy: an issue is identified by a hidden marker
    in the body THIS job wrote together with the authoring bot, never by a title anyone can
    choose — otherwise a stranger's issue gets closed or commented on by the bot.
    """
    job = plugin_nightly["jobs"]["owner-issue"]
    script = "\n".join(step.get("run", "") for step in _steps(job))

    assert "--limit" in script, "a listing with no limit silently truncates and files a duplicate"
    assert '-ge "$LIMIT"' in script, "hitting the limit is an UNKNOWN answer and must refuse, not guess"
    assert job["concurrency"]["cancel-in-progress"] is False
    assert "${{ github.repository }}" in job["concurrency"]["group"], "one caller must not serialise another"

    assert ".author.login" in script and "contains($m)" in script
    assert ".title ==" not in script, "the title is not this job's to own — see the docstring"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-12")
def test_the_reusable_nightly_writes_only_issues_and_only_from_one_job(
    plugin_nightly: dict[str, Any], workflow: dict[str, Any]
) -> None:
    """Its caller's grant is derived, not hand-kept: whatever the jobs ask for is what a plugin
    repository must grant, so a new scope fails here rather than at startup in 15 repositories."""
    needed = _union(plugin_nightly)
    assert needed.get("contents") != "write"
    assert needed.get("issues") == "write"
    writers = [
        name for name, job in plugin_nightly["jobs"].items() if _effective(plugin_nightly, job).get("issues") == "write"
    ]
    assert writers == ["owner-issue"], f"exactly one job may write issues, got {writers}"
    # It nests plugin-ci, so its caller must also cover everything plugin-ci asks for.
    for scope, level in _union(workflow).items():
        assert _LEVEL[needed.get(scope, "none")] >= _LEVEL[level], f"caller grant misses {scope}: {level}"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-12")
def test_the_reusable_nightly_probes_core_main(plugin_nightly: dict[str, Any]) -> None:
    """The row the lane exists for. `latest` is informational and must not be able to file."""
    main = plugin_nightly["jobs"]["main"]
    assert str(main["uses"]).endswith("plugin-ci.yml")
    assert main["with"]["harness_ref"] == "main"
    assert "inputs.latest_ref != ''" in str(plugin_nightly["jobs"]["latest"]["if"])
    owner = plugin_nightly["jobs"]["owner-issue"]
    assert owner["needs"] == ["main", "latest"]
    assert "$MAIN_RESULT" in "\n".join(step.get("run", "") for step in _steps(owner))
