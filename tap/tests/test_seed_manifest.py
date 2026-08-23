"""Wheel-cache seed manifest generate/verify (req-cicd-supply-chain-provenance-2).

The module under test runs under bare in-container python3 BEFORE `uv sync`
creates the venv, so it lives at docker/seed_manifest.py (not inside the tap
package) and is loaded here by path. Its stdlib-only constraint is guarded by
the import-graph walk in test_boot_pointer.py.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("seed_manifest", _REPO_ROOT / "docker" / "seed_manifest.py")
assert _spec is not None and _spec.loader is not None
seed_manifest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_manifest)


@pytest.fixture()
def seed_tree(tmp_path: Path) -> Path:
    """A miniature seed: nested dirs, an empty file, binary content."""
    tree = tmp_path / "seed"
    (tree / "archive-v0" / "ab").mkdir(parents=True)
    (tree / "archive-v0" / "ab" / "wheel.whl").write_bytes(b"\x00\x01binary")
    (tree / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55")
    (tree / "empty.marker").write_text("")
    return tree


def _manifest_for(tree: Path, tmp_path: Path) -> Path:
    out = tmp_path / "manifest.json"
    seed_manifest.generate(tree, out)
    return out


def test_roundtrip_valid_seed_verifies_clean(seed_tree: Path, tmp_path: Path) -> None:
    manifest = _manifest_for(seed_tree, tmp_path)
    assert seed_manifest.verify(seed_tree, manifest)["failures"] == []


def test_relocated_tree_still_verifies(seed_tree: Path, tmp_path: Path) -> None:
    """Generated under one root, verified under another — the deps-warm
    (/root/.cache/uv) vs runtime (/opt/uv-cache-seed) path asymmetry: relative
    paths are load-bearing."""
    manifest = _manifest_for(seed_tree, tmp_path)
    relocated = tmp_path / "opt" / "uv-cache-seed"
    shutil.copytree(seed_tree, relocated)
    assert seed_manifest.verify(relocated, manifest)["failures"] == []


def test_hash_mismatch_detected(seed_tree: Path, tmp_path: Path) -> None:
    manifest = _manifest_for(seed_tree, tmp_path)
    (seed_tree / "archive-v0" / "ab" / "wheel.whl").write_bytes(b"tampered")
    failures = seed_manifest.verify(seed_tree, manifest)["failures"]
    assert any("HASH MISMATCH" in f and "wheel.whl" in f for f in failures)


def test_missing_file_detected(seed_tree: Path, tmp_path: Path) -> None:
    manifest = _manifest_for(seed_tree, tmp_path)
    (seed_tree / "empty.marker").unlink()
    failures = seed_manifest.verify(seed_tree, manifest)["failures"]
    assert any("MISSING" in f and "empty.marker" in f for f in failures)


def test_extra_unmanifested_file_detected(seed_tree: Path, tmp_path: Path) -> None:
    """A padded seed must not pass as 'mostly fine' — extra files fail too."""
    manifest = _manifest_for(seed_tree, tmp_path)
    (seed_tree / "archive-v0" / "smuggled.whl").write_bytes(b"payload")
    failures = seed_manifest.verify(seed_tree, manifest)["failures"]
    assert any("EXTRA" in f and "smuggled.whl" in f for f in failures)


def test_absent_manifest_is_invalid_not_stale(seed_tree: Path, tmp_path: Path) -> None:
    failures = seed_manifest.verify(seed_tree, tmp_path / "nope.json")["failures"]
    assert failures and "manifest missing" in failures[0]


def test_generate_refuses_manifest_inside_tree(seed_tree: Path) -> None:
    """The manifest must never list itself — enforced, not remembered."""
    with pytest.raises(ValueError, match="inside the tree"):
        seed_manifest.generate(seed_tree, seed_tree / "manifest.json")


def test_generate_is_deterministic(seed_tree: Path, tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    seed_manifest.generate(seed_tree, a)
    seed_manifest.generate(seed_tree, b)
    assert a.read_bytes() == b.read_bytes()


def test_corrupt_manifest_json_is_a_failure(seed_tree: Path, tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    failures = seed_manifest.verify(seed_tree, bad)["failures"]
    assert failures and "unreadable" in failures[0]


def test_cli_verify_emits_boot_evidence(seed_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = _manifest_for(seed_tree, tmp_path)
    rc = seed_manifest.main(["seed_manifest.py", "verify", str(seed_tree), str(manifest)])
    assert rc == 0
    evidence = json.loads(capsys.readouterr().out.strip())
    assert evidence == {"tap_boot_evidence": "seed-verify", "result": "ok", "files": 3}


def test_cli_verify_failure_exit_code_and_diagnostics(
    seed_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A red verify dumps the whole story: declared/observed counts, per-class
    counts with samples, and a machine-legible failure evidence line."""
    manifest = _manifest_for(seed_tree, tmp_path)
    (seed_tree / "CACHEDIR.TAG").write_text("altered")
    (seed_tree / "empty.marker").unlink()
    (seed_tree / "smuggled.bin").write_bytes(b"x")
    rc = seed_manifest.main(["seed_manifest.py", "verify", str(seed_tree), str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "manifest declares 3 file(s); observed 3" in err
    assert "MISSING from seed: 1 file(s)" in err and "empty.marker" in err
    assert "EXTRA unmanifested: 1 file(s)" in err and "smuggled.bin" in err
    assert "HASH MISMATCH: 1 file(s)" in err and "CACHEDIR.TAG" in err
    evidence = json.loads(err.rsplit("seed-verify: FAILED ", 1)[1].splitlines()[0])
    assert evidence == {
        "tap_boot_evidence": "seed-verify",
        "result": "failed",
        "declared": 3,
        "observed": 3,
        "missing": 1,
        "extra": 1,
        "mismatched": 1,
    }


def test_cli_diagnostic_sample_cap(seed_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Bounded dump: at most 10 samples per class, with an '… and N more' tail."""
    manifest = _manifest_for(seed_tree, tmp_path)
    for i in range(14):
        (seed_tree / f"pad{i:02}.bin").write_bytes(b"x")
    rc = seed_manifest.main(["seed_manifest.py", "verify", str(seed_tree), str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "EXTRA unmanifested: 14 file(s)" in err
    assert "… and 4 more" in err


def test_malformed_files_shape_is_clean_failure(seed_tree: Path, tmp_path: Path) -> None:
    """Valid JSON with 'files' as a list must fail cleanly, never traceback."""
    bad = tmp_path / "shape.json"
    bad.write_text(json.dumps({"format": seed_manifest.MANIFEST_FORMAT, "files": ["a", "b"]}))
    failures = seed_manifest.verify(seed_tree, bad)["failures"]
    assert failures and "malformed" in failures[0]
