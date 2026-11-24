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

import hashlib
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
    owner = plugin_nightly["jobs"]["owner-issue"]
    assert owner["needs"] == ["main", "latest", "migrations"]
    assert "$MAIN_RESULT" in "\n".join(step.get("run", "") for step in _steps(owner))


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-16")
def test_the_reusable_nightly_tests_the_newest_release_every_night(plugin_nightly: dict[str, Any]) -> None:
    """The release row is no longer opt-in: with no `latest_ref` it follows core's newest release.

    The tag comes from the API and becomes a ref plugin-ci checks out, so the job that resolves
    it holds no scope, checks out nothing, and lets only `vX.Y.Z` through.
    """
    jobs = plugin_nightly["jobs"]
    latest = jobs["latest"]
    assert "if" not in latest, "the release row must run every night, not only when a caller names a tag"
    assert latest["needs"] == "newest-release"
    assert str(latest["uses"]).endswith("plugin-ci.yml")
    assert latest["with"]["harness_ref"] == "${{ needs.newest-release.outputs.tag }}"

    resolve = jobs["newest-release"]
    assert resolve["permissions"] == {}
    steps = _steps(resolve)
    assert not any("uses" in step for step in steps), "the resolving job runs no action and checks out nothing"
    run = "\n".join(step.get("run", "") for step in steps)
    assert "releases/latest" in run
    assert "${{" not in run, "inputs reach the script through env, never by interpolation"


def _resolve_release_row(
    tmp_path: Path, plugin_nightly: dict[str, Any], *, pinned: str, newest: str
) -> tuple[int, str]:
    """Run the resolver's own script with a stand-in `gh` that answers `newest`."""
    script = "\n".join(step.get("run", "") for step in _steps(plugin_nightly["jobs"]["newest-release"]))
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "gh").write_text('#!/bin/sh\nprintf "%s\\n" "$NEWEST"\n')
    (fake / "gh").chmod(0o755)
    out = tmp_path / "output"
    out.write_text("")
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "PINNED": pinned,
        "NEWEST": newest,
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    done = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow step's own body under a stub gh IS the test; argv list, no shell, PATH leads with a temp stub dir
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )
    return done.returncode, out.read_text()


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-16")
@pytest.mark.parametrize(("pinned", "newest"), [("", "v0.4.2"), ("v0.4.2", "ignored")])
def test_the_release_row_resolves_a_release_tag(
    tmp_path: Path, plugin_nightly: dict[str, Any], pinned: str, newest: str
) -> None:
    assert _resolve_release_row(tmp_path, plugin_nightly, pinned=pinned, newest=newest) == (0, "tag=v0.4.2\n")


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-16")
@pytest.mark.parametrize(
    ("pinned", "newest"),
    [
        ("main", "v0.4.2"),
        ("v0.4.2\nextra=1", "v0.4.2"),
        ("0123456789abcdef0123456789abcdef01234567", "v0.4.2"),
        ("", "main"),
        ("", "v0.4.2\nextra=1"),
        ("", "v0.4"),
    ],
)
def test_the_release_row_refuses_anything_that_is_not_a_release_tag(
    tmp_path: Path, plugin_nightly: dict[str, Any], pinned: str, newest: str
) -> None:
    """A caller's pin and the API's answer pass the same gate, and nothing is written on a refusal."""
    code, written = _resolve_release_row(tmp_path, plugin_nightly, pinned=pinned, newest=newest)
    assert code != 0
    assert written == ""


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
    # Its one condition is the migrations road, which runs no suite (tap#1262); no other `if:`
    # may let a failed fast set be stepped over.
    assert fast.get("if", _NOT_PARITY) == _NOT_PARITY, "a failed fast set must stop the job, not be stepped over"
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


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-14")
def test_the_boot_waits_never_sync_the_venv_pre_boot_is_installing() -> None:
    """The waits poll while pre-boot installs plugins: a syncing `uv run` there could rewrite the venv
    under it (PR 1219 review, Grok), so every command in them is `--no-sync`."""
    steps, names = _boot_steps()
    for name in ("Wait for pre-boot to install the plugins", "Wait for the stack to become healthy"):
        run = steps[names.index(name)]["run"]
        assert "uv run " not in run.replace("uv run --no-sync ", "")


# --------------------------------------------------------------------------- #
# The web image: pull the published, provenance-verified image for the harness SHA,
# else build (req-tap-plugin-extdev-repo-ci-15, aws-build Q78c)
# --------------------------------------------------------------------------- #

PULL_STEP = "Pull the published web image for the harness SHA (provenance-verified)"
_HARNESS_SHA = "d2599582803a260c04f3646ba11d2c8bcea41625"


def _uses(step: dict[str, Any], prefix: str) -> bool:
    return str(step.get("uses", "")).startswith(prefix)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_the_build_runs_only_when_no_verified_image_was_pulled() -> None:
    """The pull comes first; buildx, the mirror mapping and the first build attempt are each
    skipped once it succeeded (the later attempts already wait on the first one failing)."""
    steps, names = _boot_steps()
    pull = names.index(PULL_STEP)
    assert steps[pull]["id"] == "prebuilt"
    gate = "steps.prebuilt.outputs.pulled != 'true'"
    buildx = next(i for i, step in enumerate(steps) if _uses(step, "docker/setup-buildx-action@"))
    builds = [i for i, step in enumerate(steps) if _uses(step, "docker/build-push-action@")]
    mirror = next(i for i, step in enumerate(steps) if step.get("id") == "mirror")
    assert pull < buildx < mirror < builds[0]
    for i in (buildx, mirror, builds[0]):
        assert steps[i]["if"] == gate, steps[i].get("name", steps[i].get("uses"))
    for i in builds[1:]:
        assert "steps.build" in steps[i]["if"] and "failure" in steps[i]["if"]
    # Whichever road is taken, the stack boots the same local tag and never pulls on its own.
    assert "tap-web:ci" in steps[pull]["run"]
    assert all(steps[i]["with"]["tags"] == "tap-web:ci" for i in builds)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_the_pull_verifies_provenance_for_the_harness_sha_and_pulls_by_digest() -> None:
    steps, names = _boot_steps()
    step = steps[names.index(PULL_STEP)]
    assert step["env"]["HARNESS_SHA"] == "${{ needs.conformance.outputs.harness_sha }}"
    assert step["env"]["HARNESS_REPO"] == "${{ inputs.harness_repo }}"
    run = step["run"]
    assert "${{" not in run, "the body must take env: values only"
    for flag in (
        "--repo unified-systems-com/tap",
        "--signer-workflow unified-systems-com/tap/.github/workflows/publish-images.yml",
        "--source-ref refs/heads/main",
        '--source-digest "$HARNESS_SHA"',
        "--predicate-type https://slsa.dev/provenance/v1",
        "--deny-self-hosted-runners",
    ):
        assert flag in run, flag
    # The tag is a lookup only: every pull and tag names the digest that was verified.
    assert 'docker pull --quiet "$image@$index"' in run
    assert 'docker tag "$image@$index" tap-web:ci' in run
    assert run.count("docker pull") == 1
    # A miss builds; it never fails the job, so the step needs no continue-on-error to hide one.
    assert "continue-on-error" not in step
    assert "set -e" not in run.replace("set -uo pipefail", "")


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_no_secret_is_written_into_the_tree_before_the_image_exists() -> None:
    """`COPY . .` takes the whole tree, so a PAT written before the build would land in an image
    layer and in the GitHub Actions cache export."""
    steps, names = _boot_steps()
    last_image_step = max(
        i for i, step in enumerate(steps) if _uses(step, "docker/build-push-action@") or step.get("id") == "prebuilt"
    )
    for name in ("Prepare secrets root", "Wire read-only plugins PAT"):
        assert last_image_step < names.index(name) < names.index("Boot the plugin profile"), name


_PULL_DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
case "$*" in
  "buildx imagetools inspect --raw "*)
    [ -n "${STUB_INDEX_BYTES:-}" ] || exit 1
    printf '%s' "$STUB_INDEX_BYTES" ;;
  "pull --quiet "*|"tag "*) exit 0 ;;
  *) echo "unexpected docker call: $*" >&2; exit 2 ;;
esac
"""

_PULL_GH_STUB = """#!/usr/bin/env bash
echo "gh $*" >> "$STUB_LOG"
exit "${STUB_GH_RC:-0}"
"""


def _run_pull(tmp_path: Path, dockerfile: str = "ARG TAP_FIPS=1\n", **overrides: str) -> tuple[str, str, list[str]]:
    """Run the pull step's own body under stub docker/gh; return (output, summary, calls)."""
    steps, names = _boot_steps()
    body = str(steps[names.index(PULL_STEP)]["run"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in (("docker", _PULL_DOCKER_STUB), ("gh", _PULL_GH_STUB)):
        (bin_dir / name).write_text(source, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (tmp_path / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    log, out, summary = tmp_path / "calls", tmp_path / "out", tmp_path / "summary"
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "HARNESS_REPO": "unified-systems-com/tap",
        "HARNESS_SHA": _HARNESS_SHA,
        "GH_TOKEN": "stub",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(out),
        "GITHUB_STEP_SUMMARY": str(summary),
        "STUB_LOG": str(log),
        "STUB_INDEX_BYTES": '{"mediaType":"application/vnd.oci.image.index.v1+json"}',
        "STUB_GH_RC": "0",
    }
    env.update(overrides)
    result = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow step's own body under stub docker/gh IS the test; argv list, no shell, PATH is a temp stub dir
        ["bash", "-c", body], env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return out.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"), calls


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_a_verified_image_is_pulled_by_the_digest_of_the_bytes_served(tmp_path: Path) -> None:
    raw = '{"mediaType":"application/vnd.oci.image.index.v1+json"}'
    digest = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    out, summary, calls = _run_pull(tmp_path, STUB_INDEX_BYTES=raw)
    assert out.strip() == "pulled=true"
    ref = f"ghcr.io/unified-systems-com/tap-web@{digest}"
    assert f"docker buildx imagetools inspect --raw ghcr.io/unified-systems-com/tap-web:sha-{_HARNESS_SHA[:7]}" in calls
    assert any(
        c.startswith(f"gh attestation verify oci://{ref} ") and f"--source-digest {_HARNESS_SHA}" in c for c in calls
    )
    assert f"docker pull --quiet {ref}" in calls and f"docker tag {ref} tap-web:ci" in calls
    assert digest in summary


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"STUB_GH_RC": "1"}, "does not verify"),
        ({"STUB_INDEX_BYTES": ""}, "no image is published"),
        ({"HARNESS_REPO": "someone/tap"}, "only unified-systems-com/tap"),
        ({"HARNESS_SHA": "main"}, "not a full commit SHA"),
    ],
)
def test_anything_short_of_a_verified_image_builds_and_pulls_nothing(
    tmp_path: Path, overrides: dict[str, str], reason: str
) -> None:
    out, summary, calls = _run_pull(tmp_path, **overrides)
    assert out.strip() == "pulled=false"
    assert reason in summary and "built here" in summary
    assert not any(c.startswith(("docker pull", "docker tag")) for c in calls), calls


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_a_harness_whose_dockerfile_builds_another_fips_posture_is_not_swapped(tmp_path: Path) -> None:
    """publish-images builds TAP_FIPS=1 only; a harness defaulting otherwise must build its own."""
    out, summary, calls = _run_pull(tmp_path, dockerfile="ARG TAP_FIPS=0\n")
    assert out.strip() == "pulled=false" and "TAP_FIPS=1" in summary
    assert calls == []


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-15")
def test_the_secrets_root_is_cleared_before_the_image_and_filled_after() -> None:
    """Nothing at tap_secrets/ may be in the build context, whether pulled or built (the build context is `.`):
    the clear runs before the image step, and the root is created and the PAT written only after it."""
    steps, names = _boot_steps()
    clear = names.index("Clear the secrets root before the image")
    image = names.index("Pull the published web image for the harness SHA (provenance-verified)")
    prepare = names.index("Prepare secrets root")
    assert clear < image < prepare
    run = steps[clear]["run"]
    assert "rm -f tap_secrets" in run and "exit 1" in run


# The migrations road (tap#1262). Every other database plugin CI makes is built from the models
# (tap#1258), so these hold the one road that still replays a plugin's migrations from zero.

_NOT_PARITY = "${{ !inputs.schema_parity }}"


def _inputs(path: Path) -> dict[str, Any]:
    # YAML 1.1 reads the bare `on:` key as the boolean True, so the trigger table is keyed by it.
    loaded: dict[Any, Any] = _load(path)
    inputs: dict[str, Any] = loaded[True]["workflow_call"]["inputs"]
    return inputs


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
def test_the_migrations_road_is_off_unless_asked_for() -> None:
    """A pull request never takes it: the input defaults false, and only the nightly passes it."""
    parity = _inputs(PLUGIN_CI)["schema_parity"]
    assert parity["type"] == "boolean" and parity["default"] is False and parity["required"] is False


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
def test_the_migrations_road_boots_from_zero_and_proves_parity_before_anything_else() -> None:
    steps, names = _boot_steps()
    boot = steps[names.index("Boot the plugin profile")]
    assert boot["env"]["TAP_BOOT_INSTALL__SCHEMA_FROM_MODELS"] == "${{ inputs.schema_parity && 'false' || 'true' }}"
    parity_name = "Parity — the real migrations from zero equal a model-built database"
    parity = steps[names.index(parity_name)]
    assert parity["if"] == "${{ inputs.schema_parity }}"
    assert parity["id"] == "parity"
    assert "python -m tap.schema_parity" in parity["run"]
    assert "set -o pipefail" in parity["run"], "the tee must not swallow a failed parity"
    assert "tap/schema_parity.py" in parity["run"], "a harness without the module fails closed"
    order = ["Wait for the stack to become healthy", parity_name, "Run the plugin's in-package tests"]
    assert [names.index(name) for name in order] == sorted(names.index(name) for name in order)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
def test_the_migrations_road_runs_no_suite_and_its_summary_needs_the_parity_step() -> None:
    steps, names = _boot_steps()
    for name in (
        "Start the test-DB template build (background)",
        "Fast set (ci_fast) — fail early",
        "Run the plugin's in-package tests",
    ):
        assert steps[names.index(name)]["if"] == _NOT_PARITY, name
    after = steps[names.index("After-tests command (caller-supplied)")]
    assert after["if"] == "${{ inputs.after_tests_command != '' && !inputs.schema_parity }}"
    summary = steps[names.index("Summary (fails on zero executed tests)")]
    assert summary["env"]["PARITY_OUTCOME"] == "${{ steps.parity.outcome || 'not reached' }}"
    run = summary["run"]
    # On the migrations road the evidence is the parity step, and anything but success is red.
    assert '[ "$PARITY_OUTCOME" != success ]' in run
    assert run.index('[ "$SCHEMA_PARITY" = true ]') < run.index('[ "$executed" = "0" ]')


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
def test_the_nightly_runs_the_migrations_row_against_core_main(plugin_nightly: dict[str, Any]) -> None:
    row = plugin_nightly["jobs"]["migrations"]
    assert str(row["uses"]).endswith("plugin-ci.yml")
    assert row["if"] == "${{ inputs.migrations }}"
    assert row["with"]["harness_ref"] == "main"
    assert row["with"]["schema_parity"] is True
    assert row["with"]["boot_and_test_timeout_minutes"] == "${{ inputs.migrations_timeout_minutes }}"
    assert row["permissions"] == plugin_nightly["jobs"]["main"]["permissions"]
    inputs = _inputs(PLUGIN_NIGHTLY)
    assert inputs["migrations"]["default"] is True, "on by default: it is the only road that replays them"
    assert inputs["migrations_timeout_minutes"]["default"] > inputs["boot_and_test_timeout_minutes"]["default"]


def _owner_issue(
    tmp_path: Path, plugin_nightly: dict[str, Any], *, main: str, migrations: str, open_issue: bool = False
) -> tuple[int, str, str]:
    """Run the owner-issue step under a stand-in `gh` and `jq`: not a fork, writes logged, and either no
    open owner issue or one (number 7) that an earlier red night filed."""
    script = "\n".join(step.get("run", "") for step in _steps(plugin_nightly["jobs"]["owner-issue"]))
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "gh.log"
    (fake / "gh").write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        '  "api repos/"*) echo false ;;\n'
        '  "issue list") echo "[]" ;;\n'
        '  *) echo "$*" >> "$GH_LOG" ;;\n'
        "esac\n"
    )
    (fake / "gh").chmod(0o755)
    # The script's two jq reads are fixed: the count of open issues and the owner issue's number. A
    # stand-in, because the web image ships no jq and the verdict, not jq, is what is under test.
    count, number = ("1", "7") if open_issue else ("0", "")
    (fake / "jq").write_text(
        "#!/bin/sh\ncat >/dev/null\n"
        f'for a; do [ "$a" = length ] && {{ echo {count}; exit 0; }}; done\n'
        f'[ -n "{number}" ] && echo {number}\nexit 0\n'
    )
    (fake / "jq").chmod(0o755)
    env = {
        "PATH": f"{fake}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GITHUB_SERVER_URL": "https://github.example",
        "GITHUB_REPOSITORY": "owner/plugin",
        "GITHUB_RUN_ID": "1",
        "MAIN_RESULT": main,
        "LATEST_RESULT": "success",
        "MIGRATIONS_RESULT": migrations,
        "TITLE": "Nightly red vs core main",
        "ASSIGNEE": "",
        "MARKER": "<!-- tap-plugin-nightly-owner-issue -->",
        "LIMIT": "1000",
    }
    done = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow step's own body under a stub gh IS the test; argv list, no shell, PATH leads with a temp stub dir
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )
    return done.returncode, log.read_text() if log.exists() else "", done.stderr


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
@pytest.mark.parametrize(
    ("main", "migrations", "red"),
    [
        ("success", "success", False),
        ("success", "skipped", False),
        ("success", "failure", True),
        ("failure", "success", True),
    ],
)
def test_a_red_migrations_row_files_the_owner_issue(
    tmp_path: Path, plugin_nightly: dict[str, Any], main: str, migrations: str, red: bool
) -> None:
    """The row is not informational: with `main` green, a failed migrations row still reds the night."""
    code, writes, stderr = _owner_issue(tmp_path, plugin_nightly, main=main, migrations=migrations)
    assert (code != 0) is red, stderr
    assert ("issue create" in writes) is red
    if red:
        assert f"migrations row: {migrations}" in writes


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-17")
@pytest.mark.parametrize(("main", "migrations", "closes"), [("success", "success", True), ("success", "cancelled", False)])
def test_only_a_migrations_row_that_ran_closes_the_owner_issue(
    tmp_path: Path, plugin_nightly: dict[str, Any], main: str, migrations: str, closes: bool
) -> None:
    """A cancelled replay proved nothing: it must not close the issue a failed replay opened (PR 1313 review)."""
    code, writes, stderr = _owner_issue(tmp_path, plugin_nightly, main=main, migrations=migrations, open_issue=True)
    assert code == 0, stderr
    assert ("issue close 7" in writes) is closes, writes
    assert "issue create" not in writes


# The migrations-match-models check (req-tap-plugin-extdev-repo-ci-18; Q57a, Issue# 1284 - tap). Every
# road but the nightly's migrations row builds its databases from the models, so nothing else notices
# a plugin whose models (or whose BaseModel, moved by core) need a migration it does not ship.

MAKEMIGRATIONS_STEP = "Migrations — the plugin's models need no new migration"

_MM_DOCKER_STUB = """#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
case "$*" in
  *"manage.py shell"*)
    echo "a boot log line on stdout"
    [ -n "${STUB_LABELS+x}" ] && echo "TAP-LABELS: $STUB_LABELS"
    [ -n "${STUB_SECOND_LABELS+x}" ] && echo "TAP-LABELS: $STUB_SECOND_LABELS"
    [ -n "${STUB_TRAILING_LINES+x}" ] && seq 1 "$STUB_TRAILING_LINES"
    echo "a log line printed after the labels"
    exit 0 ;;
  *"manage.py makemigrations"*)
    echo "Migrations for 'grid_fixtures': (stub)"
    exit "${STUB_MM_RC:-0}" ;;
  *) echo "unexpected docker call: $*" >&2; exit 2 ;;
esac
"""


def _run_makemigrations(tmp_path: Path, **overrides: str | None) -> tuple[int, str, str, list[str]]:
    """Run the check's own body under a stub docker; return (exit code, output, step output, calls)."""
    steps, names = _boot_steps()
    body = str(steps[names.index(MAKEMIGRATIONS_STEP)]["run"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(_MM_DOCKER_STUB, encoding="utf-8")
    (bin_dir / "docker").chmod(0o755)
    log, out = tmp_path / "calls", tmp_path / "out"
    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "PLUGIN_SLUG": "grid_fixtures",
        "GITHUB_OUTPUT": str(out),
        "STUB_LOG": str(log),
        "STUB_LABELS": "grid_fixtures",
    }
    env.update({key: value for key, value in overrides.items() if value is not None})
    for key in [key for key, value in overrides.items() if value is None]:
        env.pop(key)
    result = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow step's own body under a stub docker IS the test; argv list, no shell, PATH leads with a temp stub dir
        ["bash", "-c", body], env=env, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    step_out = out.read_text(encoding="utf-8") if out.exists() else ""
    return result.returncode, result.stdout + result.stderr, step_out, calls


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_the_migrations_check_runs_on_both_roads_after_the_boot_and_before_parity_and_the_suite() -> None:
    steps, names = _boot_steps()
    step = steps[names.index(MAKEMIGRATIONS_STEP)]
    assert step["id"] == "makemigrations"
    assert "if" not in step, "both roads: a pull request and the nightly's migrations row"
    assert "continue-on-error" not in step
    assert 'makemigrations "${label_list[@]}" --check --dry-run' in step["run"]
    order = [
        "Wait for the stack to become healthy",
        MAKEMIGRATIONS_STEP,
        "Parity — the real migrations from zero equal a model-built database",
        "Run the plugin's in-package tests",
    ]
    assert [names.index(name) for name in order] == sorted(names.index(name) for name in order)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_the_check_reads_the_plugins_labels_from_the_marker_and_passes_when_nothing_is_owed(tmp_path: Path) -> None:
    code, output, step_out, calls = _run_makemigrations(tmp_path, STUB_LABELS="grid_fixtures grid_fixtures_extra")
    assert code == 0, output
    assert "labels=grid_fixtures grid_fixtures_extra" in step_out
    checks = [c for c in calls if "makemigrations" in c]
    assert len(checks) == 1
    assert "makemigrations grid_fixtures grid_fixtures_extra --check --dry-run -v 3" in checks[0]


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_a_migration_owed_fails_the_check_and_names_the_remedy(tmp_path: Path) -> None:
    code, output, _, _ = _run_makemigrations(tmp_path, STUB_MM_RC="1")
    assert code != 0
    assert "::error::tap_plugin.grid_fixtures's models differ from its migrations" in output
    assert "manage.py makemigrations grid_fixtures" in output and "requires_tap" in output
    assert (tmp_path / "makemigrations.log").read_text(encoding="utf-8").startswith("Migrations for"), (
        "the would-be migration is kept for the author"
    )


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
@pytest.mark.parametrize("labels", [None, ""])
def test_no_plugin_app_in_the_registry_fails_closed_without_checking(tmp_path: Path, labels: str | None) -> None:
    code, output, _, calls = _run_makemigrations(tmp_path, STUB_LABELS=labels)
    assert code != 0
    assert "nothing to check, so this fails closed" in output
    assert not any("makemigrations" in c for c in calls)


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_the_summary_is_red_unless_the_migrations_check_succeeded_on_either_road() -> None:
    steps, names = _boot_steps()
    summary = steps[names.index("Summary (fails on zero executed tests)")]
    assert summary["env"]["MAKEMIGRATIONS_OUTCOME"] == "${{ steps.makemigrations.outcome || 'not reached' }}"
    run = summary["run"]
    gate = '[ "$MAKEMIGRATIONS_OUTCOME" != success ]'
    assert gate in run
    # Before the migrations road's early exit, so that road is held to it too.
    assert run.index(gate) < run.rindex('[ "$SCHEMA_PARITY" = true ]')


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_the_labels_reach_makemigrations_as_argv_never_inside_a_command_string() -> None:
    """Nothing read back from the container is spliced into a string a shell parses (PR 1352 review)."""
    steps, names = _boot_steps()
    run = str(steps[names.index(MAKEMIGRATIONS_STEP)]["run"])
    check = run[run.index("set +e") :]
    assert "sh -c" not in check, "the check runs manage.py directly, with the labels as separate words"
    assert '"${label_list[@]}"' in check


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
@pytest.mark.parametrize(
    "labels",
    [
        'grid_fixtures"; touch pwned; echo "',
        "grid_fixtures'; touch pwned; echo '",
        "grid_fixtures $(touch pwned)",
        "grid_fixtures;touch pwned",
        "grid-fixtures",
        "9grid",
    ],
)
def test_a_label_that_is_not_an_identifier_fails_closed_without_checking(tmp_path: Path, labels: str) -> None:
    code, output, step_out, calls = _run_makemigrations(tmp_path, STUB_LABELS=labels)
    assert code != 0
    assert "not an identifier" in output and "fails closed" in output
    assert not any("makemigrations" in c for c in calls)
    assert step_out == "", "nothing unvalidated reaches GITHUB_OUTPUT"
    assert not (tmp_path / "pwned").exists()


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_a_newline_in_the_labels_cannot_add_a_label_or_an_output_line(tmp_path: Path) -> None:
    code, output, step_out, calls = _run_makemigrations(
        tmp_path, STUB_LABELS="grid_fixtures\nlabels=forged\ntouch pwned"
    )
    assert code == 0, output
    assert step_out == "labels=grid_fixtures\n"
    checks = [c for c in calls if "makemigrations" in c]
    assert len(checks) == 1
    assert checks[0].endswith("manage.py makemigrations grid_fixtures --check --dry-run -v 3")
    assert not (tmp_path / "pwned").exists()


@pytest.mark.spec("req-tap-plugin-extdev-repo-ci-18")
def test_only_the_first_marked_line_names_the_labels(tmp_path: Path) -> None:
    code, output, step_out, calls = _run_makemigrations(
        tmp_path, STUB_LABELS="grid_fixtures", STUB_SECOND_LABELS="other_app"
    )
    assert code == 0, output
    assert step_out == "labels=grid_fixtures\n"
    checks = [c for c in calls if "makemigrations" in c]
    assert len(checks) == 1 and "other_app" not in checks[0]


def test_output_after_the_marker_cannot_break_the_pipe(tmp_path: Path) -> None:
    """The extractor reads the whole stream: stopping at the first marker would leave the
    producer writing into a closed pipe, and under ``pipefail`` the step would die with 141
    (seen on the server for PR# 1352 - tap, where the stub's trailing line was enough)."""
    code, output, step_out, _ = _run_makemigrations(
        tmp_path, STUB_LABELS="grid_fixtures", STUB_TRAILING_LINES="200000"
    )
    assert code == 0, output
    assert step_out == "labels=grid_fixtures\n"
