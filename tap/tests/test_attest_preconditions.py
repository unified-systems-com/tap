"""A `push-to-registry` attestation needs registry credentials in its own job (req-cicd-sbom-4).

`actions/attest*` with ``push-to-registry: true`` stores the attestation beside the image,
which it can only do with registry credentials in the Docker config. Those credentials come
from a login step IN THE SAME JOB — a login in another job of the same workflow is a different
runner and a different Docker config.

This is not hypothetical. PR #538 moved SBOM signing into a first-party-only job and left the
registry login behind in the job it split from; every check passed, and the first real run
(35257723153, `publish-images` on main) failed on every attest step with
``Error: No credentials found for registry ghcr.io`` — images and provenance published, no SBOM
attestations, which is exactly the end state tap#518 had just closed (tap#543).

`publish-images.yml` only runs on push to main, so PR CI cannot exercise it: the invariant has
to be asserted statically, here, or it is asserted by production.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tap.guards.base import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: Actions that publish an attestation to the registry when `push-to-registry` is on.
_ATTEST_PREFIXES = ("actions/attest@", "actions/attest-build-provenance@", "actions/attest-sbom@")
#: What counts as establishing registry credentials for the rest of the job: the third-party
#: login action, or `docker login` in a run step (what a first-party-only job must use).
_LOGIN_ACTION_PREFIX = "docker/login-action@"
_LOGIN_COMMAND = "docker login"


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (job.get("steps") or []) if isinstance(s, dict)]


def _is_attest_push(step: dict[str, Any]) -> bool:
    uses = str(step.get("uses") or "")
    if not uses.startswith(_ATTEST_PREFIXES):
        return False
    with_block = step.get("with") or {}
    # A YAML `true` parses to bool; a quoted "true" stays a string. Both mean push.
    return str(with_block.get("push-to-registry", "")).lower() == "true"


def _establishes_credentials(step: dict[str, Any]) -> bool:
    if str(step.get("uses") or "").startswith(_LOGIN_ACTION_PREFIX):
        return True
    return _LOGIN_COMMAND in str(step.get("run") or "")


def unlogged_attest_steps(workflow: dict[str, Any], name: str) -> list[str]:
    """Return one message per `push-to-registry` attest step with no earlier login in its job."""
    problems: list[str] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        logged_in = False
        for index, step in enumerate(_steps(job)):
            if _establishes_credentials(step):
                logged_in = True
                continue
            if _is_attest_push(step) and not logged_in:
                label = step.get("name") or step.get("uses")
                problems.append(
                    f"{name} job `{job_name}` step {index + 1} (`{label}`): "
                    f"`push-to-registry: true` with no registry login earlier in this job — "
                    f"the attestation cannot be stored and every attest step fails at run time "
                    f"(tap#543). Add `docker login` (a run step keeps the job first-party-only) "
                    f"or move the step into a job that logs in."
                )
    return problems


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def test_every_push_to_registry_attestation_has_credentials_in_its_job() -> None:
    problems: list[str] = []
    for path in _workflow_files():
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            problems.extend(unlogged_attest_steps(data, path.name))
    assert not problems, "Attestation precondition violations (req-cicd-sbom-4):\n  " + "\n  ".join(problems)


def test_the_live_tree_actually_exercises_this() -> None:
    """A green check over zero attest steps would be a presence test, not a correctness one."""
    found = [
        path.name
        for path in _workflow_files()
        if any(
            _is_attest_push(step)
            for job in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("jobs", {}).values()
            if isinstance(job, dict)
            for step in _steps(job)
        )
    ]
    assert found, "no `push-to-registry` attest step found in .github/workflows — has the lane moved?"


_SHA = "0" * 40


def _workflow_yaml(steps: str) -> dict[str, Any]:
    raw: Any = yaml.safe_load(f"""
name: t
on: push
jobs:
  attest:
    runs-on: ubuntu-latest
    steps:
{steps}""")
    assert isinstance(raw, dict)
    return raw


_ATTEST_STEP = f"""      - uses: actions/attest@{_SHA} # v4
        with:
          subject-name: ghcr.io/org/image
          push-to-registry: true
"""


def test_attest_without_any_login_is_flagged() -> None:
    assert unlogged_attest_steps(_workflow_yaml(_ATTEST_STEP), "wf.yml")


@pytest.mark.parametrize(
    "login",
    [
        pytest.param(f"      - uses: docker/login-action@{_SHA} # v4\n", id="login-action"),
        pytest.param('      - run: echo "$T" | docker login ghcr.io -u u --password-stdin\n', id="docker-login-run"),
    ],
)
def test_a_login_earlier_in_the_same_job_satisfies_it(login) -> None:
    assert unlogged_attest_steps(_workflow_yaml(login + _ATTEST_STEP), "wf.yml") == []


def test_a_login_after_the_attest_step_does_not_count() -> None:
    login = '      - run: echo "$T" | docker login ghcr.io -u u --password-stdin\n'
    assert unlogged_attest_steps(_workflow_yaml(_ATTEST_STEP + login), "wf.yml")


def test_a_login_in_another_job_does_not_count() -> None:
    """The failure PR #538 shipped: the login lived in the job the signing job was split from."""
    raw: Any = yaml.safe_load(f"""
name: t
on: push
jobs:
  manifest:
    runs-on: ubuntu-latest
    steps:
      - uses: docker/login-action@{_SHA} # v4
  attest:
    runs-on: ubuntu-latest
    steps:
{_ATTEST_STEP}""")
    assert unlogged_attest_steps(raw, "wf.yml")


def test_an_attest_step_that_does_not_push_needs_no_login() -> None:
    step = f"""      - uses: actions/attest@{_SHA} # v4
        with:
          subject-name: ghcr.io/org/image
"""
    assert unlogged_attest_steps(_workflow_yaml(step), "wf.yml") == []
