"""SBOM generation lane — one derivation, two serializations, fail-closed gates.

Implements the generation half of spec-cicd-sbom.md against one verified per-arch
image digest (req-cicd-sbom-1/-2/-3/-5/-6, gates -7/-11):

 1. Load + JSON-Schema-validate the image's supplemental manifest (declared
    out-of-band components — req-cicd-sbom-3; schema beside this script), then
    DERIVE each copied-image component's version/source/purl from the Dockerfile
    ``COPY --from`` pin that lands it (tap#225): the manifest declares identity and
    rationale, the Dockerfile declares version and digest, and this joins them, so
    there is no second copy of the version to go stale.
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

Runs on the CI runner (publish-images.yml `sbom` job: read-only token, `uv run` with the
locked `ci-tooling` group; the first-party `attest-sbom` job signs, tap#507); unit-testable
pure functions, orchestration in main().
"""

# mypy: allow-untyped-defs, allow-any-generics
# ^ JSON-document plumbing at a system boundary (CLAUDE.md: Any is allowed at
#   system boundaries with justification): every structure here is a foreign
#   schema (CycloneDX/SPDX/syft output) validated by jsonschema, not by mypy.
from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
SYFT_IMAGE = "anchore/syft:v1.51.0@sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0"

# Scan-surface exclusions (req-cicd-sbom-2): the wheel-cache phantom inventory and
# the uv/uvx embedded cargo-auditable crate closures. The uv/uvx EXECUTABLES are
# declared components (supplemental manifest), only their embedded metadata is noise.
SYFT_EXCLUDES = ["/opt/uv-cache-seed/**", "/bin/uv", "/bin/uvx", "/usr/bin/uv", "/usr/bin/uvx"]

# Canary lists (req-cicd-sbom-7): TAP-specific truths. Required names are checked in
# addition to EVERY component of the supplemental manifest (a dropped declaration is
# a red publish). Forbidden names/locations are the known-phantom markers.
CANARIES = {
    # The four js-vendor libs prove the package-lock seam survived into the scan
    # (req-cicd-sbom-13); a lockfile that stopped being cataloged is a silent
    # closure loss, exactly the regression class canaries exist for.
    "tap-web": {"required": ["tap", "django", "openssl", "htmx.org", "echarts", "tabulator-tables", "cytoscape"]},
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


# ---------------------------------------------------------------------------
# Dockerfile COPY --from sites: parsed ONCE here, consumed by the reconciliation
# gate (oob_detect.check_dockerfile_sites) and by the copied-image derivation
# below. Two readers of the same fact, one parser.
# ---------------------------------------------------------------------------

# Annotation grammar: a DEFINED requirement id + a mandatory non-empty reason.
_ALLOW_RE = re.compile(r"#\s*sbom-allow\((?P<rid>req-[a-z0-9-]+)\)\s*:\s*\S")
# Dockerfile instructions are case-insensitive and flags may precede --from
# (--chown=... --from=...); parse accordingly, and fail CLOSED on any COPY
# that mentions --from but resists parsing (Codex finding on PR #115: a
# guard that recognizes only one spelling is a guard in name only).
_COPY_RE = re.compile(r"^\s*copy\s+(?P<rest>.+)$", re.IGNORECASE)
_FROM_FLAG_RE = re.compile(r"--from=(?P<src_stage>\S+)")
# A `--from=` value that is an UPSTREAM IMAGE rather than a build stage, pinned
# the way this repo pins them: repo:tag@sha256:<64 hex>. A build-stage name
# (`deps-warm`, `js-vendor`) does not match, and neither does a half-pinned ref
# — which is the point: the derivation below refuses to invent a version from a
# reference that does not state one.
_PINNED_IMAGE_RE = re.compile(
    r"^(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*)"
    r":(?P<version>[A-Za-z0-9._-]+)@(?P<digest>sha256:[0-9a-f]{64})$"
)


class CopySite(NamedTuple):
    """One ``COPY --from=`` instruction and how it accounts for itself."""

    dockerfile: str
    lineno: int
    src_stage: str
    sources: list[str]
    dest: str
    allow_rid: str | None

    def landed_paths(self) -> list[str]:
        """Absolute in-image paths this instruction lands — a dir destination expands per source."""
        if self.dest.endswith("/"):
            return [self.dest + Path(s).name for s in self.sources]
        return [self.dest]


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """(first_lineno, line) with backslash continuations joined — a COPY split
    across lines must parse as the single instruction Docker sees."""
    out: list[tuple[int, str]] = []
    pending: str | None = None
    pending_no = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip()
        if pending is not None:
            if stripped.endswith("\\"):
                pending = pending + " " + stripped[:-1].strip()
            else:
                out.append((pending_no, pending + " " + raw.strip()))
                pending = None
            continue
        if stripped.endswith("\\") and not raw.lstrip().startswith("#"):
            pending = stripped[:-1].strip()
            pending_no = lineno
            continue
        out.append((lineno, raw))
    if pending is not None:
        out.append((pending_no, pending))
    return out


def parse_copy_sites(dockerfile: Path) -> list[CopySite]:
    """Every COPY --from site, with any sbom-allow annotation from the preceding comment.

    Raises ValueError (fail-closed) on a COPY that mentions --from but cannot
    be parsed into sources + destination — an unrecognized spelling must never
    pass silently.
    """
    sites: list[CopySite] = []
    pending_allow: str | None = None
    for lineno, raw in _logical_lines(dockerfile.read_text(encoding="utf-8")):
        line = raw.strip()
        if line.startswith("#"):
            m = _ALLOW_RE.search(line)
            if m:
                pending_allow = m.group("rid")
            continue
        if not line:
            continue
        copy_m = _COPY_RE.match(line)
        if copy_m and "--from" in line:
            from_m = _FROM_FLAG_RE.search(line)
            if not from_m:
                raise ValueError(f"{dockerfile}:{lineno} COPY mentions --from in an unsupported form: {line!r}")
            rest = copy_m.group("rest")
            if "[" in rest:
                # JSON (exec) form: COPY --from=x ["src", "dest"]
                parsed = json.loads(rest[rest.index("[") :])
                args = [str(a) for a in parsed]
            else:
                args = [t for t in rest.split() if not t.startswith("--")]
            if len(args) < 2:
                raise ValueError(f"{dockerfile}:{lineno} COPY --from with unparseable args: {line!r}")
            sites.append(
                CopySite(
                    dockerfile=str(dockerfile),
                    lineno=lineno,
                    src_stage=from_m.group("src_stage"),
                    sources=args[:-1],
                    dest=args[-1],
                    allow_rid=pending_allow,
                )
            )
        # Any non-comment line consumes the pending annotation: it binds to the
        # NEXT instruction only, never floats down the file.
        pending_allow = None
    return sites


def derive_copied_image_facts(supplemental: dict[str, object], dockerfile: Path) -> dict[str, object]:
    """Fill in every ``copied-image`` component's version, source and purl FROM THE DOCKERFILE (tap#225).

    A ``COPY --from=ghcr.io/astral-sh/uv:0.12.15@sha256:…`` line already states the
    version and the digest of the bytes it lands. Declaring them a second time in the
    supplemental manifest created a copy that could be — and for four releases was —
    false: the published, attested SBOM asserted uv 0.12.3 while the image shipped
    0.12.15, because Renovate bumps the pin and nothing bumped the manifest.

    Remedy #1 of the derive > verify > detect order (CLAUDE.md, *presence is not
    correctness*): the second copy is REMOVED rather than reconciled, so it cannot
    drift. The manifest keeps what only a human can say — identity, path, license,
    rationale, and the version-free ``purl_base`` — and the Dockerfile keeps what it
    alone knows. Renovate's `dockerfile` manager bumps one pin; the SBOM follows.

    Fails closed (never a silent pass-through) when a declared copied-image path is
    landed by no ``COPY --from`` site, by more than one source, or by a reference that is
    not a fully pinned ``repo:tag@sha256:…`` image — and when a manifest hand-declares a
    field this function owns.

    **Why ambiguity is refused rather than resolved.** This parser reads instructions, not
    the stage graph: it does not know which ``FROM`` stage receives a ``COPY``, nor which
    stage is the build target. So when two sources write one path it cannot say which
    bytes ship, and a version taken from the wrong one is attested provenance over content
    it does not describe. Requiring a single writer removes the question instead of
    answering it with an assumption.

    Named residual (tap#643): the DIGEST is cryptographically bound to the bytes; the TAG
    is not. Nothing in the reference proves ``0.12.16`` is the version of the bytes behind
    that digest, so the version here is taken on trust from a string rather than observed
    from the artifact. Smaller than the lie it replaces — a hand-typed version related to
    nothing — and the digest still travels into the SBOM exactly, but not zero.

    Named residual (tap#642): a plain ``COPY`` from the build context — no ``--from``, so
    not a site this parser sees — that overwrites a declared path would leave a derived
    version describing replaced bytes. What such a copy CANNOT falsify is the component's
    sha256, which is read from the scanned image, so the drift is visible rather than
    silent. Neither shipped Dockerfile does this today.

    Returns the same manifest object, mutated in place.
    """
    # EVERY site that lands a path, pinned or not, in Dockerfile order. Filtering the
    # unpinned ones out here would describe the wrong bytes: a later
    # `COPY --from=builder /other /bin/uv` overwrites the pinned binary, and picking "the
    # pinned site" would publish the upstream image's version and digest for bytes that
    # never came from it (Codex seat, PR #627). The LAST producer wins, exactly as Docker
    # resolves it, and it must be fully pinned or the component is underivable.
    by_path: dict[str, list[CopySite]] = {}
    for site in parse_copy_sites(dockerfile):
        for path in site.landed_paths():
            by_path.setdefault(path, []).append(site)

    problems: list[str] = []
    components = supplemental["components"]
    if not isinstance(components, list):  # deterministic raise, not assert (vanishes under -O)
        raise TypeError(f"supplemental components is {type(components).__name__}, expected list")
    for comp in components:
        if comp.get("source_kind") != "copied-image":
            continue
        name, path = comp.get("name", "?"), comp.get("path")
        declared = [f for f in ("version", "source", "purl") if f in comp]
        if declared:
            problems.append(
                f"{name}: declares {', '.join(declared)} — a copied-image component's version, source "
                f"and purl are DERIVED from the Dockerfile COPY --from pin that lands {path}, never "
                f"authored here (tap#225). Remove the field(s); keep 'purl_base'."
            )
            continue
        sites = by_path.get(str(path), [])
        if not sites:
            problems.append(
                f"{name}: no 'COPY --from' site in {dockerfile} lands {path} — its version cannot be "
                f"derived, and a copied-image component whose provenance is NOT OBSERVABLE must not "
                f"be published as though it were known"
            )
            continue
        refs = {s.src_stage for s in sites}
        if len(refs) > 1:
            # Two or more different sources write this path. Which one ships depends on
            # the stage graph and on which stage is the build target — neither of which
            # this parser models, so the honest answer is "cannot prove it" and the
            # publish stops. Refusing on ambiguity is stronger than picking the textually
            # last site AND makes the stage question moot: whatever the graph looks like,
            # a single writer is the only shape that has one answer (Codex seat, PR #627).
            where = ", ".join(f"{dockerfile}:{s.lineno} --from={s.src_stage}" for s in sites)
            problems.append(
                f"{name}: {path} is written by {len(refs)} different sources — {where}. Which one "
                f"lands in the published stage is not derivable from COPY order alone, and a version "
                f"guessed from the wrong one is attested provenance over bytes it does not describe"
            )
            continue
        producer = sites[0]
        pinned = _PINNED_IMAGE_RE.match(producer.src_stage)
        if pinned is None:
            problems.append(
                f"{name}: the site landing {path} is {dockerfile}:{producer.lineno} "
                f"'--from={producer.src_stage}', which is not a fully pinned "
                f"<repo>:<tag>@sha256:<digest> image — it states no version to derive"
            )
            continue
        comp["version"] = pinned.group("version")
        comp["source"] = producer.src_stage
        if "purl_base" in comp:
            comp["purl"] = f"{comp['purl_base']}@{pinned.group('version')}"
    if problems:
        fail(problems, "derive-copied-image")
    return supplemental


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


@functools.cache
def _fips_pins() -> Any:
    """Load `tap/fips_pins.py` by path (stdlib-only, settings-free) — the one derivation of whether
    the pinned provider is CMVP-validated. Loaded by file so this script needs no `tap` import."""
    spec = importlib.util.spec_from_file_location("tap_fips_pins", _REPO_ROOT / "tap" / "fips_pins.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load tap/fips_pins.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


#: A release version as these fields spell it: 3.0.22, 3.1.2a.
_VERSION_TOKEN_RE = re.compile(r"\d+\.\d+\.\d+[a-z]*")


def _asserted_versions(comp: dict) -> list[tuple[str, str, str | None]]:
    """(label, field, the version that field ACTUALLY asserts) for each version-bearing field.

    Parsed per field's own grammar, because what a matcher reads is a specific position in
    a specific string — not "somewhere in the text":

    * ``purl`` — the ``@<version>`` between the name and any ``?qualifiers``. A purl with
      no version asserts ``None``, which is a red: it is a purl no feed can resolve.
    * ``cpe``  — CPE 2.3 field 5 (``cpe:2.3:<part>:<vendor>:<product>:<version>:…``), the
      field NVD-backed matchers key on.
    * ``source`` — a URL with no single version slot, so EVERY release-version token in it
      must be the pin (the tarball path and the filename each carry one). A stale primary
      with the pin hidden in a query string fails here rather than passing on presence.
    """
    out: list[tuple[str, str, str | None]] = []
    purl = comp.get("purl")
    if purl is not None:
        head, _, qualifiers = str(purl).split("#", 1)[0].partition("?")
        out.append(("purl version", "purl", head.rsplit("@", 1)[1] if "@" in head else None))
        # A purl qualifier can carry a whole download URL (this one does), so it gets the
        # same every-token treatment `source` gets — a stale URL smuggled into a qualifier
        # is the same lie in a quieter place.
        out += [("purl qualifier", "purl", t) for t in _VERSION_TOKEN_RE.findall(qualifiers)]
    cpe = comp.get("cpe")
    if cpe is not None:
        parts = str(cpe).split(":")
        out.append(("cpe version field", "cpe", parts[5] if len(parts) > 5 else None))
    source = comp.get("source")
    if source is not None:
        tokens = _VERSION_TOKEN_RE.findall(str(source))
        out += [("source", "source", t) for t in tokens] or [("source", "source", None)]
    return out


def fips_validation_property(comp: dict, *, pins_module: Any | None = None) -> dict[str, str] | None:
    """For the self-built FIPS provider component (the one declared at the provider's install
    path): a `tap:fips-validation` property DERIVED from the pin (req-fips-pin-currency-8) —
    never from the manifest's prose. Fails closed when the pins are unreadable, when the
    manifest's declared version is not the pinned one, or when its `_description` hand-writes
    a certificate that disagrees with the derivation: a present-but-false validation claim in
    the published SBOM is exactly the record nobody re-checks."""
    pins_mod = pins_module or _fips_pins()
    if comp.get("path") != pins_mod.PROVIDER_PATH:
        return None
    missing = [k for k in ("name", "version") if k not in comp]
    if missing:
        fail([f"provider component at {comp['path']} is missing {', '.join(missing)}"], "fips-validation")
    try:
        pins = pins_mod.read_pins()
    except pins_mod.PinsUnreadable as exc:
        fail([f"{comp['name']}: FIPS pins NOT OBSERVABLE — {exc}"], "fips-validation")
    if comp["version"] != pins.version:
        fail(
            [f"{comp['name']} declares version {comp['version']} but docker/build-openssl-fips.sh pins {pins.version}"],
            "fips-validation",
        )
    # The version-BEARING identity fields too, not just `version` (tap#225). The
    # release URL, the purl's download_url and the CPE each spell the version out,
    # and a declared-but-stale CPE is the worst of the three: it silently matches the
    # advisory feed for a version the image does not ship. This is remedy #2 (verify),
    # deliberately, where the copied-image components get remedy #1 (derive): the URL
    # shape is authored once in docker/build-openssl-fips.sh (BASE_URL/TARBALL, built
    # from OSSL_VERSION), and restating that construction in Python would trade one
    # duplicate for another across a language boundary. The fact that actually drifts
    # — the version — is derived; these are checked against it and fail closed.
    #
    # Each field is PARSED for the version it actually asserts, never substring-searched.
    # A substring test is the very defect this file is fixing wearing the fix's clothes:
    # `pkg:generic/openssl@0.0.0?download_url=...-3.0.22.tar.gz` contains the pin and
    # still tells every matcher to look up 0.0.0 (Codex seat, PR #627).
    problems = [
        f"{comp['name']}: {label} asserts version {claimed!r}, but docker/build-openssl-fips.sh "
        f"pins {pins.version} — {comp[field]!r}"
        for label, field, claimed in _asserted_versions(comp)
        if claimed != pins.version
    ]
    if problems:
        fail(problems, "fips-validation")
    cert = pins.validation.certificate if pins.validation else None
    prose = comp.get("_description", "")
    for claimed in pins_mod.CLAIM_RE.findall(prose):
        if claimed != cert:
            fail(
                [f"{comp['name']}: _description claims CMVP #{claimed}; the pin derives {pins.status_clause()!r}"],
                "fips-validation",
            )
    if cert is None and pins_mod.VALIDATED_PHRASE_RE.search(prose):
        fail(
            [f"{comp['name']}: _description says 'FIPS-validated'; the pin derives {pins.status_clause()!r}"],
            "fips-validation",
        )
    return {"name": "tap:fips-validation", "value": pins.status_clause()}


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
        validation = fips_validation_property(comp)
        if validation is not None:
            entry["properties"].append(validation)
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


def _pep503(name: str) -> str:
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def derive_source_built(pyproject_path: Path, lock_path: Path, *, root: Path | None = None) -> dict[str, str]:
    """The built-from-source set, DERIVED never declared (req-cicd-sbom-12):
    [tool.uv] no-binary-package forces sdist builds (the FIPS --no-binary
    discipline), and a lock entry with an sdist but zero wheels is source-built
    everywhere by necessity. Returns PEP 503-normalized name -> reason."""
    import tomllib

    # Boundary validation (the SonarCloud agentic path-traversal rule, and the
    # right edge regardless): these paths arrive as CLI arguments in the
    # privileged publish job — they must stay inside the working tree the job
    # checked out, never wander the runner's filesystem.
    root = (root if root is not None else Path.cwd()).resolve()
    for candidate in (pyproject_path, lock_path):
        if not candidate.resolve().is_relative_to(root):
            raise ValueError(f"derivation input {candidate} escapes the working tree {root}")

    out: dict[str, str] = {}
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    for name in pyproject.get("tool", {}).get("uv", {}).get("no-binary-package", []):
        out[_pep503(name)] = "forced sdist build: [tool.uv] no-binary-package (pyproject.toml)"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    for pkg in lock.get("package", []):
        if "sdist" in pkg and not pkg.get("wheels"):
            out.setdefault(_pep503(pkg["name"]), "sdist-only distribution: no wheels published (uv.lock)")
    return out


def mark_source_built(cdx: dict, spdx: dict, source_built: dict[str, str]) -> list[str]:
    """Mark derived source-built members in BOTH serializations; fail closed on a
    derived name absent from the scan (the closure changed shape under us —
    the same red a dropped canary raises)."""
    problems: list[str] = []
    cdx_seen: set[str] = set()
    for comp in cdx.get("components", []):
        norm = _pep503(comp.get("name", ""))
        if norm in source_built:
            comp.setdefault("properties", []).extend(
                [
                    {"name": "tap:source-built", "value": "true"},
                    {"name": "tap:source-built-reason", "value": source_built[norm]},
                ]
            )
            cdx_seen.add(norm)
    for pkg in spdx.get("packages", []):
        norm = _pep503(pkg.get("name", ""))
        if norm in source_built:
            note = f"tap:source-built — {source_built[norm]}"
            pkg["comment"] = f"{pkg['comment']} | {note}" if pkg.get("comment") else note
    for norm in sorted(set(source_built) - cdx_seen):
        problems.append(
            f"derived source-built member ABSENT from the scan: {norm} ({source_built[norm]}) — "
            f"the Python closure changed shape; never resolve this by hand-editing the derivation"
        )
    return problems


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
                # Declared-closure catalogers on top of the image defaults:
                # uv.lock (python) and /opt/tap-static-vendor/package-lock.json
                # (the js-vendor closure, req-cicd-sbom-13) are both lockfile
                # seams — the locked truth IS the artifact's inventory.
                "+python-package-cataloger,+javascript-lock-cataloger",
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
    ap.add_argument(
        "--dockerfile",
        required=True,
        type=Path,
        help="the Dockerfile that builds this image — the authoring site for every copied-image "
        "component's version and digest (req-cicd-sbom-3, tap#225)",
    )
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)

    subject = f"{args.ref}@{args.digest}"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_cdx = args.out_dir / f"{args.image}-{args.arch}.cdx.json"
    out_spdx = args.out_dir / f"{args.image}-{args.arch}.spdx.json"

    supplemental = derive_copied_image_facts(load_supplemental(args.supplemental), args.dockerfile)
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

    if args.image == "tap-web":
        # Source-built derivation inputs (req-cicd-sbom-12) are CONSTANTS at the
        # repo-root cwd the publish job runs in — deliberately not CLI knobs:
        # nothing ever needed to vary them, and a user-controlled path into a
        # privileged job's read is a taint source with no upside (SonarCloud
        # S8707; tests exercise derive_source_built directly with their own
        # root). Only tap-web carries the Python closure.
        source_built = derive_source_built(Path("pyproject.toml"), Path("uv.lock"))
        problems = mark_source_built(cdx, spdx, source_built)
        if problems:
            fail(problems, "source-built")
        print(f"sbom-generate: marked {len(source_built)} source-built member(s): {sorted(source_built)}")

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
