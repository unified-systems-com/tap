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
