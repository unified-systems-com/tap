"""scripts/codespace-env: a prebuilt Codespace learns its name from the identity file (tap#1308)."""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _derive(tmp_path: Path, identity: str | None, wait: int | str = 3, **env: str) -> subprocess.CompletedProcess[str]:
    # A copy of the script, so the signing key it generates lands in the throwaway tree, not the repository.
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True, exist_ok=True)
    for name in ("codespace-env", "py"):
        shutil.copy2(REPO / "scripts" / name, tree / "scripts" / name)
    base = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "CODESPACES": "true",
        "CODESPACE_NAME": "",
        "GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN": "app.github.dev",
        "GITHUB_API_URL": "http://127.0.0.1:9",  # no network: the owner stays unresolved, which is allowed
        "TAP_CODESPACE_NAME_WAIT": str(wait),
    }
    if identity is not None:
        base["TAP_CODESPACE_IDENTITY"] = identity
    return subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — running the committed script IS the test; argv list of fixed strings, no shell  # nosec B603  # noqa: S603
        ["bash", str(tree / "scripts" / "codespace-env"), "--output", str(tmp_path / "out.env"), "--force"],
        env={**base, **env}, capture_output=True, text=True, check=False, timeout=60,
    )


def _full(name: str, user: str = "visitor") -> str:
    return f"CODESPACE_NAME={name}\nGITHUB_CODESPACES_PORT_FORWARDING_DOMAIN=app.github.dev\nGITHUB_USER={user}\n"


def _hosts(tmp_path: Path) -> str:
    for line in (tmp_path / "out.env").read_text().splitlines():
        if line.startswith("ALLOWED_HOSTS="):
            return line.removeprefix("ALLOWED_HOSTS=").split(",")[0]
    raise AssertionError("no ALLOWED_HOSTS line")


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_the_identity_file_names_a_codespace_the_environment_does_not(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text('CODESPACE_NAME="spike-abc"\nGITHUB_CODESPACES_PORT_FORWARDING_DOMAIN=app.github.dev\nGITHUB_USER=visitor\n')
    proc = _derive(tmp_path, str(ident))
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "spike-abc-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_the_file_wins_over_a_stale_environment(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text(_full("current-one"))
    proc = _derive(tmp_path, str(ident), CODESPACE_NAME="stale-one")
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "current-one-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_name_written_after_start_is_waited_for(tmp_path: Path) -> None:
    """The dev container's postStartCommand writes the file after web has started."""
    ident = tmp_path / "identity.env"
    ident.write_text("")

    def late() -> None:
        time.sleep(1.5)
        ident.write_text(_full("late-one"))

    writer = threading.Thread(target=late)
    writer.start()
    proc = _derive(tmp_path, str(ident), wait=20)
    writer.join()
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "late-one-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_half_written_file_is_waited_out_never_mixed_with_the_environment(tmp_path: Path) -> None:
    """A name without its user must not borrow the prebuild's user: GITHUB_USER decides the owner."""
    ident = tmp_path / "identity.env"
    ident.write_text("CODESPACE_NAME=current\n")

    def finish() -> None:
        time.sleep(1.5)
        ident.write_text(_full("current", user="current-user"))

    writer = threading.Thread(target=finish)
    writer.start()
    proc = _derive(tmp_path, str(ident), wait=20, GITHUB_USER="stale-user")
    writer.join()
    assert proc.returncode == 0, proc.stderr
    assert "current (opened by current-user)" in proc.stderr
    assert "stale-user" not in proc.stderr


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_an_incomplete_file_refuses_rather_than_fall_back(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text("CODESPACE_NAME=current\nGITHUB_CODESPACES_PORT_FORWARDING_DOMAIN=app.github.dev\n")
    proc = _derive(tmp_path, str(ident), wait=1, CODESPACE_NAME="from-env", GITHUB_USER="stale-user")
    assert proc.returncode != 0
    assert not (tmp_path / "out.env").exists()


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_prebuild_with_no_name_still_refuses(tmp_path: Path) -> None:
    """Nothing writes the file during a prebuild, so derivation fails closed and initializes nothing."""
    ident = tmp_path / "identity.env"
    ident.write_text("")
    proc = _derive(tmp_path, str(ident), wait=1)
    assert proc.returncode != 0
    assert "held no complete identity" in proc.stderr
    assert not (tmp_path / "out.env").exists()


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_malformed_name_is_refused_not_run(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    marker = tmp_path / "pwned"
    ident.write_text(f"CODESPACE_NAME=x$(touch {marker})\n")
    proc = _derive(tmp_path, str(ident), wait=1)
    assert proc.returncode != 0
    assert not marker.exists()


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_hostile_wait_runs_nothing(tmp_path: Path) -> None:
    """The wait reaches bash arithmetic, where an array subscript would run a command."""
    ident = tmp_path / "identity.env"
    ident.write_text(_full("named"))
    marker = tmp_path / "pwned"
    proc = _derive(tmp_path, str(ident), wait=f"x[$(touch {marker})]")
    assert not marker.exists()
    assert proc.returncode == 0, proc.stderr
    assert "must be 0-900 seconds" in proc.stderr


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_wait_with_leading_zeros_is_decimal(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text(_full("zeros"))
    proc = _derive(tmp_path, str(ident), wait="008")
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "zeros-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-5")
def test_the_generated_file_runs_nothing_from_its_own_comments(tmp_path: Path) -> None:
    """The heredoc is unquoted, so a backtick span in its comments was a command substitution."""
    proc = _derive(tmp_path, None, CODESPACE_NAME="from-env")
    assert proc.returncode == 0, proc.stderr
    assert "command not found" not in proc.stderr and "syntax error" not in proc.stderr
    assert "'gh codespace ports forward'" in (tmp_path / "out.env").read_text()


@pytest.mark.spec("req-tap-serving-codespace-5")
def test_the_template_holds_no_command_syntax() -> None:
    """The heredoc must stay unquoted to interpolate values, so nothing in it may be a command."""
    text = (REPO / "scripts" / "codespace-env").read_text()
    start = text.index('cat > "$output" <<ENVFILE')
    template = text[start : text.index("\nENVFILE\n", start)]
    assert "`" not in template
    assert "$(" not in template
