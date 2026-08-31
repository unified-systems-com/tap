"""Emit a minimal CycloneDX document containing ONLY the declared out-of-band components.

Why this exists: the nightly Trivy scan reads the image's package databases (apk, the Python
closure). The out-of-band components declared in `docker/*sbom-supplemental.json` are, by
definition, the things no package manager installed — so the image scan cannot see them, and the
most compliance-significant binary we ship (the self-built OpenSSL FIPS provider) has never been
in a vulnerability scanner's field of view.

This turns those declarations into something a matcher can consume. `trivy sbom` over the output
resolves each component's `cpe`/`purl` against NVD/OSV, and the findings ride the same SARIF →
code-scanning path as the image scan (req-cicd-security-scanning, tap#231).

⚠️ THIS IS NOT THE SHIPPED SBOM. The published artifact is `scripts/sbom/generate.py`'s
single derivation — Syft over a verified digest, per-arch, with real file hashes, schema and
minimum-element gates, and attestation. This document is a *vulnerability-matching input*: it
carries identity (name/version/purl/cpe) and deliberately **omits `hashes` entirely** rather than
inventing them, because a hash claimed without measuring the artifact is exactly the kind of
declaration this repo keeps finding to be false. Never attest it and never publish it.

Usage:
    python scripts/sbom/declared_cdx.py --supplemental docker/sbom-supplemental.json --out /tmp/x.cdx.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

# Prefer generate.py's schema-validated loader — one derivation of "what a supplemental IS",
# not a second parser that could drift from the schema it is supposed to honour.
#
# It needs `jsonschema`, which is not present on a bare CI runner or host Python. Rather than add
# a dependency to a SECURITY lane for a belt-and-braces check, fall back to a plain read and say
# so. The supplementals are already schema-gated where it counts: `tap/tests/test_sbom_generate.py`
# per-commit, and `generate.py` fail-closed at publish. A validation failure here would be the
# third place to learn it, not the first.
_REPO_ROOT = _HERE.parent.parent


def _checked(path: Path, *, allow_temp: bool = False) -> Path:
    """Resolve `path` and refuse anything outside the roots this script may legitimately touch.

    Path traversal is not hypothetical here: the script is invoked from a workflow with
    matrix-supplied values, and both arguments reach `open()`. Resolve first, then compare —
    that rejects `../` escapes and absolute paths in one check, and returning the resolved
    path means a caller cannot accidentally go on using the unvalidated original.

    The two arguments have genuinely different rights, so they get different rules. The INPUT
    is a committed manifest and must live in the repository. The OUTPUT is a scratch file the
    caller consumes immediately, so a temp directory is legitimate — and forbidding it would
    only push callers into writing scan inputs into the working tree.
    """
    resolved = path.expanduser().resolve()
    roots = [_REPO_ROOT]
    if allow_temp:
        roots.append(Path(tempfile.gettempdir()).resolve())
    if not any(resolved.is_relative_to(root) for root in roots):
        allowed = " or ".join(str(r) for r in roots)
        raise ValueError(f"path must be under {allowed}, got {path}")
    return resolved


def _load(path: Path) -> dict[str, Any]:
    try:
        spec = importlib.util.spec_from_file_location("sbom_generate", _HERE / "generate.py")
        if spec is None or spec.loader is None:
            raise ImportError("cannot load sibling generate.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        loaded: dict[str, Any] = gen.load_supplemental(path)
        return loaded
    except ImportError as exc:
        print(f"declared_cdx: schema validation unavailable ({exc}); reading {path} unvalidated", file=sys.stderr)
        parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return parsed


def declared_document(supplemental: dict[str, Any]) -> dict[str, Any]:
    """A CycloneDX 1.5 doc carrying each declared component's identity, and nothing more."""
    components: list[dict[str, object]] = []
    for comp in supplemental["components"]:
        entry: dict[str, object] = {
            "type": "library" if comp["source_kind"] == "self-built" else "application",
            "bom-ref": f"tap-declared:{comp['name']}@{comp['version']}",
            "name": comp["name"],
            "version": comp["version"],
        }
        # Identity is the whole point: without at least one of these, a matcher has nothing
        # to resolve and the component is invisible — the state this script exists to end.
        if "purl" in comp:
            entry["purl"] = comp["purl"]
        if "cpe" in comp:
            entry["cpe"] = comp["cpe"]
        if "purl" not in comp and "cpe" not in comp:
            print(
                f"declared_cdx: {comp['name']} has neither purl nor cpe — it will match nothing. "
                f"Give it an identifier or state why it has none.",
                file=sys.stderr,
            )
        components.append(entry)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "properties": [
                {"name": "tap:document_kind", "value": "declared-components-only"},
                {
                    "name": "tap:not_the_shipped_sbom",
                    "value": "vulnerability-matching input; no hashes, never attested",
                },
            ]
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--supplemental", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)

    # Both paths reach open(). This script's callers include CI workflows and AI operators,
    # so validate at the boundary rather than reasoning about what a hostile value could do
    # (the argument-injection hardening already applied in scripts/sbom/oob_detect.py).
    try:
        supplemental_path = _checked(args.supplemental)
        out_path = _checked(args.out, allow_temp=True)
    except ValueError as exc:
        print(f"declared_cdx: {exc}", file=sys.stderr)
        return 2

    supplemental = _load(supplemental_path)
    doc = declared_document(supplemental)
    if not doc["components"]:
        print("declared_cdx: supplemental declared no components — refusing to emit an empty scan input", file=sys.stderr)
        return 1
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(f"{c['name']}@{c['version']}" for c in doc["components"])
    print(f"declared_cdx: wrote {out_path} with {len(doc['components'])} component(s): {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
