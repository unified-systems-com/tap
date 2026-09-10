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


def _tier_after_with_shell(tmp_path: Path, changes: dict[str, str], shell: str) -> str:
    """Same classification, run under an explicit shell — bash-only constructs fail QUIETLY."""
    repo = _repo_with_base(tmp_path)
    for rel, text in changes.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(repo, "add", rel)
    if changes:
        _git(repo, "commit", "-q", "-m", "change")
    # argv[0] is a literal interpreter name; the script path is the repo's own file, not input.
    # nosemgrep — argv[0] is the interpreter this test CHOSE (bash vs sh); a literal cannot
    # express "run the same script under both shells", which is the whole point of the case.
    # The script path is the repo's own file and "base" is a fixed ref; nothing here is input.
    out = subprocess.run(  # nosemgrep
        [shell, str(SCRIPT), "base"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    return out.strip()


def test_docs_only_is_docs(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"docs/x.md": "x\n"}) == "docs"


def test_specs_is_specs(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"specs/spec-x.md": "x\n", "docs/y.md": "y\n"}) == "specs"


def test_code_is_full(tmp_path: Path) -> None:
    assert _tier_after(tmp_path, {"tap/x.py": "x = 1\n"}) == "full"


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
@pytest.mark.parametrize(
    "path",
    ["tap_web/skills/add-panel/SKILL.md", "tap_plugin/g/skills/x/SKILL.md", "tap_grid/skills/s/NOTES.md"],
)
def test_skill_prose_is_docs(tmp_path: Path, path: str) -> None:
    """A SKILL.md is instructions an agent reads; no boot lane opens the file (tap#410)."""
    assert _tier_after(tmp_path, {path: "# skill\n"}) == "docs"


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
@pytest.mark.parametrize(
    "path",
    ["tap_web/skills/drive-browser/drive.py", "tap_web/skills/s/helper.sh", "tap_web/skills/s/data.json"],
)
def test_code_inside_a_skill_directory_is_still_full(tmp_path: Path, path: str) -> None:
    """The `.md` in the pattern is load-bearing, not tidiness.

    A skill directory is not prose-only: `tap_web/skills/drive-browser/` ships `drive.py`
    and `mint_session.py`, real executable Python that the docs lane would not validate.
    A blanket `*/skills/*` carve-out would route those through a one-minute prose gate —
    a fast lane for code, which is the opposite of what tap#410 asked for.
    """
    assert _tier_after(tmp_path, {path: "x = 1\n"}) == "full"


@pytest.mark.spec("req-dev-validation-product-line-lanes-7")
def test_skill_prose_beside_code_is_full(tmp_path: Path) -> None:
    """The strictest file in the diff decides — prose does not launder its neighbour."""
    changes = {"tap_web/skills/s/SKILL.md": "# skill\n", "tap_web/skills/s/drive.py": "x = 1\n"}
    assert _tier_after(tmp_path, changes) == "full"


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


@pytest.mark.spec("req-dev-validation-bom-lane-2")
@pytest.mark.parametrize("shell", ["bash", "sh"])
def test_boot_tier_survives_a_posix_shell(tmp_path: Path, shell: str) -> None:
    """A BOM change classifies `boot` under sh as well as bash.

    `BASH_SOURCE` is a bash extension and is EMPTY under dash: it pointed the classifier's
    module path at the parent directory, the classifier could not run, its output came back
    empty, and the tier degraded to `full` with no error — the BOM lane then skipped and
    `gate` accepted the skip (observed on run 34457835453). A bash-only construct in this
    script fails quietly, so both shells are exercised.
    """
    assert _tier_after_with_shell(tmp_path, {"boot/test_all.boot.json": "{}\n"}, shell) == "boot"


@pytest.mark.spec("req-dev-validation-bom-lane-2")
@pytest.mark.spec("req-dev-localexec-host-syntax-floor-3")
def test_an_unanswerable_classifier_fails_closed_to_boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No verdict means MORE validation, never less.

    When the classifier cannot run at all (no python3 on PATH here), the script must still
    require the BOM lane. Degrading to `full` would drop the requirement silently, which is
    the failure this tier exists to remove.
    """
    repo = _repo_with_base(tmp_path)
    (repo / "tap").mkdir(parents=True, exist_ok=True)
    (repo / "tap" / "x.py").write_text("x = 1\n")
    _git(repo, "add", "tap/x.py")
    _git(repo, "commit", "-q", "-m", "change")
    # A PATH holding ONLY git and bash — symlinked in, so the real bin directory (which also
    # carries python3) is not on it. The classifier therefore cannot run at all.
    only_bin = tmp_path / "onlybin"
    only_bin.mkdir()
    for tool in ("git", "bash"):
        found = shutil.which(tool)
        assert found, f"the test needs {tool}"
        (only_bin / tool).symlink_to(found)
    assert shutil.which("python3", path=str(only_bin)) is None, "python3 must be absent for this test"
    # nosemgrep — argv[0] is the bash this test symlinked into a PATH it built, which is how
    # python3 is kept out of reach; a literal would resolve through the real PATH and defeat it.
    proc = subprocess.run(  # nosemgrep
        [str(only_bin / "bash"), str(SCRIPT), "base"],
        cwd=repo,
        env={"PATH": str(only_bin), "HOME": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == "boot"
    assert "no verdict" in proc.stderr
    # req-dev-localexec-host-syntax-floor-3: failing closed must not eat the CAUSE.
    # The classifier's own stderr is echoed beneath the verdict line, indented four
    # spaces. Assert on THAT block, not on the word "python3" — the verdict line itself
    # now names the interpreter, so a substring check there would pass even if the
    # capture were deleted. When this output went to /dev/null a SyntaxError in the
    # classifier was indistinguishable from a missing interpreter, and every PR ran
    # `boot` for weeks with nobody able to see why (tap#400).
    captured = [ln for ln in proc.stderr.splitlines() if ln.startswith("    ") and ln.strip()]
    assert captured, (
        "the classifier's own stderr was discarded — failing closed must report the cause. "
        f"stderr was: {proc.stderr!r}"
    )


@pytest.mark.spec("req-dev-validation-bom-lane-2")
def test_the_classifier_always_answers(tmp_path: Path) -> None:
    """`--classify` prints `boot` or `no-boot` — never silence, which reads as "did not run"."""
    # nosemgrep — a literal interpreter plus the repo's own module path; no input reaches argv.
    out = subprocess.run(  # nosemgrep
        ["python3", str(REPO_ROOT / "tap" / "bom_inputs.py"), "--classify", "--root", str(REPO_ROOT)],
        input="docs/x.md\n",
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "no-boot"
