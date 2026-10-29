"""Container-engine selection for the dev scripts (req-dev-multisession-container-engine).

`scripts/lib/container-engine.sh` is sourced by spawn, dc, despawn, prune-images and gate-lean, and
nothing here talks to a real daemon: each case puts fake `docker` and `podman` executables on PATH,
sources the real helper in `bash`, and reads back the engine it chose. The fakes answer exactly the
calls the helper makes (`docker info`, `docker ps`, `podman machine inspect`, `podman info`).
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "container-engine.sh"

# `docker info` succeeds on the default socket when FAKE_DOCKER_UP=1, and on the Podman socket when
# DOCKER_HOST equals FAKE_PODMAN_URL and FAKE_PODMAN_UP=1. `docker ps` prints an id when the engine it
# was pointed at holds the project (FAKE_DOCKER_HAS / FAKE_PODMAN_HAS).
FAKE_DOCKER = """#!/bin/sh
case "$1" in
  info)
    if [ -n "$DOCKER_HOST" ]; then
      [ "$DOCKER_HOST" = "$FAKE_PODMAN_URL" ] && [ "$FAKE_PODMAN_UP" = 1 ] && exit 0
      exit 1
    fi
    [ "$FAKE_DOCKER_UP" = 1 ] && exit 0
    exit 1 ;;
  ps)
    if [ -n "$DOCKER_HOST" ]; then
      [ "$FAKE_PODMAN_HAS" = 1 ] && echo abc123
    else
      [ "$FAKE_DOCKER_HAS" = 1 ] && echo def456
    fi
    exit 0 ;;
esac
exit 0
"""

FAKE_PODMAN = """#!/bin/sh
case "$1 $2" in
  "machine inspect") [ -n "$FAKE_MACHINE_SOCK" ] && echo "$FAKE_MACHINE_SOCK"; [ -n "$FAKE_MACHINE_SOCK" ] || exit 125; exit 0 ;;
esac
case "$1" in
  info) echo "$FAKE_LINUX_SOCK"; exit 0 ;;
esac
exit 0
"""

BASE_PATH = "/usr/bin:/bin"


@pytest.fixture
def sandbox() -> Iterator[Path]:
    # AF_UNIX paths are capped near 104 bytes, and pytest's tmp_path can exceed that.
    d = Path(tempfile.mkdtemp(dir="/tmp", prefix="tapeng"))
    (d / "bin").mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _install(sandbox: Path, name: str, body: str) -> None:
    f = sandbox / "bin" / name
    f.write_text(body, encoding="utf-8")
    f.chmod(0o755)


def _socket(path: Path) -> Path:
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.listen(1)
    _KEEP.append(s)
    return path


_KEEP: list[socket.socket] = []


@pytest.fixture(autouse=True)
def _close_sockets() -> Iterator[None]:
    yield
    while _KEEP:
        _KEEP.pop().close()


def _run(sandbox: Path, body: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Source the helper in a clean environment and run `body`, then print the verdict."""
    script = f'source "{HELPER}"\n{body}\necho "ENGINE=$TAP_ENGINE"\necho "HOST=${{DOCKER_HOST:-}}"\n'
    return subprocess.run(
        ["bash", "-c", script],
        env={"PATH": f"{sandbox / 'bin'}:{BASE_PATH}", "HOME": str(sandbox), **env},
        capture_output=True,
        text=True,
        check=False,
        cwd=sandbox,
    )


def _verdict(run: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    lines = dict(line.split("=", 1) for line in run.stdout.splitlines() if "=" in line)
    return lines["ENGINE"], lines["HOST"]


def _podman_machine(sandbox: Path) -> str:
    """A working Podman machine: a real socket at the path `machine inspect` reports."""
    _install(sandbox, "docker", FAKE_DOCKER)
    _install(sandbox, "podman", FAKE_PODMAN)
    return str(_socket(sandbox / "p.sock"))


@pytest.mark.spec("req-dev-multisession-container-engine-1")
def test_an_explicit_docker_host_is_never_overridden(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select", DOCKER_HOST="unix:///var/run/mine.sock", FAKE_MACHINE_SOCK=sock)
    assert _verdict(run) == ("explicit", "unix:///var/run/mine.sock")


@pytest.mark.spec("req-dev-multisession-container-engine-1")
def test_an_explicit_docker_context_is_never_overridden(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select", DOCKER_CONTEXT="desktop-linux", FAKE_MACHINE_SOCK=sock)
    assert _verdict(run) == ("explicit", "")


@pytest.mark.spec("req-dev-multisession-container-engine-2")
def test_docker_wins_when_it_answers_even_if_podman_is_also_up(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(
        sandbox, "tap_engine_select", FAKE_DOCKER_UP="1", FAKE_MACHINE_SOCK=sock, FAKE_PODMAN_URL=f"unix://{sock}", FAKE_PODMAN_UP="1"
    )
    assert _verdict(run) == ("docker", "")


@pytest.mark.spec("req-dev-multisession-container-engine-3")
def test_podman_machine_socket_is_used_when_docker_is_down(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select", FAKE_MACHINE_SOCK=sock, FAKE_PODMAN_URL=f"unix://{sock}", FAKE_PODMAN_UP="1")
    assert _verdict(run) == ("podman", f"unix://{sock}")
    assert "using Podman" in run.stderr


@pytest.mark.spec("req-dev-multisession-container-engine-3")
def test_linux_podman_socket_is_found_when_there_is_no_machine(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select", FAKE_LINUX_SOCK=f"unix://{sock}", FAKE_PODMAN_URL=f"unix://{sock}", FAKE_PODMAN_UP="1")
    assert _verdict(run) == ("podman", f"unix://{sock}")


@pytest.mark.spec("req-dev-multisession-container-engine-3")
def test_a_reported_path_that_is_not_a_socket_is_not_used(sandbox: Path) -> None:
    _podman_machine(sandbox)
    ghost = sandbox / "gone.sock"  # a machine that is stopped reports its path; nothing listens there
    run = _run(sandbox, "tap_engine_select", FAKE_MACHINE_SOCK=str(ghost), FAKE_PODMAN_URL=f"unix://{ghost}", FAKE_PODMAN_UP="1")
    assert _verdict(run) == ("none", "")


@pytest.mark.spec("req-dev-multisession-container-engine-3")
def test_a_socket_that_does_not_answer_is_not_used(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select", FAKE_MACHINE_SOCK=sock, FAKE_PODMAN_URL=f"unix://{sock}", FAKE_PODMAN_UP="0")
    assert _verdict(run) == ("none", "")


@pytest.mark.spec("req-dev-multisession-container-engine-3")
def test_no_podman_binary_leaves_the_failure_to_the_caller(sandbox: Path) -> None:
    _install(sandbox, "docker", FAKE_DOCKER)
    run = _run(sandbox, "tap_engine_select")
    assert _verdict(run) == ("none", "")
    assert run.returncode == 0


def _worktree(sandbox: Path, env_local: str) -> Path:
    wt = sandbox / "wt"
    wt.mkdir()
    (wt / ".env.local").write_text(env_local, encoding="utf-8")
    return wt


@pytest.mark.spec("req-dev-multisession-container-engine-4")
def test_a_session_recorded_on_podman_stays_on_podman_even_when_docker_is_up(sandbox: Path) -> None:
    _podman_machine(sandbox)
    wt = _worktree(sandbox, "WEB_PORT=8480\nDOCKER_HOST=unix:///tmp/recorded.sock\n")
    run = _run(sandbox, f'tap_engine_select "{wt}"', FAKE_DOCKER_UP="1")
    assert _verdict(run) == ("sticky", "unix:///tmp/recorded.sock")


@pytest.mark.spec("req-dev-multisession-container-engine-4")
@pytest.mark.parametrize(
    "value",
    [
        "tcp://10.0.0.1:2375",
        "unix:///tmp/x.sock; touch /tmp/pwned",
        "unix:///tmp/$(id).sock",
        "unix://relative.sock",
        "unix:///tmp/has space.sock",
    ],
)
def test_a_recorded_host_that_is_not_a_plain_socket_path_is_ignored(sandbox: Path, value: str) -> None:
    _podman_machine(sandbox)
    wt = _worktree(sandbox, f"DOCKER_HOST={value}\n")
    run = _run(sandbox, f'tap_engine_select "{wt}"', FAKE_DOCKER_UP="1")
    assert _verdict(run) == ("docker", "")
    assert "ignoring DOCKER_HOST" in run.stderr
    assert not Path("/tmp/pwned").exists()


@pytest.mark.spec("req-dev-multisession-container-engine-5")
def test_a_podman_choice_is_recorded_once_in_env_local(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    wt = _worktree(sandbox, "WEB_PORT=8480\n")
    env = {"FAKE_MACHINE_SOCK": sock, "FAKE_PODMAN_URL": f"unix://{sock}", "FAKE_PODMAN_UP": "1"}
    body = f'tap_engine_select; tap_engine_persist "{wt}/.env.local"; tap_engine_persist "{wt}/.env.local"'
    _run(sandbox, body, **env)
    lines = (wt / ".env.local").read_text(encoding="utf-8").splitlines()
    assert lines.count(f"DOCKER_HOST=unix://{sock}") == 1
    assert "WEB_PORT=8480" in lines


@pytest.mark.spec("req-dev-multisession-container-engine-5")
def test_a_docker_choice_leaves_env_local_alone(sandbox: Path) -> None:
    _podman_machine(sandbox)
    wt = _worktree(sandbox, "WEB_PORT=8480\n")
    _run(sandbox, f'tap_engine_select; tap_engine_persist "{wt}/.env.local"', FAKE_DOCKER_UP="1")
    assert (wt / ".env.local").read_text(encoding="utf-8") == "WEB_PORT=8480\n"


@pytest.mark.spec("req-dev-multisession-container-engine-6")
@pytest.mark.spec("req-dev-multisession-teardown-cleanup-7")
def test_despawn_on_docker_warns_when_the_project_is_on_podman(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(
        sandbox,
        "tap_engine_select; tap_engine_warn_other tap_probe",
        FAKE_DOCKER_UP="1",
        FAKE_MACHINE_SOCK=sock,
        FAKE_PODMAN_URL=f"unix://{sock}",
        FAKE_PODMAN_UP="1",
        FAKE_PODMAN_HAS="1",
    )
    assert "also has containers on Podman" in run.stderr
    assert f"DOCKER_HOST=unix://{sock} docker compose -p tap_probe down -v --remove-orphans" in run.stderr


@pytest.mark.spec("req-dev-multisession-container-engine-6")
@pytest.mark.spec("req-dev-multisession-teardown-cleanup-7")
def test_despawn_on_podman_warns_when_the_project_is_on_docker(sandbox: Path) -> None:
    _podman_machine(sandbox)
    wt = _worktree(sandbox, "DOCKER_HOST=unix:///tmp/recorded.sock\n")
    run = _run(sandbox, f'tap_engine_select "{wt}"; tap_engine_warn_other tap_probe', FAKE_DOCKER_HAS="1")
    assert "also has containers on the default Docker daemon" in run.stderr
    assert "env -u DOCKER_HOST docker compose -p tap_probe down -v --remove-orphans" in run.stderr


@pytest.mark.spec("req-dev-multisession-container-engine-6")
def test_no_warning_when_the_other_engine_does_not_hold_the_project(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(
        sandbox,
        "tap_engine_select; tap_engine_warn_other tap_probe",
        FAKE_DOCKER_UP="1",
        FAKE_MACHINE_SOCK=sock,
        FAKE_PODMAN_URL=f"unix://{sock}",
        FAKE_PODMAN_UP="1",
    )
    assert "WARNING" not in run.stderr


# --- the wiring: the helper is only worth anything if every script that talks to a daemon uses it ---

SCRIPTS = ["spawn-session.sh", "dc", "despawn-session.sh", "prune-images", "gate-lean"]


@pytest.mark.spec("req-dev-multisession-container-engine-7")
@pytest.mark.parametrize("name", SCRIPTS)
def test_every_daemon_script_sources_the_helper_and_selects(name: str) -> None:
    text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
    assert "lib/container-engine.sh" in text
    assert "tap_engine_select" in text


@pytest.mark.spec("req-dev-multisession-container-engine-7")
def test_spawn_selects_on_both_roads_and_records_the_choice() -> None:
    text = (ROOT / "scripts" / "spawn-session.sh").read_text(encoding="utf-8")
    assert text.count("tap_engine_select") >= 2  # Step 0.1 (fresh spawn) and the --promote branch
    assert 'tap_engine_persist "$WORKTREE/.env.local"' in text


@pytest.mark.spec("req-dev-multisession-container-engine-7")
@pytest.mark.spec("req-dev-multisession-teardown-cleanup-7")
def test_despawn_selects_from_the_session_worktree_before_touching_the_stack() -> None:
    text = (ROOT / "scripts" / "despawn-session.sh").read_text(encoding="utf-8")
    assert 'tap_engine_select "$WORKTREE"' in text
    assert text.index('tap_engine_select "$WORKTREE"') < text.index("tap_engine_warn_other") < text.index('bold "Stopping docker stack"')


@pytest.mark.spec("req-dev-multisession-container-engine-8")
def test_prune_images_does_not_ask_podman_to_prune_a_buildx_builder() -> None:
    text = (ROOT / "scripts" / "prune-images").read_text(encoding="utf-8")
    assert "podman|sticky)" in text
    assert text.index("podman|sticky)") < text.index("dk builder prune")


@pytest.mark.spec("req-dev-multisession-container-engine-8")
def test_spawn_names_the_podman_remedy_when_no_engine_answers() -> None:
    text = (ROOT / "scripts" / "spawn-session.sh").read_text(encoding="utf-8")
    assert "Neither Docker nor Podman is responding" in text
    assert "podman machine start" in text
