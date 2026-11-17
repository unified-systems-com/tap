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
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tap.guards.base import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
PLUGIN_CI = WORKFLOWS / "plugin-ci.yml"
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
    """tap#796's shape, derived: a grant short of any job's request is a startup_failure; more is a leak.

    Core's caller of plugin-ci on a clock is the reusable plugin nightly, which every plugin
    repository's `nightly.yml` calls; each of its plugin-ci jobs must grant exactly the union."""
    nightly = _load(PLUGIN_NIGHTLY)
    callers = [job for job in nightly["jobs"].values() if str(job.get("uses", "")).endswith("plugin-ci.yml")]
    assert callers, "plugin-nightly.yml no longer calls plugin-ci.yml"
    for caller in callers:
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
    release = next(
        step
        for job in _load(RELEASE_TAGS)["jobs"].values()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith(TRIVY)
    )
    assert gate["uses"] == release["uses"]
    # The action pin alone is not "one Trivy": the binary is its own input, named on both.
    assert gate["with"]["version"] == release["with"]["version"]
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
    assert gate["with"]["ignore-unfixed"] == "false", (
        "the plugin closure gate must block on unfixable HIGH/CRITICAL too (Q94d); waive it in the "
        "plugin repo's .trivyignore with a reason, or fix it. Asserted as an explicit value, not as "
        "an absent key: omitting it relies on the pinned action's default, so a pin bump that "
        "changed that default would restore --ignore-unfixed with this test still green"
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


REPO_SCOPE_JOB = "repo-scope"


def _repo_scope_run(workflow: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in _steps(workflow["jobs"][REPO_SCOPE_JOB]))


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-13")
def test_the_repo_scope_job_runs_the_repo_checks_without_strict(workflow: dict[str, Any]) -> None:
    """Q85b: `--repo` never with `--strict` in a gate — a missing CODEOWNERS is a warning by policy."""
    script = _repo_scope_run(workflow)
    assert "tap_plugins.validate_plugin" in script
    assert "--repo" in script
    assert "--strict" not in script, "--strict would promote the CODEOWNERS warning to a failure"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-13")
def test_the_repo_scope_job_fails_on_a_failed_repo_check_and_on_none_running(workflow: dict[str, Any]) -> None:
    """The verdict is the `repo-*` checks: any failed one fails the job, and zero of them ran is not a pass."""
    script = _repo_scope_run(workflow)
    assert 'startswith("repo-")' in script
    assert '.status == "fail"' in script
    assert "no repo-* check ran" in script


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-13")
def test_the_repo_scope_job_is_read_only_and_checks_the_whole_repository(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"][REPO_SCOPE_JOB]
    assert _effective(workflow, job) == {"contents": "read"}
    checkout = next(s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["repository"] == "${{ inputs.plugin_repo || github.repository }}"
    assert checkout["with"]["persist-credentials"] is False
    assert "sparse-checkout" not in checkout["with"], "the shell checks read .github/ and the repository root"


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-13")
def test_the_ci_tooling_group_carries_a_yaml_parser() -> None:
    """Without PyYAML the pin and nightly-shape checks fail as inconclusive (req-tap-plugin-validate-repo-6)."""
    import tomllib

    groups = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["dependency-groups"]
    assert any(str(dep).lower().startswith("pyyaml") for dep in groups["ci-tooling"])


def _build_job_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """The steps of the job that builds the harness web image."""
    for job in workflow["jobs"].values():
        steps = _steps(job)
        if any(str(step.get("uses", "")).startswith("docker/build-push-action@") for step in steps):
            return steps
    raise AssertionError("no job builds the web image")


def test_every_build_attempt_takes_the_mirror_contexts(workflow: dict[str, Any]) -> None:
    """ECR Public's anonymous cap outlasts the retry, so each attempt must build from the
    mirror mapping, and the mapping must be computed before the first attempt."""
    steps = _build_job_steps(workflow)
    ids = [step.get("id") for step in steps]
    builds = [i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith("docker/build-push-action@")]
    assert len(builds) == 3
    assert ids.index("mirror") < builds[0]
    for i in builds:
        assert steps[i]["with"]["build-contexts"] == "${{ steps.mirror.outputs.contexts }}", steps[i]["name"]


def test_the_mirror_mapping_redirects_only_digest_pinned_ecr_library_images(
    workflow: dict[str, Any], tmp_path: Path
) -> None:
    """Run the step's own script on a Dockerfile like an old harness tag's: the digest-pinned
    ECR image maps to the same digest on mirror.gcr.io; a tag-only ECR reference and a
    non-ECR image are left alone, since only a digest guarantees the same bytes."""
    step = next(s for s in _build_job_steps(workflow) if s.get("id") == "mirror")
    digest = "sha256:" + "e" * 64
    (tmp_path / "Dockerfile").write_text(
        f"FROM public.ecr.aws/docker/library/node:24-alpine@{digest} AS js-vendor\n"
        "FROM --platform=linux/amd64 public.ecr.aws/docker/library/python:3.14\n"
        f"FROM cgr.dev/chainguard/wolfi-base:latest@{digest} AS base\n",
        encoding="utf-8",
    )
    out, summary = tmp_path / "out", tmp_path / "summary"
    script = tmp_path / "mirror_step.py"
    script.write_text(step["run"], encoding="utf-8")
    # Run it the way Actions does (`shell: python` = the interpreter on a script file).
    env = {**os.environ, "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)}
    subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow step's own body IS the test; argv list, no shell, the interpreter running pytest
        [sys.executable, str(script)], cwd=tmp_path, env=env, check=True, capture_output=True
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("contexts<<") and lines[-1] == lines[0].removeprefix("contexts<<")
    assert lines[1:-1] == [
        f"public.ecr.aws/docker/library/node:24-alpine@{digest}=docker-image://mirror.gcr.io/library/node@{digest}"
    ]


# `repository:` values a reusable workflow may check out with no `ref`, matched EXACTLY. A
# substring test would also pass `${{ github.repository_owner }}/other`, which is a foreign repo.
UNPINNED_CHECKOUT_REPOSITORIES = {
    # The caller's own repository: with no `ref`, checkout takes the caller's commit.
    "${{ github.repository }}",
    # The plugin under test. Core's nightly passes each plugin repo here on purpose, to test that
    # plugin's default branch as it stands: plugins float against a pinned core.
    "${{ inputs.plugin_repo || github.repository }}",
    # The product under test in product-health.yml, the same shape: the thing being checked,
    # not tooling the check executes.
    "${{ inputs.product_repo || github.repository }}",
}


def cross_repo_checkout_problems(name: str, data: dict[str, Any]) -> list[str]:
    """Checkouts of ANOTHER repository, in a reusable workflow, that name no `ref`.

    A reusable workflow runs in its caller's context, so a checkout of a different repository
    with no `ref` takes that repository's default branch at run time. The caller pins
    `<workflow>.yml@<sha>`, but what the job then checks out is not covered by that pin, so two
    runs of the same caller commit can execute different code. `plugin-release-sbom.yml` took
    its SBOM tooling from tap's default branch this way until it was given `job.workflow_sha`.
    Only the exact values in `UNPINNED_CHECKOUT_REPOSITORIES` are exempt.
    """
    # PyYAML (YAML 1.1) reads the bare key `on` as the boolean True.
    keys: dict[Any, Any] = data
    triggers = keys.get("on", keys.get(True)) or {}
    if not isinstance(triggers, dict) or "workflow_call" not in triggers:
        return []
    problems = []
    for job_id, job in (data.get("jobs") or {}).items():
        for index, step in enumerate(_steps(job)):
            if not str(step.get("uses", "")).startswith("actions/checkout@"):
                continue
            inputs = step.get("with") or {}
            repository = str(inputs.get("repository", ""))
            if repository and repository.strip() not in UNPINNED_CHECKOUT_REPOSITORIES and not inputs.get("ref"):
                problems.append(f"{name} job {job_id} step {step.get('name', index)}: {repository} with no ref")
    return problems


def test_every_reusable_workflow_pins_what_it_checks_out_of_another_repo() -> None:
    problems = [
        problem
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for problem in cross_repo_checkout_problems(path.name, _load(path))
    ]
    assert not problems, problems


def test_the_unpinned_release_tooling_checkout_fails_the_check() -> None:
    """Non-vacuity: plugin-release-sbom.yml's tooling checkout as it stood before the fix."""
    before: dict[str, Any] = yaml.safe_load(
        """
on:
  workflow_call: {}
jobs:
  release:
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: unified-systems-com/tap
          path: _core
          persist-credentials: false
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: ${{ inputs.plugin_repo || github.repository }}
"""
    )
    assert cross_repo_checkout_problems("before.yml", before) == [
        "before.yml job release step 0: unified-systems-com/tap with no ref"
    ]
    before["on"] = {"push": {}}
    assert cross_repo_checkout_problems("before.yml", before) == [], "only a called workflow runs as its caller"


def test_an_expression_that_merely_mentions_the_caller_repo_is_not_exempt() -> None:
    """Non-vacuity: `github.repository_owner` contains `github.repository` but names a foreign repo."""
    data: dict[str, Any] = yaml.safe_load(
        """
on:
  workflow_call: {}
jobs:
  build:
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: ${{ github.repository_owner }}/other
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1
        with:
          repository: ${{ github.repository }}
"""
    )
    assert cross_repo_checkout_problems("x.yml", data) == [
        "x.yml job build step 0: ${{ github.repository_owner }}/other with no ref"
    ]


def test_the_failure_probe_cannot_change_the_boot_job_result() -> None:
    """The tap#1013 crypto probe runs only after a failure, and its own failure is ignored."""
    steps = _steps(_load(PLUGIN_CI)["jobs"]["boot-and-test"])
    names = [step.get("name", "") for step in steps]
    probe = steps[names.index("Probe the web image's Python and crypto on failure")]
    assert probe["if"] == "failure()"
    assert probe["continue-on-error"] is True
    assert names.index("Dump web logs on failure") < names.index(probe["name"])


def _boot_steps() -> tuple[list[dict[str, Any]], list[str]]:
    steps = _steps(_load(PLUGIN_CI)["jobs"]["boot-and-test"])
    return steps, [step.get("name", "") for step in steps]


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-14")
def test_the_fast_set_runs_after_pre_boot_and_before_health_and_the_suite() -> None:
    """The ci_fast set runs during the boot's migrate, ahead of everything slow (aws-build Q70c)."""
    steps, names = _boot_steps()
    order = [
        "Boot the plugin profile",
        "Wait for pre-boot to install the plugins",
        "Start the test-DB template build (background)",
        "Fast set (ci_fast) — fail early",
        "Wait for the stack to become healthy",
        "Run the plugin's in-package tests",
    ]
    assert [names.index(name) for name in order] == sorted(names.index(name) for name in order)
    fast = steps[names.index("Fast set (ci_fast) — fail early")]
    assert "if" not in fast, "a failed fast set must stop the job, not be stepped over"
    run = fast["run"]
    assert '-m "ci_fast and not live_fetch"' in run
    assert "--no-sync" in run, "the venv must not be synced under the boot's running migrate"
    # Exit 5 is pytest's "no tests ran": a plugin that marks nothing is a no-op, not a red.
    assert "5)" in run and "exit 1" in run


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-14")
def test_the_parallel_suite_clones_one_template_and_has_a_serial_road() -> None:
    steps, names = _boot_steps()
    template = steps[names.index("Start the test-DB template build (background)")]["run"]
    assert "scripts/build-test-template" in template and "exec -d" in template
    assert 'mode=serial' in template and '"$TEST_WORKERS" = "0"' in template
    suite = steps[names.index("Run the plugin's in-package tests")]["run"]
    assert "TAP_TEST_DB_TEMPLATE=tap_test_template" in suite
    assert '-n "$TEST_WORKERS"' in suite
    # Both roads write the log the zero-executed summary reads.
    assert suite.count("| tee pytest.log") == 2
    # YAML 1.1 reads the bare `on:` key as the boolean True, so the trigger table is keyed by it.
    loaded: dict[Any, Any] = _load(PLUGIN_CI)
    workers = loaded[True]["workflow_call"]["inputs"]["test_workers"]
    assert workers["default"] == "auto" and workers["required"] is False


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-8")
def test_the_summary_still_fails_on_zero_executed_and_reports_the_fast_set() -> None:
    steps, names = _boot_steps()
    summary = steps[names.index("Summary (fails on zero executed tests)")]
    assert summary["if"] == "always()"
    run = summary["run"]
    assert 'Path("pytest.log")' in run and '[ "$executed" = "0" ]' in run
    assert "fast set (ci_fast)" in run


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-14")
def test_the_boot_waits_are_bounded_by_the_job_timeout_not_a_fixed_count() -> None:
    """A long boot is bounded by boot_and_test_timeout_minutes alone (rampart-20x-playground, 2026-11-17)."""
    steps, names = _boot_steps()
    for name in ("Wait for pre-boot to install the plugins", "Wait for the stack to become healthy"):
        step = steps[names.index(name)]
        assert step["env"]["BOOT_TIMEOUT_MIN"] == "${{ inputs.boot_and_test_timeout_minutes }}"
        assert "seq 1 $((BOOT_TIMEOUT_MIN * 6))" in step["run"]
        assert "seq 1 90" not in step["run"]
