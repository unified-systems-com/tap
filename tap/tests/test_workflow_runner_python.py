"""Unit tests for the workflow runner-interpreter scanner (req-dev-localexec-runner-interpreter).

Synthetic workflow fixtures exercise each predicate both ways. The live repo's workflows are
asserted clean by the harness itself (`test_guards.py` runs every registered guard's
`check()`), so these tests own the scanner logic, not the tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tap.guards.base import REPO_ROOT
from tap.guards.workflow_runner_python import repo_python_calls, scan_workflow

_SHA = "0" * 40
_SETUP = f"""      - uses: actions/setup-python@{_SHA} # v7
        with:
          python-version-file: "pyproject.toml"
"""


def _scan(raw: str, name: str = "wf.yml") -> list[str]:
    return scan_workflow(Path(name), raw, yaml.safe_load(raw))


def _workflow(steps: str, job_extra: str = "") -> str:
    return f"""
name: t
on: push
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
{job_extra}    steps:
      - uses: actions/checkout@{_SHA} # v7
{steps}"""


def _run(script: str) -> str:
    body = "\n".join(f"          {line}" for line in script.splitlines())
    return f"      - name: go\n        run: |\n{body}\n"


# -1: a derived interpreter must precede repo Python --------------------------------


@pytest.mark.spec("req-dev-localexec-runner-interpreter-1")
@pytest.mark.parametrize(
    "script",
    [
        "python3 scripts/sbom/generate.py --image x",
        "python3 tap/bom_inputs.py --classify",
        'python3 "$SCRIPT" --flag',
        "python -m tap.boot_pointer x",
        "python3 -u -W ignore scripts/tool.py",
        "python3 -m pip install --quiet jsonschema==4.23.0",
        "python3 -m build --wheel",
        "python3 -c 'from tap.plugin_identity import slug_for_dist_name'",
        "printf 'x' | python3 -c '\nimport sys\nfrom tap.x import y\n'",
        "out=$(python3 - <<'PY'\nimport tap_grid\nPY\n)",
        "cd sub && \\\n  python3.14 scripts/x.py",
    ],
)
def test_repo_python_without_setup_is_flagged(script):
    violations = _scan(_workflow(_run(script)))
    assert len(violations) == 1 and "runner's system interpreter" in violations[0]


@pytest.mark.spec("req-dev-localexec-runner-interpreter-1")
def test_derived_setup_python_earlier_in_the_job_satisfies():
    assert _scan(_workflow(_SETUP + _run("python3 scripts/sbom/generate.py"))) == []


@pytest.mark.spec("req-dev-localexec-runner-interpreter-1")
def test_setup_python_after_the_step_does_not_count():
    violations = _scan(_workflow(_run("python3 scripts/sbom/generate.py") + _SETUP))
    assert len(violations) == 1


@pytest.mark.spec("req-dev-localexec-runner-interpreter-1")
def test_setup_python_in_another_job_does_not_count():
    raw = f"""
name: t
on: push
permissions:
  contents: read
jobs:
  first:
    runs-on: ubuntu-latest
    steps:
{_SETUP}  second:
    runs-on: ubuntu-latest
    steps:
{_run("python3 scripts/x.py")}"""
    violations = _scan(raw)
    assert len(violations) == 1 and "job `second`" in violations[0]


@pytest.mark.spec("req-dev-localexec-runner-interpreter-1")
def test_shell_python_importing_repo_code_is_flagged():
    step = "      - shell: python\n        run: |\n          from tap.x import y\n"
    assert len(_scan(_workflow(step))) == 1


# -2: the version is derived, never a literal ----------------------------------------


@pytest.mark.spec("req-dev-localexec-runner-interpreter-2")
def test_python_version_literal_is_flagged_and_does_not_satisfy():
    literal = f"""      - uses: actions/setup-python@{_SHA} # v7
        with:
          python-version: "3.14"
"""
    violations = _scan(_workflow(literal + _run("python3 scripts/x.py")))
    assert any("`python-version:` literal" in v for v in violations)
    assert any("runner's system interpreter" in v for v in violations)


@pytest.mark.spec("req-dev-localexec-runner-interpreter-2")
def test_setup_python_without_a_pyproject_version_file_is_flagged():
    bare = f"      - uses: actions/setup-python@{_SHA} # v7\n"
    violations = _scan(_workflow(bare))
    assert len(violations) == 1 and "python-version-file" in violations[0]


@pytest.mark.spec("req-dev-localexec-runner-interpreter-2")
def test_core_checkout_pyproject_satisfies():
    setup = f"""      - uses: actions/setup-python@{_SHA} # v7
        with:
          python-version-file: "_core/pyproject.toml"
"""
    assert _scan(_workflow(setup + _run("python3 _core/scripts/sbom/plugin_release.py"))) == []


# -3: only the host interpreter counts -----------------------------------------------


@pytest.mark.spec("req-dev-localexec-runner-interpreter-3")
@pytest.mark.parametrize(
    "script",
    [
        "uv run --frozen python scripts/sbom/generate.py",
        "uv run --project _tooling --frozen --no-sync \\\n  python -m tap.ci_harness",
        "docker compose --env-file .env exec -T web sh -c 'cd /app && uv run python manage.py x'",
        "docker run --rm img python3 scripts/x.py",
        "scripts/dc exec web python3 -m tap.x",
        'echo "host python3: $(python3 -V 2>&1)"',
        "python3 --version",
        "python3 -m json.tool < f.json",
        "python3 -c 'import json, sys; print(json.load(sys.stdin)[\"x\"])'",
        "n=$(python3 - <<'PY'\nimport re, pathlib\nprint(1)\nPY\n)",
        "# python3 scripts/commented-out.py",
        "ls /usr/bin/python3",
    ],
)
def test_non_host_or_non_repo_python_passes(script):
    assert repo_python_calls(script) == []
    assert _scan(_workflow(_run(script))) == []


@pytest.mark.spec("req-dev-localexec-runner-interpreter-3")
def test_job_container_is_exempt():
    assert _scan(_workflow(_run("python3 scripts/x.py"), job_extra="    container: python:3.14\n")) == []


@pytest.mark.spec("req-dev-localexec-runner-interpreter-3")
def test_guard_allow_annotation_exempts_the_job():
    annotated = "      # guard-allow: req-dev-localexec-runner-interpreter — stdlib-only, parses at the floor\n"
    assert _scan(_workflow(annotated + _run("python3 scripts/x.py"))) == []


# -4: catches the break it exists for ------------------------------------------------


# `publish-images.yml` verbatim at ed79370d, the last main commit before the fix (tap#518 /
# PR 520): its manifest job ran generate.py on the runner's python3. Committed as a fixture,
# not read from git history, so the control runs in shallow CI checkouts and in the container.
_BROKEN_PUBLISH = Path(__file__).parent / "data" / "workflow_runner_python" / "publish-images-pre-tap518.yml"


@pytest.mark.spec("req-dev-localexec-runner-interpreter-4")
def test_flags_the_pre_fix_publish_images_manifest_job():
    violations = _scan(_BROKEN_PUBLISH.read_text(encoding="utf-8"), "publish-images.yml")
    assert any("job `manifest`" in v and "scripts/sbom/generate.py" in v for v in violations), violations


@pytest.mark.spec("req-dev-localexec-runner-interpreter-4")
def test_passes_the_fixed_publish_images():
    path = REPO_ROOT / ".github" / "workflows" / "publish-images.yml"
    assert _scan(path.read_text(encoding="utf-8"), "publish-images.yml") == []
