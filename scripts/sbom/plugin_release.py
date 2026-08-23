"""Plugin release SBOM — generate, gate, and prepare for attestation (req-cicd-sbom-10).

Declare-vs-decide, plugin edition: the plugin's release lane DECLARES an attested
per-release SBOM keyed on the boot-record identity (dist name, exact version); the
system (flavored-image bakes, boot records) later VERIFIES and composes — it never
re-derives blindly. This module is the generation + fail-closed gate half, run by
the reusable release workflow (core repo, .github/workflows/plugin-release-sbom.yml)
against the freshly built wheel:

 * One pinned-Syft derivation over the WHEEL (the artifact, not the source tree) →
   CycloneDX (primary) + SPDX. A wheel scan yields the plugin package at its exact
   version plus its DECLARED dependency requirements (dist METADATA Requires-Dist);
   dependency RESOLUTION deliberately does not happen here — the resolved closure
   is instance-level truth (boot record) or bake-level truth (flavored-image SBOM,
   req-cicd-sbom-9). The coverage statement says so explicitly.
 * Identity gate: the SBOM's plugin component MUST match the expected dist name and
   exact version (tag == wheel == SBOM — the boot-record join key). Phantom canaries
   apply as in the core lane.
 * Conformance: both documents schema-validate against core's vendored schemas;
   minimum-elements-lite on the primary (document fields, tools, identifiers —
   the dependency GRAPH is exempted here by design: a wheel declares requirements,
   it does not resolve them).

Shares core's vendored schemas and validators (loaded by path from generate.py —
one derivation of that logic, not a copy).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("sbom_generate", _HERE / "generate.py")
assert _spec is not None and _spec.loader is not None
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)

SYFT_IMAGE = _gen.SYFT_IMAGE
FORBIDDEN_NAMES = _gen.FORBIDDEN_NAMES


def dist_name_for(slug: str) -> str:
    """Slug -> dist name, the conformance-gated identity convention."""
    return "tap-plugin-" + slug.replace("_", "-")


def check_plugin_identity(doc: dict[str, object], slug: str, expected_version: str) -> list[str]:
    """The identity gate: dist name at the exact expected version, phantoms absent."""
    problems: list[str] = []
    dist = dist_name_for(slug)
    components_obj = doc.get("components", [])
    if not isinstance(components_obj, list):
        raise TypeError(f"CycloneDX components is {type(components_obj).__name__}, expected list")
    components = components_obj
    matches = [c for c in components if c.get("name") == dist]
    if not matches:
        problems.append(
            f"plugin component ABSENT: {dist} (found: {sorted(c.get('name', '?') for c in components)[:10]})"
        )
    elif not any(c.get("version") == expected_version for c in matches):
        problems.append(
            f"plugin version mismatch: {dist} is {[c.get('version') for c in matches]}, expected {expected_version} "
            "(tag == wheel == SBOM is the boot-record join key)"
        )
    names = {c.get("name") for c in components}
    for name in FORBIDDEN_NAMES:
        if name in names:
            problems.append(f"forbidden phantom PRESENT: {name}")
    return problems


def check_minimum_elements_wheel(doc: dict[str, object]) -> list[str]:
    """Minimum-elements-lite for a wheel SBOM: everything from the core check EXCEPT
    the dependency graph, which a wheel legitimately lacks (declared, not resolved)."""
    problems = _gen.check_minimum_elements(doc)
    return [p for p in problems if "dependency relationships" not in p]


def inject_coverage(doc: dict[str, object], coverage: str) -> dict[str, object]:
    meta = doc.setdefault("metadata", {})
    if not isinstance(meta, dict):
        raise TypeError(f"CycloneDX metadata is {type(meta).__name__}, expected object")
    props = meta.setdefault("properties", [])
    if not isinstance(props, list):
        raise TypeError(f"CycloneDX metadata.properties is {type(props).__name__}, expected list")
    props.append({"name": "tap:coverage", "value": coverage})
    return doc


def _run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)


def syft_scan_wheel(wheel: Path, out_cdx: Path, out_spdx: Path) -> None:
    """One pinned-Syft derivation over the wheel CONTENTS, both serializations.

    The wheel is extracted and dir-scanned: syft's `file:` source does not
    unpack archives (a raw .whl scan yields zero components — proven in the
    pilot smoke), while the unpacked `*.dist-info/METADATA` is exactly the
    python cataloger's food. Deliberately the same mechanism that made the
    wheel-cache phantoms in the image lane — there it was accident, here the
    unpacked wheel IS the artifact under description.
    """
    import zipfile

    with tempfile.TemporaryDirectory() as td:
        unpacked = Path(td) / "wheel"
        unpacked.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            # Belt on top of stdlib sanitization (zip-slip): this runs in the
            # privileged release job (OIDC + attestations), and the wheel —
            # though built seconds earlier in this same job — is cheap to
            # validate explicitly rather than reason about.
            for name in zf.namelist():
                if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                    raise ValueError(f"wheel member escapes extraction root: {name!r}")
            zf.extractall(unpacked)
        out = Path(td) / "out"
        out.mkdir()
        _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{unpacked}:/in:ro",
                "-v",
                f"{out}:/out",
                # Same trap as the image lane (groundwork §3.5): without this, syft
                # serializes every file as a name-only component.
                "-e",
                "SYFT_FILE_METADATA_SELECTION=none",
                SYFT_IMAGE,
                "scan",
                "dir:/in",
                "-o",
                "cyclonedx-json=/out/bom.cdx.json",
                "-o",
                "spdx-json=/out/bom.spdx.json",
            ]
        )
        out_cdx.write_bytes((out / "bom.cdx.json").read_bytes())
        out_spdx.write_bytes((out / "bom.spdx.json").read_bytes())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wheel", required=True, type=Path)
    ap.add_argument("--expected-version", required=True, help="from the release tag (vX.Y.Z -> X.Y.Z)")
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dist = dist_name_for(args.slug)
    out_cdx = args.out_dir / f"{dist}-{args.expected_version}.cdx.json"
    out_spdx = args.out_dir / f"{dist}-{args.expected_version}.spdx.json"

    syft_scan_wheel(args.wheel, out_cdx, out_spdx)

    coverage = (
        f"Describes the released wheel {args.wheel.name}: the plugin package "
        f"{dist}@{args.expected_version} and its DECLARED dependency requirements "
        f"(dist METADATA). Dependency resolution deliberately absent — the resolved "
        f"closure is instance-level truth (boot record) or bake-level truth "
        f"(flavored-image SBOM, req-cicd-sbom-9/-10). Generated at "
        f"{datetime.now(UTC).isoformat()}; document id {uuid.uuid4()}."
    )
    cdx = inject_coverage(json.loads(out_cdx.read_text(encoding="utf-8")), coverage)
    spdx = json.loads(out_spdx.read_text(encoding="utf-8"))

    _gen.validate_schema(cdx, "cyclonedx")
    _gen.validate_schema(spdx, "spdx")
    problems = check_minimum_elements_wheel(cdx)
    if problems:
        _gen.fail(problems, "conformance")
    problems = check_plugin_identity(cdx, args.slug, args.expected_version)
    if problems:
        _gen.fail(problems, "identity")

    out_cdx.write_text(json.dumps(cdx, indent=1) + "\n", encoding="utf-8")
    out_spdx.write_text(json.dumps(spdx, indent=1) + "\n", encoding="utf-8")
    components_out = cdx.get("components") or []
    if not isinstance(components_out, list):
        raise TypeError("CycloneDX components is not a list")
    n_components = len(components_out)
    print(f"plugin-sbom: OK {out_cdx.name} ({n_components} components) + {out_spdx.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
