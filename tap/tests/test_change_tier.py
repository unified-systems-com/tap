"""`scripts/change-tier` classifies a diff into docs | specs | full | boot, fail-closed.

Spec: specs/spec-dev-validation.md (req-dev-validation-product-line-lanes-7, req-dev-validation-bom-lane-2).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "change-tier"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="change-tier shells out to git")


def _git(cwd: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "HOME": str(cwd),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def _repo_with_base(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "base")
    return repo


def _tier_after(tmp_path: Path, changes: dict[str, str]) -> str:
    repo = _repo_with_base(tmp_path)
    for rel, text in changes.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(repo, "add", rel)
    if changes:
        _git(repo, "commit", "-q", "-m", "change")
    # argv[0] is the literal interpreter (the static-string rule Codacy/Bandit apply to subprocess); the
    # script path is the repo's own file, not input.
    out = subprocess.run(["bash", str(SCRIPT), "base"], cwd=repo, check=True, capture_output=True, text=True).stdout
    return out.strip()


def test_docs_only_is_docs(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"docs/x.md": "x\n"}) == "docs"


def test_specs_is_specs(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"specs/spec-x.md": "x\n", "docs/y.md": "y\n"}) == "specs"


def test_code_is_full(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"tap/x.py": "x = 1\n"}) == "full"


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_empty_diff_is_full(tmp_path: Path) -> None:
    """Fail-closed: nothing changed reads as the whole battery, never as docs."""
    assert _tier_after(tmp_path, {}) == "full"


@pytest.mark.spec("req-dev-validation-bom-lane-2")
@pytest.mark.spec("req-dev-validation-product-line-lanes-9")
def test_boot_record_is_boot(tmp_path: Path) -> None:
    """A core boot record in the diff is the BOM moving: `boot`, on top of full."""
    assert _tier_after(tmp_path, {"boot/test_all.boot.json": "{}\n"}) == "boot"


@pytest.mark.spec("req-dev-validation-product-line-lanes-9")
def test_in_package_boot_record_is_boot(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"tap_plugins/tests/fixtures/x/tap_plugin/x/boot/ci.boot.json": "{}\n"}) == "boot"


@pytest.mark.spec("req-dev-validation-bom-lane-2")
def test_boot_outranks_docs_and_code(tmp_path: Path) -> None:
    assert (
        _tier_after(tmp_path, {"docs/x.md": "x\n", "boot/core_ci.boot.json": "{}\n", "tap/x.py": "x = 1\n"}) == "boot"
    )


# --- The BOM inputs are declared once; the classifier derives from them (tap#379) ---------------


@pytest.mark.spec("req-dev-validation-product-line-lanes-9")
@pytest.mark.parametrize(
    "path",
    [
        "uv.lock",
        "pyproject.toml",
        "docker/Dockerfile",
        "docker/entrypoint.sh",
        "docker/build-openssl-fips.sh",
        "docker/openssl-release-keys.asc",
        "docker-compose.ci.yml",
        ".env",
        "tap/preboot.py",
        "tap_boot/schemas/boot.schema.json",
    ],
)
def test_every_bom_input_is_boot(tmp_path: Path, path: str) -> None:
    """A lockfile-only PR (PR# 373) was `full`, not `boot`: the two globs stood proxy for the BOM.
    Every declared input now classifies `boot` through tap.bom_inputs."""
    assert _tier_after(tmp_path, {path: "x\n"}) == "boot"


@pytest.mark.spec("req-dev-validation-product-line-lanes-9")
def test_change_under_a_records_editable_path_is_boot(tmp_path: Path) -> None:
    """A record's editable/path source is unpinned: a change under it changes what boots (F3)."""
    record = '{"install": {"plugins": [{"slug": "s", "enabled": true, "source": {"type": "editable", "path": "fixtures/s"}}]}}\n'
    repo = _repo_with_base(tmp_path)
    (repo / "boot").mkdir()
    (repo / "boot" / "x.boot.json").write_text(record)
    _git(repo, "add", "boot/x.boot.json")
    _git(repo, "commit", "-q", "-m", "record")
    _git(repo, "branch", "-f", "base")
    src = repo / "fixtures" / "s" / "tap_plugin" / "s"
    src.mkdir(parents=True)
    (src / "models.py").write_text("x = 1\n")
    _git(repo, "add", "fixtures/s/tap_plugin/s/models.py")
    _git(repo, "commit", "-q", "-m", "editable change")
    out = subprocess.run(["bash", str(SCRIPT), "base"], cwd=repo, check=True, capture_output=True, text=True).stdout
    assert out.strip() == "boot"
