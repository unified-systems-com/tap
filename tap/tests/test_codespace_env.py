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


def _derive(tmp_path: Path, identity: str | None, wait: int = 3, **env: str) -> subprocess.CompletedProcess[str]:
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


def _hosts(tmp_path: Path) -> str:
    for line in (tmp_path / "out.env").read_text().splitlines():
        if line.startswith("ALLOWED_HOSTS="):
            return line.removeprefix("ALLOWED_HOSTS=").split(",")[0]
    raise AssertionError("no ALLOWED_HOSTS line")


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_the_identity_file_names_a_codespace_the_environment_does_not(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text('CODESPACE_NAME="spike-abc"\nGITHUB_CODESPACES_PORT_FORWARDING_DOMAIN=app.github.dev\n')
    proc = _derive(tmp_path, str(ident))
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "spike-abc-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_the_file_wins_over_a_stale_environment(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    ident.write_text("CODESPACE_NAME=current-one\n")
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
        ident.write_text("CODESPACE_NAME=late-one\n")

    writer = threading.Thread(target=late)
    writer.start()
    proc = _derive(tmp_path, str(ident), wait=20)
    writer.join()
    assert proc.returncode == 0, proc.stderr
    assert _hosts(tmp_path) == "late-one-8000.app.github.dev"


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_prebuild_with_no_name_still_refuses(tmp_path: Path) -> None:
    """Nothing writes the file during a prebuild, so derivation fails closed and initializes nothing."""
    ident = tmp_path / "identity.env"
    ident.write_text("")
    proc = _derive(tmp_path, str(ident), wait=1)
    assert proc.returncode != 0
    assert "named no Codespace" in proc.stderr
    assert not (tmp_path / "out.env").exists()


@pytest.mark.spec("req-tap-serving-codespace-9")
def test_a_malformed_name_is_refused_not_run(tmp_path: Path) -> None:
    ident = tmp_path / "identity.env"
    marker = tmp_path / "pwned"
    ident.write_text(f"CODESPACE_NAME=x$(touch {marker})\n")
    proc = _derive(tmp_path, str(ident), wait=1)
    assert proc.returncode != 0
    assert not marker.exists()


@pytest.mark.spec("req-tap-serving-codespace-5")
def test_the_generated_file_runs_nothing_from_its_own_comments(tmp_path: Path) -> None:
    """The heredoc is unquoted, so a backtick span in its comments was a command substitution."""
    proc = _derive(tmp_path, None, CODESPACE_NAME="from-env")
    assert proc.returncode == 0, proc.stderr
    assert "command not found" not in proc.stderr and "syntax error" not in proc.stderr
    assert "'gh codespace ports forward'" in (tmp_path / "out.env").read_text()
