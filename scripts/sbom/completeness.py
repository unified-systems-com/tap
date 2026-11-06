"""Field-completeness check for a CycloneDX SBOM (req-cicd-sbom-32).

A scanner matches on what the SBOM carries. An SBOM that lacks the matching fields does not fail;
it quietly reports fewer vulnerabilities. Measured on the attested tap-web document with Grype
v0.120.1: all fields gave 91 matches, no extra CPE candidates 89, no CPE 50, no CPE and no upstream
qualifier 12 (specs/spec-cicd-sbom.md, req-cicd-sbom-32). This check refuses that silent loss.

"Complete" here means FIELD completeness: each component carries the identifiers a matcher uses.
It does NOT mean inventory completeness (that every package in the image is listed); that is
req-cicd-sbom-2, -7 and -12. The document says so itself (COVERAGE below, req-cicd-sbom-32-10).

What is required of which component is DATA, in `completeness.rules.json` (validated against
`completeness.rules.schema.json` at load); how it is checked is this code. A component whose purl
ecosystem has no rule, or that has no purl and is not the operating-system component, is a gap of
class `unruled-ecosystem`: the check never passes a component it has no rule for (req-cicd-sbom-32-11).

Three outcomes, never two: `complete`, `thin` (with a count per gap class and examples), and
`not-observable` (the check could not run: unreadable document, invalid or unloadable rules).
Exit codes follow: 0, 1, 2. Only `complete` passes.

Usage:
    python scripts/sbom/completeness.py [--annotate] < doc.cdx.json > annotated.json 2>> "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

_HERE = Path(__file__).resolve().parent
DEFAULT_RULES = _HERE / "completeness.rules.json"
RULES_SCHEMA = _HERE / "completeness.rules.schema.json"
RULES_FORMAT = "tap-sbom-completeness-rules/1"

#: Written into the document so a `complete` verdict is never read as an inventory claim.
COVERAGE = (
    "Covers identifier fields only (purl and its qualifiers, cpe, apk origin package, the operating-system "
    "component). Does not cover whether every package in the image is listed."
)

#: Gap classes that are not a rule's own requirement name.
UNRULED = "unruled-ecosystem"
OS_COMPONENT = "os-component"
NO_COMPONENTS = "no-components"

#: How many example components each gap class keeps in the document.
MAX_EXAMPLES = 5

PROPERTY_PREFIX = "tap:completeness"

VERDICT_EXIT = {"complete": 0, "thin": 1, "not-observable": 2}


class RulesError(Exception):
    """The rules file could not be loaded or did not validate: the check cannot run."""


class MalformedDocument(Exception):
    """The document is not shaped like CycloneDX in a way the check relies on: the verdict is not-observable.

    A record the check cannot read must never be skipped and then reported as complete.
    """


#: Named once so no formatter target can rewrite it into the unparenthesized form, which only Python 3.14 accepts.
_CANNOT_ANNOTATE = (MalformedDocument, AttributeError, TypeError)


def _walk_components(raw: Any, path: str = "components") -> list[dict[str, Any]]:
    """Every component, nested ones included (CycloneDX allows `components` under a component).

    Raises `MalformedDocument` on a non-list, a non-object entry, or a `properties` that is not a list of
    objects, instead of skipping what it cannot read.
    """
    if not isinstance(raw, list):
        raise MalformedDocument(f"{path} is not a list")
    found: list[dict[str, Any]] = []
    for index, component in enumerate(raw):
        where = f"{path}[{index}]"
        if not isinstance(component, dict):
            raise MalformedDocument(f"{where} is not an object")
        _require_properties(component.get("properties"), where)
        found.append(component)
        if component.get("components") is not None:
            found += _walk_components(component["components"], f"{where}.components")
    return found


def _require_properties(properties: Any, where: str) -> None:
    if properties is None:
        return
    if not isinstance(properties, list) or any(not isinstance(p, dict) for p in properties):
        raise MalformedDocument(f"{where}.properties is not a list of objects")


def _cell(text: object) -> str:
    """Make document-controlled text safe inside a Markdown table cell of the job summary.

    A component name is attacker-controlled. Collapsing whitespace removes the newlines a heading or a new
    table row needs; the remaining characters that start markup are escaped; length is bounded.
    """
    cleaned = " ".join(str(text).split())[:120]
    for char, replacement in (
        ("\\", "\\\\"),
        ("|", "\\|"),
        ("`", "'"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ("[", "\\["),
        ("]", "\\]"),
    ):
        cleaned = cleaned.replace(char, replacement)
    return cleaned


def load_rules(path: Path | None = None) -> dict[str, Any]:
    """Read the rules file and validate it against its schema; raise `RulesError` on any failure.

    Fails closed: a missing `jsonschema` is a failure to load, not a reason to skip validation.
    """
    path = DEFAULT_RULES if path is None else path
    try:
        import jsonschema  # noqa: PLC0415 - optional at import time so a bare host can still import this module
    except ImportError as exc:
        raise RulesError(f"jsonschema is not importable, so the rules cannot be validated: {exc}") from exc
    rules: dict[str, Any]
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(RULES_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RulesError(f"cannot read the rules or their schema: {exc}") from exc
    try:
        jsonschema.validate(rules, schema)
    except jsonschema.ValidationError as exc:
        raise RulesError(f"rules do not validate: {exc.message} at {list(exc.absolute_path)}") from exc
    return rules


def _purl_type(purl: str) -> str:
    """The ecosystem of a purl: the text between `pkg:` and the first `/`."""
    body = purl[len("pkg:") :] if purl.startswith("pkg:") else ""
    return body.split("/", 1)[0].lower()


def _purl_qualifiers(purl: str) -> dict[str, str]:
    """Non-blank qualifiers of a purl. A blank value (`arch=`) counts as absent."""
    if "?" not in purl:
        return {}
    query = purl.split("?", 1)[1].split("#", 1)[0]
    return {key: value for key, value in parse_qsl(query) if value}


def _property(component: dict[str, Any], name: str) -> str | None:
    for prop in component.get("properties") or []:
        if prop.get("name") == name and prop.get("value"):
            return str(prop["value"])
    return None


def _label(component: dict[str, Any]) -> str:
    return f"{component.get('name', '?')}@{component.get('version', '?')}"


def _component_gaps(component: dict[str, Any], required: list[str]) -> list[str]:
    """Gap classes of one ruled component, given its ecosystem's requirements."""
    purl = str(component.get("purl") or "")
    qualifiers = _purl_qualifiers(purl)
    origin = _property(component, "syft:metadata:originPackage")
    gaps: list[str] = []
    for requirement in required:
        if requirement == "purl":
            if not purl:
                gaps.append("purl")
        elif requirement == "cpe":
            if not component.get("cpe"):
                gaps.append("cpe")
        elif requirement == "origin-package":
            if not origin:
                gaps.append("origin-package")
        elif requirement == "purl-qualifier:arch":
            if "arch" not in qualifiers:
                gaps.append("purl-qualifier:arch")
        elif requirement == "purl-qualifier:distro":
            if "distro" not in qualifiers:
                gaps.append("purl-qualifier:distro")
        elif requirement == "purl-qualifier:upstream-when-origin-differs":
            # req-cicd-sbom-32-4: conditional. An origin equal to the name needs no upstream qualifier.
            if origin and origin != component.get("name") and "upstream" not in qualifiers:
                gaps.append("purl-qualifier:upstream")
    return gaps


def _declared_unknown(component: dict[str, Any], field: str) -> bool:
    """True when the component says, with a reason, that it could not observe `field` (req-cicd-sbom-33-5)."""
    return _property(component, f"tap:{field}:status") == "not-observed" and bool(
        _property(component, f"tap:{field}:reason")
    )


def _attribute_gaps(component: dict[str, Any], required: list[str]) -> tuple[list[str], list[str]]:
    """(gap classes, declared-unknown fields) of one component for the attribute rules of its ecosystem."""
    gaps: list[str] = []
    declared: list[str] = []
    for requirement in required:
        if requirement == "licenses-or-declared-unknown":
            if component.get("licenses"):
                continue
            (declared if _declared_unknown(component, "licenses") else gaps).append(
                "licenses-declared-unknown" if _declared_unknown(component, "licenses") else "licenses"
            )
        elif requirement == "architecture-or-declared-unknown":
            if _property(component, "tap:architecture"):
                continue
            (declared if _declared_unknown(component, "architecture") else gaps).append(
                "architecture-declared-unknown" if _declared_unknown(component, "architecture") else "architecture"
            )
    return gaps, declared


def check_completeness(
    doc: dict[str, Any], rules: dict[str, Any], *, enforce_attributes: bool = False
) -> dict[str, Any]:
    """Check a CycloneDX document against the rules; return the verdict and its evidence.

    Two tiers. `require` are the MATCHING fields a scanner needs; a gap there is always `thin`. `require_attributes` are
    the inventory attributes the grid reads (license, architecture): a gap is reported in `attribute_gaps`, and makes
    the verdict `thin` only when `enforce_attributes` is set, which image generation does (req-cicd-sbom-33-7, -33-8)
    and a rescan of an older published revision does not.

    Pure function: no I/O. The result carries `verdict`, `components`, `counts` (gap class to number of
    components), `examples` (gap class to up to MAX_EXAMPLES labels) and `candidates` (components carrying
    Syft's `syft:cpe23` candidates, reported and never required: req-cicd-sbom-32-7).
    """
    metadata = doc.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise MalformedDocument("metadata is not an object")
        _require_properties(metadata.get("properties"), "metadata")
    raw = doc.get("components")
    components = _walk_components([] if raw is None else raw)
    gaps: dict[str, list[str]] = {}
    attribute_gaps: dict[str, list[str]] = {}
    declared_unknown: dict[str, dict[str, list[str]]] = {}

    def add(gap_class: str, label: str) -> None:
        gaps.setdefault(gap_class, []).append(label)

    if not components:
        add(NO_COMPONENTS, "document")

    os_components = [c for c in components if c.get("type") == "operating-system"]
    os_required = rules["operating_system"]["require"]
    if len(os_components) != 1:
        add(OS_COMPONENT, f"{len(os_components)} operating-system components, exactly 1 required")
    else:
        for field in os_required:
            if not os_components[0].get(field):
                add(OS_COMPONENT, f"{_label(os_components[0])} lacks {field}")

    ecosystems = rules["ecosystems"]
    for component in components:
        if component.get("type") == "operating-system":
            continue
        purl = str(component.get("purl") or "")
        ecosystem = _purl_type(purl) if purl else ""
        if not ecosystem or ecosystem not in ecosystems:
            add(UNRULED, f"{_label(component)} ({ecosystem or 'no purl'})")
            continue
        for gap_class in _component_gaps(component, ecosystems[ecosystem]["require"]):
            add(gap_class, _label(component))
        missing, declared = _attribute_gaps(component, ecosystems[ecosystem].get("require_attributes", []))
        for gap_class in missing:
            attribute_gaps.setdefault(gap_class, []).append(_label(component))
        for field in declared:
            declared_unknown.setdefault(ecosystem, {}).setdefault(field.removesuffix("-declared-unknown"), []).append(
                _label(component)
            )

    for ecosystem, fields in declared_unknown.items():
        limit = ecosystems[ecosystem].get("declared_unknown_limit", 0)
        for field, labels in fields.items():
            if len(labels) > limit:
                attribute_gaps.setdefault("declared-unknown-over-limit", []).append(
                    f"{ecosystem}: {field} unknown on {len(labels)} components, limit {limit}"
                )
    if enforce_attributes:
        for gap_class, labels in attribute_gaps.items():
            gaps.setdefault(gap_class, []).extend(labels)

    candidates = sum(1 for c in components if _property(c, "syft:cpe23"))
    return {
        "verdict": "thin" if gaps else "complete",
        "components": len(components),
        "counts": {gap_class: len(labels) for gap_class, labels in sorted(gaps.items())},
        "examples": {gap_class: labels[:MAX_EXAMPLES] for gap_class, labels in sorted(gaps.items())},
        "candidates": candidates,
        "attributes_enforced": enforce_attributes,
        "attribute_gaps": {gap_class: len(labels) for gap_class, labels in sorted(attribute_gaps.items())},
        "attribute_examples": {
            gap_class: labels[:MAX_EXAMPLES] for gap_class, labels in sorted(attribute_gaps.items())
        },
        "declared_unknown": {
            ecosystem: {field: len(labels) for field, labels in sorted(fields.items())}
            for ecosystem, fields in sorted(declared_unknown.items())
        },
    }


def annotate(doc: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Write the verdict into `metadata.properties`, replacing any earlier `tap:completeness*` entries.

    The property is present in every document this module touches, including the `not-observable`
    case (req-cicd-sbom-32-8): an absent property must never stand for `complete`.
    """
    metadata = doc.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise MalformedDocument("metadata is not an object")
    _require_properties(metadata.get("properties"), "metadata")
    kept = [p for p in metadata.get("properties") or [] if not str(p.get("name", "")).startswith(PROPERTY_PREFIX)]
    added = [{"name": PROPERTY_PREFIX, "value": result["verdict"]}]
    if result["verdict"] == "not-observable":
        added.append({"name": f"{PROPERTY_PREFIX}:reason", "value": str(result.get("reason", ""))})
    else:
        added += [
            {"name": f"{PROPERTY_PREFIX}:counts", "value": json.dumps(result["counts"], sort_keys=True)},
            {"name": f"{PROPERTY_PREFIX}:examples", "value": json.dumps(result["examples"], sort_keys=True)},
            {"name": f"{PROPERTY_PREFIX}:candidates", "value": str(result["candidates"])},
            {"name": f"{PROPERTY_PREFIX}:components", "value": str(result["components"])},
            {"name": f"{PROPERTY_PREFIX}:attributes", "value": json.dumps(result["attribute_gaps"], sort_keys=True)},
            {
                "name": f"{PROPERTY_PREFIX}:attributes-enforced",
                "value": "true" if result["attributes_enforced"] else "false",
            },
            {
                "name": f"{PROPERTY_PREFIX}:declared-unknown",
                "value": json.dumps(result["declared_unknown"], sort_keys=True),
            },
        ]
    added.append({"name": f"{PROPERTY_PREFIX}:coverage", "value": COVERAGE})
    metadata["properties"] = kept + added
    return doc


def summary_markdown(result: dict[str, Any]) -> str:
    """The job-summary text: the verdict and, for `thin`, every gap class with examples."""
    lines = [f"### SBOM completeness: `{result['verdict']}`", ""]
    if result["verdict"] == "not-observable":
        lines.append(f"The check could not run: {_cell(result.get('reason', 'unknown reason'))}")
        return "\n".join(lines) + "\n"
    lines.append(f"{result['components']} components checked; {result['candidates']} carry `syft:cpe23` candidates.")
    if result["counts"]:
        lines += ["", "| Gap class | Components | Examples |", "| --- | ---: | --- |"]
        for gap_class, count in result["counts"].items():
            examples = "; ".join(_cell(label) for label in result["examples"][gap_class])
            lines.append(f"| `{gap_class}` | {count} | {examples} |")
    if result["attribute_gaps"] and not result["attributes_enforced"]:
        notes = "; ".join(f"{_cell(k)}: {v}" for k, v in result["attribute_gaps"].items())
        lines += ["", f"Attribute gaps, reported and not enforced at intake: {notes}."]
    if result["declared_unknown"]:
        declared = "; ".join(
            f"{_cell(eco)} {_cell(field)}: {n}"
            for eco, fields in result["declared_unknown"].items()
            for field, n in fields.items()
        )
        lines += ["", f"Declared unknown (with a reason): {declared}."]
    lines += ["", COVERAGE]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Read a CycloneDX document on stdin; verdict markdown on stderr; exit 0, 1 or 2.

    No file path is taken from the command line or built from the input: the document arrives on stdin, the
    annotated document (with `--annotate`) leaves on stdout, and the job summary is the shell's redirect of
    stderr (`2>> "$GITHUB_STEP_SUMMARY"`). The rules are the committed file next to this module.
    """
    parser = argparse.ArgumentParser(description="Field-completeness check for a CycloneDX SBOM, read from stdin.")
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="write the document with the tap:completeness properties to stdout",
    )
    parser.add_argument(
        "--enforce-attributes",
        action="store_true",
        help="make a missing license or architecture (not declared unknown) a thin verdict, as image generation does",
    )
    args = parser.parse_args(argv)

    doc: dict[str, Any] | None = None
    try:
        loaded = json.loads(sys.stdin.read())
        if not isinstance(loaded, dict):
            raise ValueError("top level is not an object")
        doc = loaded
        result = check_completeness(doc, load_rules(), enforce_attributes=args.enforce_attributes)
    except (OSError, ValueError, RulesError, MalformedDocument, KeyError, TypeError, AttributeError) as exc:
        result = {"verdict": "not-observable", "reason": f"{type(exc).__name__}: {exc}"}

    if args.annotate and doc is not None:
        try:
            sys.stdout.write(json.dumps(annotate(doc, result), indent=2) + "\n")
        except _CANNOT_ANNOTATE:
            # A document too malformed to carry the property cannot be written back; the verdict still stands
            # as not-observable and the run still fails.
            result = {"verdict": "not-observable", "reason": "the document is too malformed to annotate"}
    sys.stderr.write(summary_markdown(result))
    return VERDICT_EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
