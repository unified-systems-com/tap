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
    python scripts/sbom/declared_cdx.py --image tap-web    # writes ./declared-tap-web.cdx.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
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

# The image is a KEY, not a path. Both the manifest read and the document written are derived
# from this table, so no filesystem path is ever constructed from an argument — which removes
# the path-traversal class outright instead of trying to sanitise it, and matches the
# `--image` + `choices=` shape generate.py already uses.
SUPPLEMENTALS: dict[str, Path] = {
    "tap-web": _REPO_ROOT / "docker" / "sbom-supplemental.json",
    "tap-db": _REPO_ROOT / "docker" / "postgres" / "sbom-supplemental.json",
}

#: The scanner's per-image output in the nightly lane (grype-declared-nightly.yml tells the
#: scanner to write it; sarif_locate.py rewrites it). Named here, beside the manifests it
#: derives from, so the lane's file names live in ONE table keyed by the same image keys and
#: nothing downstream assembles a filesystem name from an argument.
SARIF_FILES: dict[str, str] = {image: f"grype-declared-{image}.sarif" for image in SUPPLEMENTALS}


def _load(path: Path) -> dict[str, Any]:
    """Load a supplemental, validating against its schema where jsonschema is available.

    It needs `jsonschema`, which is not present on a bare CI runner or host Python. Rather than
    add a dependency to a SECURITY lane for a belt-and-braces check, fall back to a plain read
    and say so. The supplementals are already schema-gated where it counts:
    `tap/tests/test_sbom_generate.py` per-commit, and `generate.py` fail-closed at publish.
    """
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


def _shape_or_die(supplemental: dict[str, Any], source: Path) -> list[dict[str, Any]]:
    """Assert the shape the emitter relies on, with a message that names the file.

    On the unvalidated fallback path a missing `components` or `source_kind` would surface as a
    bare KeyError from inside a comprehension. In a security lane the failure should say which
    file is malformed and what it lacks — a confusing traceback is how a real problem gets
    mistaken for a tooling bug.
    """
    components = supplemental.get("components")
    if not isinstance(components, list):
        raise ValueError(f"{source}: no 'components' list — is this a supplemental manifest?")
    for i, comp in enumerate(components):
        missing = [k for k in ("name", "version", "source_kind") if k not in comp]
        if missing:
            raise ValueError(f"{source}: component {i} is missing {', '.join(missing)}")
    return components


def declared_document(components: list[dict[str, Any]]) -> dict[str, Any]:
    """A CycloneDX 1.5 doc carrying each declared component's identity, and nothing more."""
    out: list[dict[str, object]] = []
    for comp in components:
        entry: dict[str, object] = {
            "type": "library" if comp["source_kind"] == "self-built" else "application",
            "bom-ref": f"tap-declared:{comp['name']}@{comp['version']}",
            "name": comp["name"],
            "version": comp["version"],
        }
        # Identity is the whole point: without at least one of these a matcher has nothing to
        # resolve, and the component is invisible — the state this script exists to end.
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
        out.append(entry)
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
        "components": out,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True, choices=sorted(SUPPLEMENTALS))
    args = ap.parse_args(argv)

    source = SUPPLEMENTALS[args.image]
    try:
        components = _shape_or_die(_load(source), source)
    except ValueError as exc:
        print(f"declared_cdx: {exc}", file=sys.stderr)
        return 2
    if not components:
        print(f"declared_cdx: {source} declares no components — refusing to emit an empty scan input", file=sys.stderr)
        return 1

    doc = declared_document(components)
    out_path = Path.cwd() / f"declared-{args.image}.cdx.json"
    out_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(f"{c['name']}@{c['version']}" for c in doc["components"])
    print(f"declared_cdx: wrote {out_path} with {len(doc['components'])} component(s): {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
