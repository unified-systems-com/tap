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
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# Prefer generate.py's schema-validated loader — one derivation of "what a supplemental IS",
# not a second parser that could drift from the schema it is supposed to honour.
#
# It needs `jsonschema`, which is not present on a bare CI runner or host Python. Rather than add
# a dependency to a SECURITY lane for a belt-and-braces check, fall back to a plain read and say
# so. The supplementals are already schema-gated where it counts: `tap/tests/test_sbom_generate.py`
# per-commit, and `generate.py` fail-closed at publish. A validation failure here would be the
# third place to learn it, not the first.
def _load(path: Path) -> dict:
    try:
        spec = importlib.util.spec_from_file_location("sbom_generate", _HERE / "generate.py")
        if spec is None or spec.loader is None:
            raise ImportError("cannot load sibling generate.py")
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        return gen.load_supplemental(path)
    except ImportError as exc:
        print(f"declared_cdx: schema validation unavailable ({exc}); reading {path} unvalidated", file=sys.stderr)
        return json.loads(path.read_text(encoding="utf-8"))


def declared_document(supplemental: dict) -> dict:
    """A CycloneDX 1.5 doc carrying each declared component's identity, and nothing more."""
    components = []
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

    supplemental = _load(args.supplemental)
    doc = declared_document(supplemental)
    if not doc["components"]:
        print("declared_cdx: supplemental declared no components — refusing to emit an empty scan input", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(f"{c['name']}@{c['version']}" for c in doc["components"])
    print(f"declared_cdx: wrote {args.out} with {len(doc['components'])} component(s): {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
