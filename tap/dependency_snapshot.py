"""A plugin's OWN dependency closure, walked from a booted venv (tap#664, tap#772).

Two output formats over ONE walk:

- ``cyclonedx`` — a CycloneDX 1.5 document, identity only (name, version, purl). This is what
  ``plugin-ci.yml`` scans with Trivy and gates on. It needs no GitHub write scope at all.
- ``github-snapshot`` (the default, kept so an older pinned ``plugin-ci.yml`` that calls it
  without ``--format`` still gets what it expects) — a GitHub dependency-submission payload.
  Submitting it needs ``contents: write``, which plugin CI no longer holds anywhere (the Q20
  ruling, George 2026-09-25: no job in plugin CI may hold ``contents: write``), so plugin CI no
  longer submits it.

**The gap this closes.** Plugin repos ship `pyproject.toml` and no lockfile, so GitHub's
dependency graph has nothing to parse and every plugin repo reports *0 Dependabot alerts* —
which means nothing was examined, not that nothing was found. tap's own `uv.lock` IS parsed
(29 alerts raised and fixed against it), so the mechanism works the moment a manifest exists.

**Why not a lockfile in the plugin repo.** `uv lock` cannot resolve there: sibling plugins are
not on PyPI, and the `[tool.uv.sources]` table that would make it resolve is read by
`uv pip install` *even when installing the plugin from a git URL* — which is what pre-boot
runs. A plugin author could then decide which version of a sibling a boot installs, overriding
the operator's profile pins. That inverts the boot model (the profile is the BOM) to buy a
scan. Rejected; see tap#664 for the reproduction.

**What this does instead.** After a real boot, the venv holds the plugin AND everything it
pulled in. Walk `importlib.metadata` from the plugin's own distribution and emit the closure; a
scanner then matches it against PyPI advisories (purls in a known ecosystem, which is what
Trivy matches on).

**SCOPED — the ruling (George, 2026-09-19).** Traversal STOPS at sibling plugin distributions.
They own their own repositories and submit their own snapshots, so walking into them would
attribute a sibling's Django CVE to every plugin that depends on it, and an alert nobody owns
is how people learn to ignore alerts. Siblings are not silently dropped: each one is named in
the manifest `metadata` as a scoped-out boundary, so the edge is visible to anyone reading the
snapshot.

**Approximations, stated rather than hidden.**

- Requirement markers are evaluated against the interpreter running this module. That is the
  container that boots the plugin, so it matches production — but a snapshot taken on a
  different platform would legitimately differ.
- Extras are expanded only where a requirement *requests* them (``foo[bar]`` evaluates foo's
  requirements with ``extra == "bar"``). A package that ends up installed only because some
  OTHER tool asked for an extra is not reached by this walk.
- A declared dependency that is NOT installed is reported in the manifest metadata rather than
  invented as a node: the snapshot describes the resolved environment, never the wish.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

from tap.plugin_identity import installed_plugin_dist_name, is_plugin_dist_name, normalized_dist_name

logger = logging.getLogger(__name__)

#: The submission API's payload version (the only value it accepts today).
SNAPSHOT_VERSION = 0

#: Detector identity — who produced this snapshot. Read by humans in the graph UI.
DETECTOR_NAME = "tap-dependency-snapshot"
DETECTOR_URL = "https://github.com/unified-systems-com/tap"

#: The one scope this walk describes: what a boot installs to RUN the plugin.
RUNTIME_SCOPE = "runtime"

#: Output formats of the CLI.
FORMAT_GITHUB_SNAPSHOT = "github-snapshot"
FORMAT_CYCLONEDX = "cyclonedx"


@dataclass(frozen=True)
class DistInfo:
    """One installed distribution: the three facts the walk needs."""

    name: str
    version: str
    #: Raw ``Requires-Dist`` strings, exactly as the metadata carries them.
    requires: tuple[str, ...] = ()


#: Resolve a distribution name to its installed facts, or None when it is absent.
Lookup = Callable[[str], DistInfo | None]


@dataclass
class Snapshot:
    """The walk's result: the nodes in scope, plus every boundary it stopped at."""

    #: normalized name -> node dict (package_url / relationship / scope / dependencies)
    resolved: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Sibling plugin distributions the walk deliberately did not enter.
    scoped_out_siblings: set[str] = field(default_factory=set)
    #: Declared requirements that are not installed — reported, never invented.
    declared_not_installed: set[str] = field(default_factory=set)
    #: normalized name -> installed version, for every node in ``resolved``.
    versions: dict[str, str] = field(default_factory=dict)


def _installed_lookup(name: str) -> DistInfo | None:
    try:
        dist = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    return DistInfo(
        name=dist.metadata["Name"] or name,
        version=dist.version,
        requires=tuple(dist.requires or ()),
    )


def _applicable(requirement: Requirement, extras: frozenset[str]) -> bool:
    """True if *requirement* is active for a dist installed with *extras*.

    ``extra`` is passed explicitly (empty string for "no extra requested") so a
    ``; extra == "dev"`` requirement is excluded rather than silently evaluated against an
    undefined marker variable.
    """
    if requirement.marker is None:
        return True
    candidates = extras or frozenset({""})
    return any(requirement.marker.evaluate({"extra": extra}) for extra in candidates)


def _requirements(info: DistInfo, extras: frozenset[str]) -> list[Requirement]:
    """Parse and filter one distribution's requirements; malformed entries are reported, not fatal."""
    out: list[Requirement] = []
    for raw in info.requires:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            logger.warning(
                "[b979] dependency snapshot: %s declares an unparseable requirement %r — skipped", info.name, raw
            )
            continue
        if _applicable(requirement, extras):
            out.append(requirement)
    return out


def _purl(name: str, version: str) -> str:
    """A PyPI package URL. Names are PEP 503-normalized, which is how purls compare."""
    return f"pkg:pypi/{normalized_dist_name(name)}@{version}"


def walk_closure(root_dist: str, *, lookup: Lookup | None = None) -> Snapshot:
    """Walk *root_dist*'s installed dependency closure, stopping at sibling plugins.

    The root itself is NOT a node: a snapshot describes what the repository depends on, and
    the repository IS the root. Its own requirements are ``direct``; everything reachable
    beyond them is ``indirect``.
    """
    resolve = lookup or _installed_lookup
    root = resolve(root_dist)
    if root is None:
        raise LookupError(
            f"{root_dist} is not installed — a snapshot cannot describe an environment that lacks its own plugin"
        )

    snapshot = Snapshot()
    # (name, extras, relationship); the root's own requirements are the direct set.
    queue: list[tuple[str, frozenset[str], str]] = [
        (requirement.name, frozenset(requirement.extras), "direct") for requirement in _requirements(root, frozenset())
    ]
    seen: set[str] = set()

    while queue:
        name, extras, relationship = queue.pop(0)
        key = normalized_dist_name(name)
        if key in seen:
            continue
        seen.add(key)

        if is_plugin_dist_name(name):
            # The boundary. A sibling's closure belongs to the sibling's repository, which
            # runs this same walk and submits it there.
            snapshot.scoped_out_siblings.add(key)
            continue

        info = resolve(name)
        if info is None:
            snapshot.declared_not_installed.add(key)
            continue

        child_requirements = _requirements(info, extras)
        dependencies = sorted(
            normalized_dist_name(requirement.name)
            for requirement in child_requirements
            if not is_plugin_dist_name(requirement.name)
        )
        snapshot.resolved[key] = {
            "package_url": _purl(info.name, info.version),
            "relationship": relationship,
            "scope": RUNTIME_SCOPE,
            "dependencies": dependencies,
        }
        snapshot.versions[key] = info.version
        for requirement in child_requirements:
            queue.append((requirement.name, frozenset(requirement.extras), "indirect"))

    return snapshot


def manifest_name(root_dist: str) -> str:
    """The manifest key shown in the dependency graph UI."""
    return f"tap boot closure ({normalized_dist_name(root_dist)})"


def build_payload(
    root_dist: str,
    *,
    sha: str,
    ref: str,
    job_id: str,
    job_correlator: str,
    detector_version: str,
    source_location: str = "pyproject.toml",
    scanned: str | None = None,
    lookup: Lookup | None = None,
) -> dict[str, Any]:
    """Build the full submission payload for *root_dist*. Deterministic for a given venv."""
    snapshot = walk_closure(root_dist, lookup=lookup)
    metadata: dict[str, Any] = {
        "tap_scope": "the plugin's own closure; traversal stops at sibling plugin distributions (tap#664)",
    }
    if snapshot.scoped_out_siblings:
        metadata["scoped_out_siblings"] = ", ".join(sorted(snapshot.scoped_out_siblings))
    if snapshot.declared_not_installed:
        metadata["declared_not_installed"] = ", ".join(sorted(snapshot.declared_not_installed))

    name = manifest_name(root_dist)
    return {
        "version": SNAPSHOT_VERSION,
        "sha": sha,
        "ref": ref,
        "job": {"id": job_id, "correlator": job_correlator},
        "detector": {"name": DETECTOR_NAME, "version": detector_version, "url": DETECTOR_URL},
        "scanned": scanned or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifests": {
            name: {
                "name": name,
                "file": {"source_location": source_location},
                "metadata": metadata,
                "resolved": {key: snapshot.resolved[key] for key in sorted(snapshot.resolved)},
            }
        },
    }


#: CycloneDX spec version emitted — the one `scripts/sbom/declared_cdx.py` emits too.
CYCLONEDX_SPEC_VERSION = "1.5"


def build_cyclonedx(root_dist: str, *, lookup: Lookup | None = None) -> dict[str, Any]:
    """The same scoped closure as :func:`build_payload`, as a CycloneDX document for a scanner.

    Identity only — name, version, purl — because matching is all it is for; it is never
    attested and is not the shipped SBOM. Deterministic for a given venv: no timestamp and no
    serial number, so the same closure is the same bytes.

    The root plugin is ``metadata.component`` WITHOUT a purl: it is not published to PyPI, and
    a purl would invite a match against whatever unrelated project holds that name there.
    """
    snapshot = walk_closure(root_dist, lookup=lookup)  # raises LookupError when the root is absent
    root = (lookup or _installed_lookup)(root_dist)
    root_version = root.version if root is not None else ""
    root_ref = f"tap-plugin:{normalized_dist_name(root_dist)}@{root_version}"

    def ref(key: str) -> str:
        return str(snapshot.resolved[key]["package_url"])

    components = [
        {
            "type": "library",
            "bom-ref": ref(key),
            "name": key,
            "version": snapshot.versions[key],
            "purl": ref(key),
        }
        for key in sorted(snapshot.resolved)
    ]
    direct = sorted(ref(key) for key, node in snapshot.resolved.items() if node["relationship"] == "direct")
    dependencies = [{"ref": root_ref, "dependsOn": direct}] + [
        {
            "ref": ref(key),
            # A child that is a sibling plugin or not installed has no node, so no edge.
            "dependsOn": sorted(
                ref(child) for child in snapshot.resolved[key]["dependencies"] if child in snapshot.resolved
            ),
        }
        for key in sorted(snapshot.resolved)
    ]
    properties = [
        {"name": "tap:document_kind", "value": "plugin-own-closure"},
        {
            "name": "tap:scope",
            "value": "the plugin's own closure; traversal stops at sibling plugin distributions (tap#664)",
        },
    ]
    if snapshot.scoped_out_siblings:
        properties.append({"name": "tap:scoped_out_siblings", "value": ", ".join(sorted(snapshot.scoped_out_siblings))})
    if snapshot.declared_not_installed:
        properties.append(
            {"name": "tap:declared_not_installed", "value": ", ".join(sorted(snapshot.declared_not_installed))}
        )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "library",
                "bom-ref": root_ref,
                "name": normalized_dist_name(root_dist),
                "version": root_version,
            },
            "properties": properties,
        },
        "components": components,
        "dependencies": dependencies,
    }


def _core_version() -> str:
    try:
        return importlib.metadata.version("tap")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tap.dependency_snapshot",
        description="Emit one plugin's own dependency closure, as CycloneDX or a GitHub dependency snapshot.",
    )
    parser.add_argument("--slug", required=True, help="Plugin slug; resolved to its installed distribution name.")
    parser.add_argument(
        "--format",
        choices=(FORMAT_GITHUB_SNAPSHOT, FORMAT_CYCLONEDX),
        default=FORMAT_GITHUB_SNAPSHOT,
        help="Output format. `cyclonedx` needs only --slug; `github-snapshot` also needs --sha/--ref/--job-*.",
    )
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""), help="Commit the snapshot is about.")
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF", ""), help="Ref the snapshot is about.")
    parser.add_argument("--job-id", default=os.environ.get("GITHUB_RUN_ID", ""), help="CI run id.")
    parser.add_argument(
        "--job-correlator",
        default="-".join(filter(None, (os.environ.get("GITHUB_WORKFLOW", ""), os.environ.get("GITHUB_JOB", "")))),
        help="Stable per-job key; a later run with the same correlator REPLACES this snapshot.",
    )
    parser.add_argument(
        "--detector-version",
        default="",
        help="Version recorded as the detector's. Defaults to core's installed version, or '0' when core is on the path rather than installed (the container's case).",
    )
    # Deliberately NO --out: the snapshot goes to stdout and the caller redirects it.
    # An argv-supplied output path is a write primitive this tool does not need, and
    # SonarCloud S8707 is right to flag one (found on PR 677 before it shipped).
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.format == FORMAT_CYCLONEDX:
        return _main_cyclonedx(args.slug)
    missing = [
        flag
        for flag, value in (
            ("--sha", args.sha),
            ("--ref", args.ref),
            ("--job-id", args.job_id),
            ("--job-correlator", args.job_correlator),
        )
        if not value
    ]
    if missing:
        print(f"dependency-snapshot: missing required value(s): {', '.join(missing)}", file=sys.stderr)
        return 2

    dist = installed_plugin_dist_name(args.slug)
    if dist is None:
        print(
            f"dependency-snapshot: no installed distribution for slug '{args.slug}' "
            f"(looked for both naming conventions) — the boot did not install the plugin this snapshot is about",
            file=sys.stderr,
        )
        return 1

    payload = build_payload(
        dist,
        sha=args.sha,
        ref=args.ref,
        job_id=args.job_id,
        job_correlator=args.job_correlator,
        detector_version=args.detector_version or _core_version(),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    resolved = payload["manifests"][manifest_name(dist)]["resolved"]
    print(f"dependency-snapshot: {dist} -> {len(resolved)} package(s) in scope", file=sys.stderr)
    return 0


def _main_cyclonedx(slug: str) -> int:
    dist = installed_plugin_dist_name(slug)
    if dist is None:
        print(
            f"dependency-snapshot: no installed distribution for slug '{slug}' "
            f"(looked for both naming conventions) — the boot did not install the plugin this document is about",
            file=sys.stderr,
        )
        return 1
    document = build_cyclonedx(dist)
    print(json.dumps(document, indent=2, sort_keys=True))
    print(f"dependency-snapshot: {dist} -> {len(document['components'])} package(s) in scope", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
