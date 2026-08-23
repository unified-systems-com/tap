"""Wheel-cache seed manifest — generate and verify (req-cicd-supply-chain-provenance-2).

The web image ships a pre-compiled uv wheel cache (/opt/uv-cache-seed, Dockerfile
deps-warm stage). Build-time inputs are verified by uv.lock hashes and the build is
attested — but the boot-time seed copy was a bare `cp`, and a warm-cache `uv sync`
does NOT re-verify hashes on cache hits. This module closes that gap:

* `generate` runs INSIDE the attested image build (deps-warm) and writes a per-file
  sha256 manifest of the seed tree, keyed by RELATIVE POSIX path — the seed is
  generated under /root/.cache/uv and verified under /opt/uv-cache-seed, so absolute
  paths would never match. The manifest is written OUTSIDE the tree (enforced), so it
  never lists itself.
* `verify` runs in docker/entrypoint.sh BEFORE seeding an empty uv-cache volume, as a
  FULL BIDIRECTIONAL reconciliation: hash mismatches, files missing from the seed,
  and extra unmanifested files are all failures — a partial or padded seed must not
  pass as "mostly fine". On success it emits one machine-legible boot-evidence line.

Semantics split by presence (spec): an ABSENT seed may degrade cleanly (uv falls back
to lock-hash-verified downloads/compiles); a PRESENT-but-invalid seed is a fail-closed
boot abort — inside an immutable image that means corruption or tamper, never
staleness. The abort itself is the entrypoint's job (emit_abort); this module only
reports.

Runs under bare in-container python3 BEFORE `uv sync` creates the venv, so it MUST
stay stdlib-only (guarded by tap/tests/test_boot_pointer.py's import-graph walk).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

MANIFEST_FORMAT = "tap-seed-manifest/1"
_CHUNK = 1 << 20


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_files(tree: Path) -> dict[str, str]:
    """Hash every regular file under tree, keyed by relative POSIX path."""
    files: dict[str, str] = {}
    for path in sorted(tree.rglob("*")):
        if path.is_file():
            files[path.relative_to(tree).as_posix()] = _sha256_file(path)
    return files


def generate(tree: Path, out: Path) -> dict[str, object]:
    """Write the manifest for tree to out (which MUST lie outside tree)."""
    tree = tree.resolve()
    out = out.resolve()
    if not tree.is_dir():
        raise ValueError(f"seed tree does not exist or is not a directory: {tree}")
    if out.is_relative_to(tree):
        raise ValueError(f"manifest path {out} is inside the tree it describes — it would list itself")
    manifest: dict[str, object] = {
        "format": MANIFEST_FORMAT,
        "_description": (
            "Per-file sha256 manifest of the image's uv wheel-cache seed, generated inside "
            "the attested image build and verified by the entrypoint before seeding an empty "
            "cache volume (req-cicd-supply-chain-provenance-2). Keys are POSIX paths relative "
            "to the seed root; the manifest lives outside the tree and never lists itself."
        ),
        "files": _walk_files(tree),
    }
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify(tree: Path, manifest_path: Path) -> dict[str, object]:
    """Full bidirectional reconciliation.

    Returns a report dict: {"failures": [...], "declared": N, "observed": N,
    "missing": [...], "extra": [...], "mismatched": [...]} — empty "failures"
    means valid. The class lists carry EVERY member (callers cap the display);
    "failures" is the flat human-readable form. On a structural problem
    (manifest missing/unreadable/format, tree missing) the report has zero
    counts and one structural failure line — the diagnostic dump then shows
    exactly what the verifier could and could not see.
    """
    failures: list[str] = []
    missing: list[str] = []
    extra: list[str] = []
    mismatched: list[str] = []
    declared_count = 0
    observed_count = 0

    def report() -> dict[str, object]:
        return {
            "failures": failures,
            "declared": declared_count,
            "observed": observed_count,
            "missing": missing,
            "extra": extra,
            "mismatched": mismatched,
        }

    if not manifest_path.is_file():
        failures.append(f"manifest missing: {manifest_path}")
        return report()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        declared = manifest["files"]
        fmt = manifest["format"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        failures.append(f"manifest unreadable: {exc}")
        return report()
    if not isinstance(declared, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in declared.items()
    ):
        # Valid JSON, wrong shape (e.g. files as a list) — a clean structural
        # failure, never a traceback from the set operations below.
        failures.append("manifest malformed: 'files' must be an object of {relative-path: sha256}")
        return report()
    if fmt != MANIFEST_FORMAT:
        failures.append(f"manifest format {fmt!r} != expected {MANIFEST_FORMAT!r}")
        return report()
    declared_count = len(declared)
    if not tree.is_dir():
        failures.append(f"seed tree missing: {tree}")
        return report()

    actual = _walk_files(tree)
    observed_count = len(actual)
    missing.extend(sorted(set(declared) - set(actual)))
    extra.extend(sorted(set(actual) - set(declared)))
    mismatched.extend(sorted(rel for rel in set(declared) & set(actual) if declared[rel] != actual[rel]))
    for rel in missing:
        failures.append(f"MISSING from seed: {rel}")
    for rel in extra:
        failures.append(f"EXTRA unmanifested file: {rel}")
    for rel in mismatched:
        failures.append(f"HASH MISMATCH: {rel}")
    return report()


def _as_str_list(value: object) -> list[str]:
    """Narrow a report field back to its concrete type (dict[str, object] boundary).

    Deterministic raise, not assert: this is boot-gate code and asserts strip
    under python -O."""
    if not isinstance(value, list):
        raise TypeError(f"report field is {type(value).__name__}, expected list")
    return value


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "generate":
        generate(Path(argv[2]), Path(argv[3]))
        return 0
    if len(argv) == 4 and argv[1] == "verify":
        report = verify(Path(argv[2]), Path(argv[3]))
        failures = _as_str_list(report["failures"])
        if failures:
            # Diagnostic dump: the whole story, bounded — what the manifest
            # declared, what the tree actually held, per-class counts with
            # capped samples, then one machine-legible failure evidence line.
            print(
                f"seed-verify: manifest declares {report['declared']} file(s); "
                f"observed {report['observed']} in the seed tree",
                file=sys.stderr,
            )
            _CAP = 10
            for klass, label in [
                ("missing", "MISSING from seed"),
                ("extra", "EXTRA unmanifested"),
                ("mismatched", "HASH MISMATCH"),
            ]:
                members = _as_str_list(report[klass])
                if not members:
                    continue
                print(f"seed-verify: {label}: {len(members)} file(s)", file=sys.stderr)
                for rel in members[:_CAP]:
                    print(f"seed-verify:   {rel}", file=sys.stderr)
                if len(members) > _CAP:
                    print(f"seed-verify:   … and {len(members) - _CAP} more", file=sys.stderr)
            for line in failures:
                if not any(line.startswith(p) for p in ("MISSING", "EXTRA", "HASH")):
                    print(f"seed-verify: {line}", file=sys.stderr)  # structural problems, verbatim
            evidence = {
                "tap_boot_evidence": "seed-verify",
                "result": "failed",
                "declared": report["declared"],
                "observed": report["observed"],
                "missing": len(_as_str_list(report["missing"])),
                "extra": len(_as_str_list(report["extra"])),
                "mismatched": len(_as_str_list(report["mismatched"])),
            }
            print(f"seed-verify: FAILED {json.dumps(evidence)}", file=sys.stderr)
            return 1
        # Machine-legible boot evidence (req-cicd-supply-chain-provenance-2): emitted
        # here, pre-tap.preboot; the boot-record surface absorbs it when available.
        print(json.dumps({"tap_boot_evidence": "seed-verify", "result": "ok", "files": report["declared"]}))
        return 0
    print("usage: seed_manifest.py generate <tree> <out-manifest> | verify <tree> <manifest>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
