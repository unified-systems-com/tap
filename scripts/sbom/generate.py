"""SBOM generation lane — one derivation, two serializations, fail-closed gates.

Implements the generation half of spec-cicd-sbom.md against one verified per-arch
image digest (req-cicd-sbom-1/-2/-3/-5/-6, gates -7/-11):

 1. Load + JSON-Schema-validate the image's supplemental manifest (declared
    out-of-band components — req-cicd-sbom-3; schema beside this script).
 2. Run pinned Syft ONCE against ref@digest (the single derivation), lockfile
    cataloger enabled, wheel-cache + uv-binary noise excluded, emitting BOTH
    CycloneDX JSON (primary) and SPDX JSON.
 3. Extract each declared file from the image and hash it (sha256 computed from
    the artifact, per-arch, at generation time — never hand-declared), then
    inject the supplemental components into BOTH documents. Part of generation,
    never a post-hoc edit to an attested document.
 4. Conformance (req-cicd-sbom-11): schema-validate BOTH documents against the
    vendored pinned schemas; minimum-elements checks on the primary.
 5. Canaries (req-cicd-sbom-7): required components present (incl. every
    declared out-of-band component), known phantoms absent. Any failure exits
    nonzero BEFORE anything can be attested.

Runs on the CI runner (publish-images.yml manifest job) under python3 +
jsonschema; unit-testable pure functions, orchestration in main().
"""

# mypy: allow-untyped-defs, allow-any-generics
# ^ JSON-document plumbing at a system boundary (CLAUDE.md: Any is allowed at
#   system boundaries with justification): every structure here is a foreign
#   schema (CycloneDX/SPDX/syft output) validated by jsonschema, not by mypy.
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SYFT_IMAGE = "anchore/syft:v1.51.0@sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0"

# Scan-surface exclusions (req-cicd-sbom-2): the wheel-cache phantom inventory and
# the uv/uvx embedded cargo-auditable crate closures. The uv/uvx EXECUTABLES are
# declared components (supplemental manifest), only their embedded metadata is noise.
SYFT_EXCLUDES = ["/opt/uv-cache-seed/**", "/bin/uv", "/bin/uvx", "/usr/bin/uv", "/usr/bin/uvx"]

# Canary lists (req-cicd-sbom-7): TAP-specific truths. Required names are checked in
# addition to EVERY component of the supplemental manifest (a dropped declaration is
# a red publish). Forbidden names/locations are the known-phantom markers.
CANARIES = {
    "tap-web": {"required": ["tap", "django", "openssl"]},
    "tap-db": {"required": ["postgresql-16"]},
}
FORBIDDEN_NAMES = ["my-test-package"]
FORBIDDEN_LOCATION_PREFIXES = ["/opt/uv-cache-seed"]
MAX_MISSING_PURL = 5  # pragmatic fail-closed: syft emits purls for apk + python; a
# handful of edge components may lack one ("where they exist"), a flood means the
# scan shape regressed.


def fail(msgs: list[str], stage: str) -> None:
    for m in msgs:
        print(f"sbom-{stage}: {m}", file=sys.stderr)
    print(f"sbom-{stage}: FAILED ({len(msgs)} problem(s))", file=sys.stderr)
    raise SystemExit(1)


def load_supplemental(path: Path) -> dict[str, object]:
    """Load + schema-validate the supplemental manifest (req-cicd-sbom-3)."""
    import jsonschema

    manifest: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((_HERE / "supplemental.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(manifest, schema)
    return manifest


def _cdx_registry() -> object:
    """Vendored-schema registry so bom-1.6's relative $refs resolve offline."""
    from referencing import Registry, Resource

    resources = []
    for name in ["spdx.schema.json", "jsf-0.82.schema.json"]:
        doc = json.loads((_HERE / "schemas" / name).read_text(encoding="utf-8"))
        resources.append((name, Resource.from_contents(doc)))
        if "$id" in doc:
            resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def validate_schema(doc: dict[str, object], kind: str) -> None:
    """Schema-validate a generated document against the vendored pinned schemas."""
    import jsonschema

    if kind == "cyclonedx":
        schema = json.loads((_HERE / "schemas" / "bom-1.6.schema.json").read_text(encoding="utf-8"))
        jsonschema.validators.validator_for(schema)(schema, registry=_cdx_registry()).validate(doc)
    elif kind == "spdx":
        schema = json.loads((_HERE / "schemas" / "spdx-2.3.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(doc, schema)
    else:  # pragma: no cover - programmer error
        raise ValueError(kind)


def inject_cdx(doc: dict, supplemental: dict, hashes: dict[str, str], *, coverage: str) -> dict:
    """Merge declared components + the coverage statement into the CycloneDX doc."""
    components = doc.setdefault("components", [])
    for comp in supplemental["components"]:
        entry = {
            "type": "library" if comp["source_kind"] == "self-built" else "application",
            "bom-ref": f"tap-supplemental:{comp['name']}@{comp['version']}",
            "name": comp["name"],
            "version": comp["version"],
            "licenses": [{"expression": comp["license"]}],
            "hashes": [{"alg": "SHA-256", "content": hashes[comp["name"]]}],
            "properties": [
                {"name": "tap:supplemental", "value": "true"},
                {"name": "tap:source", "value": comp["source"]},
                {"name": "tap:source_kind", "value": comp["source_kind"]},
                {"name": "tap:path", "value": comp["path"]},
            ],
        }
        if "purl" in comp:
            entry["purl"] = comp["purl"]
        if "cpe" in comp:
            entry["cpe"] = comp["cpe"]
        components.append(entry)
    props = doc.setdefault("metadata", {}).setdefault("properties", [])
    props.append({"name": "tap:coverage", "value": coverage})
    return doc


def inject_spdx(doc: dict, supplemental: dict, hashes: dict[str, str]) -> dict:
    """Merge declared components into the SPDX doc (packages + DESCRIBES edges)."""
    packages = doc.setdefault("packages", [])
    relationships = doc.setdefault("relationships", [])
    for comp in supplemental["components"]:
        spdx_id = f"SPDXRef-TapSupplemental-{comp['name']}"
        pkg = {
            "SPDXID": spdx_id,
            "name": comp["name"],
            "versionInfo": comp["version"],
            "downloadLocation": comp["source"] if comp["source"].startswith("http") else "NOASSERTION",
            "licenseConcluded": comp["license"],
            "licenseDeclared": comp["license"],
            "copyrightText": "NOASSERTION",
            "checksums": [{"algorithm": "SHA256", "checksumValue": hashes[comp["name"]]}],
        }
        if "purl" in comp:
            pkg["externalRefs"] = [
                {"referenceCategory": "PACKAGE-MANAGER", "referenceType": "purl", "referenceLocator": comp["purl"]}
            ]
        packages.append(pkg)
        relationships.append(
            {"spdxElementId": "SPDXRef-DOCUMENT", "relatedSpdxElement": spdx_id, "relationshipType": "DESCRIBES"}
        )
    return doc


def check_minimum_elements(doc: dict) -> list[str]:
    """CISA/NSA 2026 minimum-elements checks on the primary (CycloneDX) document."""
    problems: list[str] = []
    if doc.get("bomFormat") != "CycloneDX":
        problems.append(f"bomFormat is {doc.get('bomFormat')!r}, not CycloneDX")
    for field in ["specVersion", "serialNumber", "version"]:
        if not doc.get(field):
            problems.append(f"missing document field: {field}")
    meta = doc.get("metadata", {})
    if not meta.get("timestamp"):
        problems.append("missing metadata.timestamp (generation context)")
    tools = meta.get("tools")
    # CycloneDX serializes tools as either an object ({components/services}) or a
    # legacy array — handle both without assuming a shape (a list has no .get).
    if isinstance(tools, dict):
        has_tools = bool(tools.get("components") or tools.get("services"))
    else:
        has_tools = isinstance(tools, list) and len(tools) > 0
    if not has_tools:
        problems.append("missing metadata.tools (generating tool name/version)")
    if not any(p.get("name") == "tap:coverage" for p in meta.get("properties", [])):
        problems.append("missing tap:coverage statement (what the document does/does not cover)")
    components = doc.get("components", [])
    if not components:
        problems.append("no components at all")
    unnamed = [c for c in components if not c.get("name") or not c.get("version")]
    if unnamed:
        problems.append(f"{len(unnamed)} component(s) missing name or version")
    missing_purl = [c.get("name", "?") for c in components if not c.get("purl") and not c.get("cpe")]
    if len(missing_purl) > MAX_MISSING_PURL:
        problems.append(
            f"{len(missing_purl)} components lack purl/CPE (> {MAX_MISSING_PURL}): {sorted(missing_purl)[:10]}..."
        )
    if not doc.get("dependencies"):
        problems.append("missing dependency relationships (the graph, not a flat list)")
    return problems


def check_canaries(doc: dict, image: str, supplemental: dict) -> list[str]:
    """TAP-specific truths (req-cicd-sbom-7), fail-closed."""
    problems: list[str] = []
    names = {c.get("name") for c in doc.get("components", [])}
    required = set(CANARIES[image]["required"]) | {c["name"] for c in supplemental["components"]}
    for name in sorted(required):
        if name not in names:
            problems.append(f"required component ABSENT: {name}")
    for name in FORBIDDEN_NAMES:
        if name in names:
            problems.append(f"forbidden phantom PRESENT: {name}")
    for comp in doc.get("components", []):
        for occ in (comp.get("evidence") or {}).get("occurrences", []) or []:
            loc = occ.get("location", "")
            for prefix in FORBIDDEN_LOCATION_PREFIXES:
                if loc.startswith(prefix):
                    problems.append(f"component {comp.get('name')} located under forbidden {prefix}: {loc}")
    return problems


# ---------------------------------------------------------------------------
# Orchestration (docker + syft) — exercised by the publish pipeline, not unit tests.
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    print(f"+ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, check=True, capture_output=capture)


def syft_scan(subject: str, out_cdx: Path, out_spdx: Path) -> None:
    """One pinned-Syft scan (the single derivation) emitting both serializations."""
    with tempfile.TemporaryDirectory() as td:
        excludes: list[str] = []
        for pattern in SYFT_EXCLUDES:
            excludes += ["--exclude", pattern]
        _run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "/var/run/docker.sock:/var/run/docker.sock",
                "-v",
                f"{td}:/out",
                # File-metadata selection OFF: syft otherwise serializes every file in
                # the image as a name-only CycloneDX component (~13.8k entries), which
                # is a file inventory masquerading as a package claim — and it trips
                # our own minimum-elements gate (proven in the pre-CI smoke).
                "-e",
                "SYFT_FILE_METADATA_SELECTION=none",
                SYFT_IMAGE,
                "scan",
                f"docker:{subject}",
                "--select-catalogers",
                "+python-package-cataloger",
                *excludes,
                "-o",
                "cyclonedx-json=/out/bom.cdx.json",
                "-o",
                "spdx-json=/out/bom.spdx.json",
            ]
        )
        out_cdx.write_bytes((Path(td) / "bom.cdx.json").read_bytes())
        out_spdx.write_bytes((Path(td) / "bom.spdx.json").read_bytes())


def extract_hashes(subject: str, supplemental: dict) -> dict[str, str]:
    """sha256 of each declared file, read from the actual artifact (per-arch)."""
    hashes: dict[str, str] = {}
    container = subprocess.run(["docker", "create", subject], check=True, capture_output=True, text=True).stdout.strip()
    try:
        with tempfile.TemporaryDirectory() as td:
            for comp in supplemental["components"]:
                dest = Path(td) / comp["name"]
                _run(["docker", "cp", f"{container}:{comp['path']}", str(dest)], capture=True)
                hashes[comp["name"]] = hashlib.sha256(dest.read_bytes()).hexdigest()
    finally:
        subprocess.run(["docker", "rm", container], check=True, capture_output=True)
    return hashes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image", required=True, choices=sorted(CANARIES))
    ap.add_argument("--ref", required=True, help="registry ref WITHOUT digest, e.g. ghcr.io/org/tap-web")
    ap.add_argument("--digest", required=True, help="sha256:... of THIS arch's verified manifest")
    ap.add_argument("--arch", required=True)
    ap.add_argument("--supplemental", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)

    subject = f"{args.ref}@{args.digest}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_cdx = args.out_dir / f"{args.image}-{args.arch}.cdx.json"
    out_spdx = args.out_dir / f"{args.image}-{args.arch}.spdx.json"

    supplemental = load_supplemental(args.supplemental)
    _run(["docker", "pull", "--quiet", subject])
    syft_scan(subject, out_cdx, out_spdx)
    hashes = extract_hashes(subject, supplemental)

    coverage = (
        f"Covers the Wolfi apk closure, the uv.lock-declared Python closure, and the "
        f"declared out-of-band components of {subject} ({args.arch}). Deliberately "
        f"excluded: /opt/uv-cache-seed (wheel cache: available bytes, not running "
        f"software) and the uv/uvx binaries' embedded cargo-auditable crate metadata "
        f"(the tool's closure, not the artifact's; the executables ARE declared). "
        f"Generated at {datetime.now(UTC).isoformat()}; supplemental manifest "
        f"format {supplemental['format']}; document id {uuid.uuid4()}."
    )
    cdx = inject_cdx(json.loads(out_cdx.read_text()), supplemental, hashes, coverage=coverage)
    spdx = inject_spdx(json.loads(out_spdx.read_text()), supplemental, hashes)

    validate_schema(cdx, "cyclonedx")
    validate_schema(spdx, "spdx")
    problems = check_minimum_elements(cdx)
    if problems:
        fail(problems, "conformance")
    problems = check_canaries(cdx, args.image, supplemental)
    if problems:
        fail(problems, "canary")

    out_cdx.write_text(json.dumps(cdx, indent=1) + "\n", encoding="utf-8")
    out_spdx.write_text(json.dumps(spdx, indent=1) + "\n", encoding="utf-8")
    print(f"sbom-generate: OK {out_cdx.name} ({len(cdx['components'])} components) + {out_spdx.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
