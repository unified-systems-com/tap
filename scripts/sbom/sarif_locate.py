"""Stamp an SBOM-sourced Grype SARIF with the declaration that pinned each component.

Why this exists: `grype sbom:declared-<image>.cdx.json` scans a document, not a filesystem, so
every result it emits carries an EMPTY `physicalLocation.artifactLocation.uri`. GitHub Code
Scanning refuses the whole upload on that ("locationFromSarifResult: expected artifact
location", tap#294) — the job goes red for a reason unrelated to the vulnerabilities, and the
findings reach nobody. `continue-on-error` would make it green while still delivering nothing.

The honest location for such a finding is the record a human authored: the supplemental
manifest that declared the component (`docker/*sbom-supplemental.json`), at the line of that
component's entry. That is where the pin lives and where a bump lands, so an alert there points
at the thing to change. This script rewrites the SARIF in place with exactly that.

Derive-once: the manifest path comes from `declared_cdx.SUPPLEMENTALS` — the same table that
built the scanned document — so the image key cannot map to one file for the scan and another
for the location. The component is recovered from Grype's rule id, which it forms as
`<vuln-id>-<package-name>`, by matching against the names the manifest actually declares
(never by parsing free text out of the message).

Usage:
    python scripts/sbom/sarif_locate.py --image tap-web    # rewrites ./grype-declared-tap-web.sarif in place

The image is a KEY, not a path (the shape `declared_cdx.py` set): both the manifest read and the
SARIF rewritten are derived from it, so no filesystem path is ever taken from an argument. The
workflow tells the scanner to write `grype-declared-<image>.sarif` and this script derives the same
name — mirror sites, like `declared-<image>.cdx.json` between the workflow and declared_cdx.py.

Stdlib only — this runs on a bare CI runner (tap#294) and on a host without the venv.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent


def _declared_cdx() -> Any:
    """Load the sibling `declared_cdx.py` by path — the one table of per-image files — without
    touching `sys.path` (an import-time side effect that would leak into any test process)."""
    spec = importlib.util.spec_from_file_location("sbom_declared_cdx", _HERE / "declared_cdx.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load sibling declared_cdx.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_TABLES = _declared_cdx()
SUPPLEMENTALS: dict[str, Path] = _TABLES.SUPPLEMENTALS
SARIF_FILES: dict[str, str] = _TABLES.SARIF_FILES

#: SARIF's conventional base id for "relative to the checkout root" (what CodeQL emits).
SRCROOT = "%SRCROOT%"


def declaration_lines(manifest: Path) -> dict[str, int]:
    """Map each declared component name to the 1-based line of its `"name"` entry.

    Text-scanned rather than JSON-parsed because `json` does not keep line numbers; the
    manifest's own `"name": "<x>"` line is the anchor a reviewer sees in the Security tab.

    A name declared twice is refused (ValueError): the schema does not make names unique, and
    silently picking one line would stamp findings onto the wrong declaration with no signal.
    """
    lines: dict[str, int] = {}
    for n, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped.startswith('"name"'):
            continue
        try:
            name = str(json.loads("{" + stripped.rstrip(",") + "}")["name"])
        except ValueError, KeyError:
            continue
        if name in lines:
            raise ValueError(f"{manifest}: component name {name!r} is declared twice (lines {lines[name]} and {n})")
        lines[name] = n
    return lines


def _component_for(rule_id: str, names: list[str]) -> str | None:
    """Recover the declared component a Grype rule id names (`<vuln>-<package>`).

    Longest declared name wins so `uv` cannot shadow a hypothetical `foo-uv`.
    """
    for name in sorted(names, key=len, reverse=True):
        if rule_id.endswith(f"-{name}"):
            return name
    return None


def locate(sarif: dict[str, Any], uri: str, lines: dict[str, int]) -> tuple[int, int]:
    """Stamp every result whose artifact location is empty; return (stamped, unresolved).

    A location that already names a file is left alone — the fix is for the SBOM shape, not
    a rewrite of everything Grype says. A result with no `locations` at all gets one.
    `unresolved` counts results stamped with the file but not a component line (rule id
    matched no declared name); they still upload, at line 1.
    """
    stamped = unresolved = 0
    names = list(lines)
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            component = _component_for(str(result.get("ruleId", "")), names)
            line = lines.get(component or "", 1)
            locations = result.setdefault("locations", [])
            if not locations:
                locations.append({"physicalLocation": {}})
            touched = False
            for loc in locations:
                physical = loc.setdefault("physicalLocation", {})
                artifact = physical.setdefault("artifactLocation", {})
                if artifact.get("uri"):
                    continue
                artifact["uri"] = uri
                artifact["uriBaseId"] = SRCROOT
                physical["region"] = {"startLine": line}
                touched = True
            stamped += touched
            unresolved += touched and component is None
    return stamped, unresolved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image", required=True, choices=sorted(SUPPLEMENTALS))
    args = ap.parse_args(argv)

    # Both files come from the one table keyed by the image (declared_cdx.py): the manifest that
    # declared the components, and the SARIF the scanner was told to write in the working
    # directory. The argument selects entries; it contributes no bytes to either name.
    manifest = SUPPLEMENTALS[args.image]
    uri = manifest.relative_to(_REPO_ROOT).as_posix()
    path = Path.cwd() / SARIF_FILES[args.image]
    try:
        sarif = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"sarif_locate: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(sarif, dict) or not isinstance(sarif.get("runs"), list):
        print(f"sarif_locate: {path} is not a SARIF log (no 'runs' list)", file=sys.stderr)
        return 2

    try:
        lines = declaration_lines(manifest)
    except ValueError as exc:
        print(f"sarif_locate: {exc}", file=sys.stderr)
        return 2
    stamped, unresolved = locate(sarif, uri, lines)
    path.write_text(json.dumps(sarif, indent=2) + "\n", encoding="utf-8")
    total = sum(len(run.get("results", [])) for run in sarif["runs"])
    print(
        f"sarif_locate: {path.name}: {stamped} of {total} result(s) located on {uri}"
        + (f" ({unresolved} matched no declared component; placed at line 1)" if unresolved else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
