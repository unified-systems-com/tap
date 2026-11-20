"""Where schema-from-models is switched on, and where the real migrations still run (tap#1258).

On in CI and dev stacks, off in a real install, replayed nightly: each of those is a line in a
file that is easy to lose in an edit, so each is pinned here against the requirement it serves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ENV = "TAP_BOOT_INSTALL__SCHEMA_FROM_MODELS"


def _code_lines(path: str) -> list[str]:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    return [line for line in lines if not line.lstrip().startswith("#")]


def _web_env(compose: str) -> dict[str, Any]:
    environment: dict[str, Any] = yaml.safe_load((ROOT / compose).read_text(encoding="utf-8"))["services"]["web"][
        "environment"
    ]
    return environment


@pytest.mark.spec("req-boot-schema-from-models-6")
def test_ci_defaults_on_and_the_dev_compose_passes_it_through_empty() -> None:
    assert _web_env("docker-compose.ci.yml")[ENV] == "${" + ENV + ":-true}"
    # Empty in the base file: an install that sets nothing keeps its real migrations.
    assert _web_env("docker-compose.yml")[ENV] == "${" + ENV + ":-}"


@pytest.mark.spec("req-boot-schema-from-models-6")
def test_a_dev_spawn_writes_it_on() -> None:
    lines = _code_lines("scripts/spawn-session.sh")
    start = lines.index("cat > .env.local <<EOF")
    block = lines[start : lines.index("EOF", start)]
    assert f"{ENV}=true" in block


@pytest.mark.spec("req-boot-schema-from-models-2")
def test_the_entrypoint_builds_after_createcachetable_and_before_the_workers() -> None:
    lines = _code_lines("docker/entrypoint.sh")
    text = "\n".join(lines)

    def first(pattern: str) -> int:
        return next(i for i, line in enumerate(lines) if re.search(pattern, line))

    resolve = first(r"python -m tap\.preboot --profile \"\$BOOT_PROFILE_ID\" --schema-from-models")
    assert first(r"manage\.py createcachetable") < resolve < first(r'manage\.py "\$MIGRATE_COMMAND" --noinput')
    assert first(r'manage\.py "\$MIGRATE_COMMAND"') < first(r"manage\.py steady_queue &")
    assert 'MIGRATE_COMMAND="migrate_from_models"' in text and 'MIGRATE_COMMAND="migrate"' in text
    assert "manage.py migrate --noinput" not in text, "a second, unconditional migrate would undo the choice"


@pytest.mark.spec("req-boot-schema-from-models-4")
def test_the_test_template_is_built_from_the_models() -> None:
    text = "\n".join(_code_lines("scripts/build-test-template"))
    assert "BUILD_COMMAND=migrate_from_models" in text
    assert 'manage.py "$BUILD_COMMAND" --noinput' in text


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_one_nightly_job_replays_the_real_migrations_and_proves_parity() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/product-lines.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["migrations"]
    assert job["if"] == (
        "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
        " || needs.setup.outputs.migrations_changed == 'true'"
    )
    assert job["env"][ENV] == "false" and job["env"]["TAP_BOOT_PROFILE"] == "core_ci"
    runs = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "python -m tap.schema_parity" in runs
    gate = workflow["jobs"]["gate"]
    assert "migrations" in gate["needs"]
    verdict = "\n".join(str(step.get("run", "")) for step in gate["steps"])
    arm = verdict[verdict.index('case "$R_MIGRATIONS" in') :]
    arm = arm[: arm.index("*) die \"migrations finished")]
    assert "schedule | workflow_dispatch) die" in arm, "a skip on the nightly must not read green"
    assert 'if [ "$MIGRATIONS_CHANGED" = "true" ]; then die' in arm, "a skip on a migration diff must not read green"
    pick = "\n".join(str(step.get("run", "")) for step in workflow["jobs"]["setup"]["steps"])
    assert "migrations_changed=" in pick and "migrations/" in pick
