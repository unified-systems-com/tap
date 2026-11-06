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
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — argv is a literal bash -c; the script string is built from this test's own constants, never from input  # nosec B603  # noqa: S603
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


# --- tap#1139: bounded probes without GNU timeout; despawn stops on an unreachable engine -------------

_NO_TIMEOUT_TOOLS = ("bash", "sh", "sleep", "mktemp", "cat", "rm", "head", "sed", "grep", "env", "dirname")


def _path_without_timeout(sandbox: Path) -> str:
    """A PATH holding the sandbox fakes plus only the tools the helper needs: no `timeout`, no `gtimeout`."""
    tools = sandbox / "tools"
    tools.mkdir(exist_ok=True)
    for name in _NO_TIMEOUT_TOOLS:
        found = shutil.which(name)
        assert found, name
        if not (tools / name).exists():
            (tools / name).symlink_to(found)
    return f"{sandbox / 'bin'}:{tools}"


def _run_bare(sandbox: Path, body: str, timeout: int, **env: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash
    script = f'source "{HELPER}"\n{body}\necho "ENGINE=$TAP_ENGINE"\necho "HOST=${{DOCKER_HOST:-}}"\n'
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — literal bash -c over a script built from this test's own constants  # nosec B603  # noqa: S603
        [bash, "-c", script],
        env={"PATH": _path_without_timeout(sandbox), "HOME": str(sandbox), **env},
        capture_output=True,
        text=True,
        check=False,
        cwd=sandbox,
        timeout=timeout,
    )


@pytest.mark.spec("req-dev-multisession-container-engine-9")
def test_a_wedged_docker_is_bounded_on_a_host_with_no_gnu_timeout(sandbox: Path) -> None:
    """The fake `docker` never returns. Without `timeout`/`gtimeout` the old helper waited forever."""
    _install(sandbox, "docker", "#!/bin/sh\nsleep 60\n")
    run = _run_bare(sandbox, "tap_engine_select", timeout=40)
    assert _verdict(run) == ("none", "")


@pytest.mark.spec("req-dev-multisession-container-engine-9")
def test_the_bash_fallback_still_returns_the_commands_output_and_status(sandbox: Path) -> None:
    _install(sandbox, "docker", FAKE_DOCKER)
    up = _run_bare(sandbox, "tap_engine_select", timeout=40, FAKE_DOCKER_UP="1")
    assert _verdict(up) == ("docker", "")
    out = _run_bare(
        sandbox,
        "got=\"$(_tap_engine_t 5 sh -c 'echo hi; exit 3')\"; echo \"x=$got rc=$?\"; "
        "_tap_engine_t 1 sleep 30; echo \"slow rc=$?\"",
        timeout=40,
    )
    assert "x=hi rc=3" in out.stdout
    assert "slow rc=124" in out.stdout


@pytest.mark.spec("req-dev-multisession-teardown-cleanup-8")
def test_reachable_follows_the_selected_engine_not_the_default_one(sandbox: Path) -> None:
    _install(sandbox, "docker", FAKE_DOCKER)
    wt = sandbox / "wt"
    wt.mkdir()
    (wt / ".env.local").write_text("DOCKER_HOST=unix:///tmp/tapeng-dead.sock\n", encoding="utf-8")
    # Docker itself is up, but the session lives on a Podman socket that does not answer.
    run = _run(sandbox, f'tap_engine_select "{wt}"; tap_engine_reachable && echo REACHABLE=yes || echo REACHABLE=no',
               FAKE_DOCKER_UP="1")
    assert "REACHABLE=no" in run.stdout
    assert _verdict(run)[0] == "sticky"


def _despawn(sandbox: Path, *flags: str, **env: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — argv is the committed script plus fixed flags; no shell  # nosec B603  # noqa: S603
        [bash, str(ROOT / "scripts" / "despawn-session.sh"), "ghost", *flags],
        env={"PATH": f"{sandbox / 'bin'}:{BASE_PATH}", "HOME": str(sandbox), "WORKTREE_BASE": str(sandbox / "base"), **env},
        capture_output=True,
        text=True,
        check=False,
        cwd=sandbox,
        timeout=60,
        input="",
    )


@pytest.fixture
def dead_podman_session(sandbox: Path) -> Path:
    _install(sandbox, "docker", FAKE_DOCKER)
    wt = sandbox / "base" / "ghost"
    wt.mkdir(parents=True)
    (wt / ".env.local").write_text("DOCKER_HOST=unix:///tmp/tapeng-dead.sock\n", encoding="utf-8")
    return wt


@pytest.mark.spec("req-dev-multisession-teardown-cleanup-8")
def test_despawn_refuses_before_removing_anything_when_the_session_engine_is_down(
    sandbox: Path, dead_podman_session: Path
) -> None:
    run = _despawn(sandbox, "--yes", FAKE_DOCKER_UP="1")
    assert run.returncode == 1
    assert "not answering" in run.stderr
    assert "--skip-stack" in run.stderr
    assert dead_podman_session.is_dir(), "the worktree must still be there"
    assert "Stopping docker stack" not in run.stdout


@pytest.mark.spec("req-dev-multisession-teardown-cleanup-8")
def test_skip_stack_goes_past_the_check_and_prints_the_cleanup_command(sandbox: Path, dead_podman_session: Path) -> None:
    # No --yes and an empty stdin: the run stops at the confirm prompt, so nothing is torn down.
    run = _despawn(sandbox, "--skip-stack", FAKE_DOCKER_UP="1")
    assert run.returncode == 0
    assert "Aborted." in run.stdout
    assert "--skip-stack given" in run.stdout
    assert "docker compose -p tap_ghost down -v --remove-orphans" in run.stdout
    assert "not answering" not in run.stderr


@pytest.mark.spec("req-dev-multisession-teardown-cleanup-8")
def test_skip_stack_never_touches_the_stack_volumes_or_networks(sandbox: Path, dead_podman_session: Path) -> None:
    # A logging docker: whatever despawn asks the engine to do is recorded, so "left running" is checked, not assumed.
    _install(sandbox, "docker", '#!/bin/sh\necho "$@" >> "$FAKE_DOCKER_LOG"\n' + FAKE_DOCKER.split("\n", 1)[1])
    log = sandbox / "docker.log"
    run = _despawn(sandbox, "--skip-stack", "--yes", FAKE_DOCKER_UP="1", FAKE_DOCKER_LOG=str(log))
    assert "Skipping stack teardown" in run.stdout, run.stdout + run.stderr
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    for forbidden in ("compose -p", " down", "volume rm", "network rm", "volume ls", "network ls", "rmi"):
        assert forbidden not in calls, calls


@pytest.mark.spec("req-dev-multisession-teardown-cleanup-8")
def test_despawn_checks_the_engine_before_the_stack_is_touched() -> None:
    text = (ROOT / "scripts" / "despawn-session.sh").read_text(encoding="utf-8")
    assert "tap_engine_reachable" in text
    assert text.index("tap_engine_reachable") < text.index("tap_engine_warn_other") < text.index('bold "Stopping docker stack"')


# A host with Podman and NO docker binary. The fake logs its argv so the test can prove that what the
# scripts run as `docker ...` really reaches `podman`.
FAKE_PODMAN_LOGGING = """#!/bin/sh
echo "$@" >> "$FAKE_PODMAN_LOG"
case "$1 $2" in
  "machine inspect") echo "$FAKE_MACHINE_SOCK"; exit 0 ;;
esac
exit 0
"""


@pytest.mark.spec("req-dev-multisession-container-engine-10")
def test_podman_alone_is_enough_and_docker_commands_reach_it(sandbox: Path) -> None:
    _install(sandbox, "podman", FAKE_PODMAN_LOGGING)
    sock = str(_socket(sandbox / "p.sock"))
    log = sandbox / "podman.log"
    body = 'tap_engine_select\ndocker volume ls --filter name=x --format "{{.Name}}"\ndocker compose version\ncommand -v docker'
    run = _run(sandbox, body, FAKE_MACHINE_SOCK=sock, FAKE_PODMAN_LOG=str(log))
    assert _verdict(run) == ("podman", f"unix://{sock}")
    assert run.stdout.splitlines()[0].endswith("scripts/lib/docker-shim/docker")
    calls = log.read_text(encoding="utf-8").splitlines()
    assert 'volume ls --filter name=x --format {{.Name}}' in calls
    assert "compose version" in calls


@pytest.mark.spec("req-dev-multisession-container-engine-10")
def test_a_real_docker_cli_is_never_shadowed_by_the_forwarder(sandbox: Path) -> None:
    sock = _podman_machine(sandbox)
    run = _run(sandbox, "tap_engine_select\ncommand -v docker", FAKE_DOCKER_UP="1", FAKE_MACHINE_SOCK=sock)
    assert _verdict(run) == ("docker", "")
    assert run.stdout.splitlines()[0] == str(sandbox / "bin" / "docker")


@pytest.mark.spec("req-dev-multisession-container-engine-10")
def test_no_docker_and_no_podman_leaves_the_engine_unchosen(sandbox: Path) -> None:
    run = _run(sandbox, "tap_engine_select")
    assert _verdict(run) == ("none", "")


@pytest.mark.spec("req-dev-multisession-container-engine-10")
def test_the_cross_engine_warning_is_silent_when_podman_is_the_only_engine(sandbox: Path) -> None:
    _install(sandbox, "podman", FAKE_PODMAN_LOGGING)
    sock = str(_socket(sandbox / "p.sock"))
    run = _run(sandbox, "tap_engine_select\ntap_engine_warn_other tap_x", FAKE_MACHINE_SOCK=sock, FAKE_PODMAN_LOG=str(sandbox / "l"))
    assert "also has containers" not in run.stderr
