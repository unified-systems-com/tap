"""The entrypoint must not reuse packages compiled for a different image (tap#933).

The uv cache and the /app/.venv volume outlive the image. They hold packages compiled against
that image's system OpenSSL, and `uv sync` keeps an installed version it already has. After
Wolfi moved to OpenSSL 4.0, that served a 3.6-built `cryptography` beside a 4.0 CPython: two
OpenSSL cores, one fips.so, "unable to fetch drbg". `tap_clear_if_other_image` stamps the cache
with the image's identity (its seed manifest's hash) and empties both volumes when the stamp
does not match.

The function is extracted and run against temp directories, the same way
test_pr_review_triage.py runs its script's functions: no image, no Docker. Every outcome is
asserted, including the ones that must leave things alone.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.sh"
_FUNCTION = re.compile(r"^tap_clear_if_other_image\(\) \{.*?^\}$", re.DOTALL | re.MULTILINE)

pytestmark = pytest.mark.skipif(
    shutil.which("sha256sum") is None or shutil.which("bash") is None,
    reason="the entrypoint function uses bash and sha256sum, as the image does",
)


def _run_full(tmp: Path, manifest: Path) -> subprocess.CompletedProcess[str]:
    match = _FUNCTION.search(ENTRYPOINT.read_text(encoding="utf-8"))
    assert match, "tap_clear_if_other_image() not found in docker/entrypoint.sh"
    fn = tmp / "fn.sh"
    fn.write_text(match.group(0) + "\n", encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", 'source "$1"; tap_clear_if_other_image "$2" "$3" "$4"', "_",
         str(fn), str(manifest), str(tmp / "cache"), str(tmp / "venv")],
        capture_output=True, text=True, check=True,
    )


def _run(tmp: Path, manifest: Path) -> str:
    match = _FUNCTION.search(ENTRYPOINT.read_text(encoding="utf-8"))
    assert match, "tap_clear_if_other_image() not found in docker/entrypoint.sh"
    fn = tmp / "fn.sh"
    fn.write_text(match.group(0) + "\n", encoding="utf-8")
    return subprocess.run(
        ["bash", "-c", 'source "$1"; tap_clear_if_other_image "$2" "$3" "$4"', "_",
         str(fn), str(manifest), str(tmp / "cache"), str(tmp / "venv")],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _setup(tmp: Path, *, stamp: str | None, cached: bool = True) -> Path:
    manifest = tmp / "manifest.json"
    manifest.write_text('{"wheels": "this image"}', encoding="utf-8")
    cache, venv = tmp / "cache", tmp / "venv"
    cache.mkdir()
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "cryptography.so").write_text("built for some image", encoding="utf-8")
    if cached:
        (cache / "wheels").mkdir()
        (cache / "wheels" / "cryptography.whl").write_text("cached", encoding="utf-8")
    if stamp is not None:
        (cache / ".tap-image-id").write_text(stamp + "\n", encoding="utf-8")
    return manifest


def _image_id(manifest: Path) -> str:
    return subprocess.run(["sha256sum", str(manifest)], capture_output=True, text=True, check=True).stdout.split()[0]


def test_a_cache_from_another_image_is_emptied_with_the_venv(tmp_path: Path) -> None:
    """tap#933's exact shape: the stamp names a different image, so both volumes are cleared."""
    manifest = _setup(tmp_path, stamp="0" * 64)
    out = _run(tmp_path, manifest)

    assert out == _image_id(manifest)
    assert list((tmp_path / "cache").iterdir()) == []
    assert list((tmp_path / "venv").iterdir()) == []
    assert (tmp_path / "cache").is_dir() and (tmp_path / "venv").is_dir()  # mount points survive


def test_an_unstamped_nonempty_cache_is_treated_as_another_image(tmp_path: Path) -> None:
    """Every cache filled before this check existed has no stamp; it must not be trusted."""
    manifest = _setup(tmp_path, stamp=None)
    _run(tmp_path, manifest)

    assert list((tmp_path / "cache").iterdir()) == []
    assert list((tmp_path / "venv").iterdir()) == []


def test_a_cache_stamped_by_this_image_is_kept(tmp_path: Path) -> None:
    """The other branch: a matching stamp must leave both volumes untouched."""
    manifest = _setup(tmp_path, stamp=None)
    (tmp_path / "cache" / ".tap-image-id").write_text(_image_id(manifest) + "\n", encoding="utf-8")

    _run(tmp_path, manifest)

    assert (tmp_path / "cache" / "wheels" / "cryptography.whl").exists()
    assert (tmp_path / "venv" / "lib" / "cryptography.so").exists()


def test_a_stale_venv_is_cleared_even_when_the_cache_is_empty(tmp_path: Path) -> None:
    """A venv volume can outlive its cache volume; with nothing stamped, its packages are unvouched."""
    manifest = _setup(tmp_path, stamp=None, cached=False)
    _run(tmp_path, manifest)

    assert list((tmp_path / "venv").iterdir()) == []
    assert (tmp_path / "cache").is_dir()


def test_an_image_without_a_manifest_wipes_nothing(tmp_path: Path) -> None:
    """A legacy image has no identity to compare against, so it must not guess."""
    _setup(tmp_path, stamp="0" * 64)
    out = _run(tmp_path, tmp_path / "no-such-manifest.json")

    assert out == ""
    assert (tmp_path / "cache" / "wheels" / "cryptography.whl").exists()
    assert (tmp_path / "venv" / "lib" / "cryptography.so").exists()


def test_a_stamp_that_is_not_a_digest_clears_and_is_never_logged(tmp_path: Path) -> None:
    """The stamp sits in a volume: arbitrary text in it counts as no stamp and never reaches the log."""
    manifest = _setup(tmp_path, stamp="sensitive-test-value\x1b[31m")
    result = _run_full(tmp_path, manifest)

    assert "sensitive-test-value" not in result.stderr
    assert list((tmp_path / "venv").iterdir()) == []


def test_a_symlinked_stamp_is_not_followed(tmp_path: Path) -> None:
    """A symlink pointing at a real digest elsewhere is still no stamp; the volumes are cleared."""
    manifest = _setup(tmp_path, stamp=None)
    target = tmp_path / "elsewhere"
    target.write_text(_image_id(manifest) + "\n", encoding="utf-8")
    (tmp_path / "cache" / ".tap-image-id").symlink_to(target)

    _run(tmp_path, manifest)

    assert list((tmp_path / "venv").iterdir()) == []


def test_a_valid_foreign_stamp_is_logged_as_a_short_prefix_only(tmp_path: Path) -> None:
    """Even a well-formed digest from another image is logged as 12 characters, not in full."""
    manifest = _setup(tmp_path, stamp="a" * 64)
    result = _run_full(tmp_path, manifest)

    assert "stamp aaaaaaaaaaaa," in result.stderr
    assert "a" * 13 not in result.stderr
