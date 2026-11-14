"""The entrypoint starts the job workers before the Codespace boot runs.

In every standup but a Codespace, `manage.py boot` is run from outside once the container is
serving, so the Steady Queue workers already exist when a `fire-collector` step enqueues work.
The Codespace branch of the entrypoint is the one place the entrypoint runs boot itself; with
the supervisor started after it, the collector preflight waited its full 60 s for a worker that
did not exist and the step was skipped. The property is an ORDER in a shell script, so the test
reads the order from the source.

Spec: `specs/spec-tap-serving.md` req-tap-serving-codespace-8.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh"


def _lines() -> list[str]:
    return ENTRYPOINT.read_text(encoding="utf-8").splitlines()


def _first(prefix: str) -> int:
    """Index of the first non-comment line that starts with `prefix`."""
    for i, line in enumerate(_lines()):
        if line.startswith(prefix):
            return i
    raise AssertionError(f"docker/entrypoint.sh has no line starting {prefix!r}")


@pytest.mark.spec("req-tap-serving-codespace-8")
def test_the_workers_start_before_the_codespace_boot_and_the_server_after_it() -> None:
    supervisor = _first("uv run python manage.py steady_queue &")
    codespace_boot = _first('if [ "${CODESPACES:-}" = "true" ]; then')
    gunicorn = _first('echo "==> Starting gunicorn')
    assert supervisor < codespace_boot < gunicorn


@pytest.mark.spec("req-tap-serving-codespace-8")
def test_the_boot_the_codespace_runs_is_the_one_after_the_supervisor() -> None:
    lines = _lines()
    supervisor = _first("uv run python manage.py steady_queue &")
    boots = [i for i, line in enumerate(lines) if line.strip() == "if uv run python manage.py boot; then"]
    assert boots, "the Codespace branch no longer runs manage.py boot from the entrypoint"
    assert all(supervisor < i for i in boots)
