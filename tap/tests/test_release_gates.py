"""A versioned release is gated on its attestations, and `:latest` moves last (req-cicd-sbom-4).

`publish-release-tags.yml` used to poll until `:sha-<short>` EXISTED and then promote it —
presence read as completeness. For 15 days (tap#518), and again on the very next change
(tap#543), that meant `:X.Y.Z` tags were cut from images whose SBOM attestations had never
been produced. The workflow was green each time.

Neither workflow can be exercised by PR CI: `publish-release-tags` runs only on a `v*` tag and
`publish-images` only on a push to main. That is precisely how both failures shipped green. So
the gate is asserted two ways here:

* **structurally** — the verification step exists and runs BEFORE the tag is created, and
  nothing creates `:latest` before the SBOMs are attested;
* **behaviourally** — the verification step's own `run:` body is executed against stub `docker`
  and `gh` binaries, proving each of its three outcomes (verified / MISSING / NOT OBSERVABLE).

The body is written to invoke only `docker` and `gh` and to take every value through `env:`,
which is what makes the second half possible.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tap.guards.base import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_TAGS_WF = WORKFLOWS_DIR / "publish-release-tags.yml"
PUBLISH_IMAGES_WF = WORKFLOWS_DIR / "publish-images.yml"

#: The step that must run before any version tag is created.
GATE_STEP = "Every published digest carries its attestations (fail-closed)"
#: Confirmed against the real 2026-09-19 attestations (run 35411727282), not from memory:
#: provenance on the index digest, both SBOM predicates on each per-arch child.
PROVENANCE_PREDICATE = "https://slsa.dev/provenance/v1"
CYCLONEDX_PREDICATE = "https://cyclonedx.org/bom"
SPDX_PREDICATE = "https://spdx.dev/Document/v2.3"

_INDEX = "sha256:b4d214dc73631be23ee9b6c51c2ebee7133df23072c674f4bebc26cd896dbbb6"
_AMD64 = "sha256:118bca00e935c39a0953099d380e237c71f4321f728d430d060c6f42cf43c457"
_ARM64 = "sha256:725d0682bfc8c19ae2d2c31290a2a9047b9beeb52b6d5f66b1ad759db6b48c24"


def _workflow(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps(workflow: dict[str, Any], job: str) -> list[dict[str, Any]]:
    return [s for s in (workflow["jobs"][job].get("steps") or []) if isinstance(s, dict)]


def _step_index(steps: list[dict[str, Any]], name: str) -> int:
    for index, step in enumerate(steps):
        if step.get("name") == name:
            return index
    raise AssertionError(f"step {name!r} not found in {[s.get('name') for s in steps]}")


# --------------------------------------------------------------------------- #
# Structure: the gate is present, and it is upstream of the promotion
# --------------------------------------------------------------------------- #


def test_attestations_are_verified_before_the_version_tag_is_created() -> None:
    steps = _steps(_workflow(RELEASE_TAGS_WF), "retag")
    gate = _step_index(steps, GATE_STEP)
    creates = [
        index
        for index, step in enumerate(steps)
        if "imagetools create" in str(step.get("run") or "") and "${VERSION}" in str(step.get("run") or "")
    ]
    assert creates, "no step creates the version tag — has the promotion moved?"
    assert all(
        index > gate for index in creates
    ), "a version tag is created before the attestation gate runs — the gate would not gate (tap#525)"


def test_the_promotion_uses_the_digest_the_gate_verified() -> None:
    """Digest-threading: a tag re-resolved after the check could have moved (Grok, PR #629)."""
    steps = _steps(_workflow(RELEASE_TAGS_WF), "retag")
    promote = next(s for s in steps if "imagetools create" in str(s.get("run") or ""))
    body = _executable_lines(str(promote["run"]))
    assert "${ref}@${INDEX}" in body, f"promotion does not consume the verified digest: {body}"
    assert "${ref}:${SHA_TAG}" not in body, "promotion re-resolves a mutable tag after the gate"
    assert "steps.gate.outputs.index" in str(promote.get("env") or {})


def test_the_gate_checks_provenance_and_both_sbom_predicates() -> None:
    steps = _steps(_workflow(RELEASE_TAGS_WF), "retag")
    env = steps[_step_index(steps, GATE_STEP)].get("env") or {}
    declared = {str(v) for v in env.values()}
    for predicate in (PROVENANCE_PREDICATE, CYCLONEDX_PREDICATE, SPDX_PREDICATE):
        assert predicate in declared, f"the gate does not check {predicate}"


def test_the_gate_adds_no_write_scope_to_the_retag_job() -> None:
    """The gate only reads: the registry remains the job's single write path."""
    permissions = _workflow(RELEASE_TAGS_WF)["jobs"]["retag"].get("permissions") or {}
    assert permissions.get("contents") == "read"
    assert permissions.get("attestations") == "read", "gh attestation verify needs the attestations API"
    writes = {scope for scope, level in permissions.items() if level == "write"}
    assert writes == {"packages"}, f"retag gained a write scope: {writes}"


# --------------------------------------------------------------------------- #
# Structure: `:latest` moves only after the SBOMs are attested
# --------------------------------------------------------------------------- #


def _executable_lines(body: str) -> str:
    """The body without its comments — a comment mentioning a tag does not create one."""
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("#"))


def test_the_merge_step_no_longer_tags_latest() -> None:
    bodies = " ".join(
        _executable_lines(str(step.get("run") or "")) for step in _steps(_workflow(PUBLISH_IMAGES_WF), "manifest")
    )
    assert ":latest" not in bodies, (
        "the manifest job tags :latest again — a failed SBOM lane would leave the pointer "
        "consumers follow aimed at an unattested image (tap#525)"
    )


def test_latest_is_promoted_only_after_the_sbom_attestations() -> None:
    workflow = _workflow(PUBLISH_IMAGES_WF)
    movers = [
        name
        for name, job in workflow["jobs"].items()
        if any(
            ':latest"' in _executable_lines(str(step.get("run") or ""))
            for step in (job.get("steps") or [])
            if isinstance(step, dict)
        )
    ]
    assert movers == ["promote-latest"], f"unexpected jobs moving :latest: {movers}"
    needs = workflow["jobs"]["promote-latest"]["needs"]
    assert "attest-sbom" in needs, f"promote-latest does not wait for attestation: {needs}"


def test_a_backfill_run_still_does_not_move_latest() -> None:
    condition = str(_workflow(PUBLISH_IMAGES_WF)["jobs"]["promote-latest"]["if"])
    assert (
        "inputs.ref" in condition and "''" in condition
    ), f"promote-latest must skip backfills (inputs.ref set), got {condition!r}"


# --------------------------------------------------------------------------- #
# Behaviour: run the gate's own body against stubs
# --------------------------------------------------------------------------- #


def _gate_body() -> str:
    steps = _steps(_workflow(RELEASE_TAGS_WF), "retag")
    body = str(steps[_step_index(steps, GATE_STEP)]["run"])
    assert "${{" not in body, "the gate body interpolates an expression — it must take env: values only"
    return body


_DOCKER_STUB = """#!/usr/bin/env bash
# docker buildx imagetools inspect <ref> --format <template>
case "$*" in
  *"{{.Manifest.Digest}}"*) printf '%s\\n' "${STUB_INDEX}" ;;
  *"Manifest.Manifests"*)   printf '%s\\n' "${STUB_CHILDREN}" ;;
  *) echo "unexpected docker call: $*" >&2; exit 2 ;;
esac
"""

# Mirrors the real CLI: a subject with no such attestation answers HTTP 404 from the
# attestations API; anything else (registry, network, auth) is a different failure.
_GH_STUB = """#!/usr/bin/env bash
subject=""
predicate=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    oci://*) subject="$1" ;;
    --predicate-type) shift; predicate="$1" ;;
  esac
  shift
done
if [ "${STUB_MODE}" = "all-ok" ]; then
  echo "Loaded digest ${subject}"
  exit 0
fi
if [ "${STUB_MODE}" = "missing" ] && [ "${predicate}" = "${STUB_FAIL_PREDICATE}" ]; then
  echo "Error: HTTP 404: Not Found (https://api.github.com/orgs/o/attestations/x)" >&2
  exit 1
fi
if [ "${STUB_MODE}" = "unreachable" ] && [ "${predicate}" = "${STUB_FAIL_PREDICATE}" ]; then
  echo "Error: dial tcp: lookup api.github.com: no such host" >&2
  exit 1
fi
echo "Loaded digest ${subject}"
exit 0
"""


def _run_gate(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, source in (("docker", _DOCKER_STUB), ("gh", _GH_STUB)):
        stub = bin_dir / name
        stub.write_text(source, encoding="utf-8")
        stub.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        "REGISTRY": "ghcr.io",
        "OWNER": "unified-systems-com",
        "IMAGE": "tap-db",
        "SHA_TAG": "sha-207c54c",
        "VERSION": "0.1.8",
        "COMMIT": "207c54c3",
        "GH_TOKEN": "stub",
        "PROVENANCE_PREDICATE": PROVENANCE_PREDICATE,
        "CYCLONEDX_PREDICATE": CYCLONEDX_PREDICATE,
        "SPDX_PREDICATE": SPDX_PREDICATE,
        "STUB_INDEX": _INDEX,
        "STUB_CHILDREN": f"{_AMD64} {_ARM64} ",
        "STUB_MODE": "all-ok",
        "STUB_FAIL_PREDICATE": "",
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
    }
    env.update(overrides)
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — executing the committed workflow's own body under stub docker/gh IS the test; argv list, no shell, PATH is a temp stub dir
        ["bash", "-c", _gate_body()],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )


def test_a_fully_attested_candidate_is_promoted(tmp_path) -> None:
    result = _run_gate(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error::" not in result.stdout
    # provenance on the index + two predicates on each of two children.
    assert result.stdout.count("  ok ") == 5
    # The promotion downstream consumes exactly what was verified here.
    assert f"index={_INDEX}" in (tmp_path / "github_output").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "predicate",
    [
        pytest.param(PROVENANCE_PREDICATE, id="provenance"),
        pytest.param(CYCLONEDX_PREDICATE, id="cyclonedx"),
        pytest.param(SPDX_PREDICATE, id="spdx"),
    ],
)
def test_any_missing_attestation_refuses_the_release(tmp_path, predicate) -> None:
    result = _run_gate(tmp_path, STUB_MODE="missing", STUB_FAIL_PREDICATE=predicate)
    assert result.returncode != 0
    assert "::error::MISSING" in result.stdout
    assert predicate in result.stdout
    assert "refusing to create" in result.stdout
    # The operator is told how to recover, not just that it failed.
    assert "backfill" in result.stdout


def test_an_unverifiable_attestation_is_not_treated_as_missing(tmp_path) -> None:
    """Could-not-look and nothing-to-find both block, but they are different verdicts."""
    result = _run_gate(tmp_path, STUB_MODE="unreachable", STUB_FAIL_PREDICATE=CYCLONEDX_PREDICATE)
    assert result.returncode != 0
    assert "::error::NOT OBSERVABLE" in result.stdout
    assert "::error::MISSING" not in result.stdout


def test_an_unreadable_manifest_blocks_rather_than_passing(tmp_path) -> None:
    result = _run_gate(tmp_path, STUB_INDEX="", STUB_CHILDREN="")
    assert result.returncode != 0
    assert "NOT OBSERVABLE" in result.stdout
    assert "gh" not in result.stdout.replace("ghcr.io", "")


def test_one_healthy_child_does_not_excuse_a_broken_sibling(tmp_path) -> None:
    """Every child is checked; the loop must not stop at the first success."""
    result = _run_gate(tmp_path, STUB_MODE="missing", STUB_FAIL_PREDICATE=SPDX_PREDICATE)
    assert result.returncode != 0
    assert result.stdout.count("::error::MISSING") == 2, result.stdout
