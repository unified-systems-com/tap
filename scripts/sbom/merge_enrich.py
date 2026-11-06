"""Merge scanner output and public vulnerability facts into the next revision of an SBOM (req-cicd-sbom-18, -20).

Inputs, all in the fixed directory `scan-inputs/` of the working directory (no path comes from the command line
or from the documents):

    sbom.cdx.json   the verified highest revision of the image's SBOM (revision N)
    grype.json      Grype's NATIVE JSON for that SBOM (it carries the GHSA/CVE aliases, EPSS and KEV that its
                    CycloneDX output drops: req-cicd-sbom-18-7)
    kev.json        CISA's Known Exploited Vulnerabilities catalog, as fetched by the unsigned scan job
    cve.json        one object mapping CVE id to its CVE Program JSON 5 record, as fetched by the scan job
    ghsa.json       one object mapping GHSA id to its GitHub advisory (REST `advisories` shape), as fetched by the scan job
    meta.json       scan time, the digest of the attestation the input was verified from, and fetch times

Output: the next revision on stdout (the SAME serialNumber, `version` + 1, the components unchanged, one
`vulnerabilities` entry per canonical vulnerability and component), a summary on stderr, and an exit code:

    0  a new revision was written to stdout
    3  the facts did not change; nothing is written (req-cicd-sbom-20-11, publish only on change)
    2  the merge could not be done (a required input is missing or unreadable): the stage fails

This runs in the first-party sealing job and reads only what the scan job left, so it needs no network
(req-cicd-sbom-18-8). The join to the SBOM is by purl, never by `bom-ref`, because Grype regenerates the refs
(req-cicd-sbom-18-1). A source that could not be read is recorded as not observed, never as "not KEV" or "no
score" (req-cicd-sbom-18-6).
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

INPUT_DIR = Path("scan-inputs")
VERDICT_EXIT = {"changed": 0, "unchanged": 3, "failed": 2}

#: CycloneDX rating methods for the CVSS versions Grype and the CVE record name.
_GRYPE_CVSS_METHOD = {"2.0": "CVSSv2", "3.0": "CVSSv3", "3.1": "CVSSv31", "4.0": "CVSSv4"}
_RECORD_CVSS_METHOD = {"cvssV2_0": "CVSSv2", "cvssV3_0": "CVSSv3", "cvssV3_1": "CVSSv31", "cvssV4_0": "CVSSv4"}

#: Properties and ratings that change without the facts changing; they are left out of the change test.
_VOLATILE_PROPERTY_PREFIXES = (
    "tap:epss:",
    "tap:kev:catalog-version",
    "tap:kev:date-released",
    "tap:kev:fetched-at",
    "tap:cve-record:fetched-at",
    "tap:cve-record:date-updated",
)


class MergeError(Exception):
    """A required input is missing or unusable: the stage fails (req-cicd-sbom-17-3)."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Source:
    """One optional input: its parsed content and digest, or the reason it is not observed."""

    def __init__(self, data: Any = None, digest: str | None = None, reason: str | None = None) -> None:
        self.data = data
        self.digest = digest
        self.reason = reason

    @property
    def observed(self) -> bool:
        return self.reason is None


def read_required(name: str) -> tuple[Any, str]:
    try:
        raw = (INPUT_DIR / name).read_bytes()
        return json.loads(raw), _sha256(raw)
    except (OSError, ValueError) as exc:
        raise MergeError(f"required input {name} cannot be read: {exc}") from exc


def read_optional(name: str) -> Source:
    try:
        raw = (INPUT_DIR / name).read_bytes()
        return Source(json.loads(raw), _sha256(raw))
    except (OSError, ValueError) as exc:
        return Source(reason=f"{name} cannot be read: {type(exc).__name__}")


def check_kev(source: Source) -> Source:
    """A catalog without its version stamp, release time or entries is not trusted (req-cicd-sbom-21 echoes this)."""
    if not source.observed:
        return source
    catalog = source.data
    if not (
        isinstance(catalog, dict)
        and catalog.get("catalogVersion")
        and catalog.get("dateReleased")
        and isinstance(catalog.get("vulnerabilities"), list)
        and catalog["vulnerabilities"]
    ):
        return Source(reason="kev.json lacks catalogVersion, dateReleased or entries")
    return source


def check_cve(source: Source) -> Source:
    if source.observed and not isinstance(source.data, dict):
        return Source(reason="cve.json is not an object")
    return source


def check_ghsa(source: Source) -> Source:
    if source.observed and not isinstance(source.data, dict):
        return Source(reason="ghsa.json is not an object")
    return source


# ---------------------------------------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------------------------------------


def _alias_source(identifier: str) -> str:
    if identifier.startswith("CVE-"):
        return "NVD"
    if identifier.startswith("GHSA-"):
        return "GitHub Advisory Database"
    return "other"


def canonical_and_aliases(match: dict[str, Any]) -> tuple[str, list[str]]:
    """The CVE id when any alias is a CVE, otherwise the scanner's own id; every other id is an alias."""
    vulnerability = match["vulnerability"]
    ids = [vulnerability["id"], *(rel["id"] for rel in match.get("relatedVulnerabilities") or [])]
    cves = sorted({i for i in ids if i.startswith("CVE-")})
    if vulnerability["id"].startswith("CVE-"):
        canonical = vulnerability["id"]
    elif cves:
        canonical = cves[0]
    else:
        canonical = vulnerability["id"]
    return canonical, sorted({i for i in ids if i != canonical})


def _purl_key(purl: str) -> str:
    """Compare purls without being fooled by qualifier order or case of the type/name."""
    base, _, query = purl.partition("?")
    return base.lower() + "?" + "&".join(sorted(query.split("&"))) if query else base.lower()


class ComponentIndex:
    """purl (exact, then normalized) and name+version to the revision-1 `bom-ref` (req-cicd-sbom-18-9)."""

    def __init__(self, components: list[dict[str, Any]]) -> None:
        self.exact: dict[str, str] = {}
        self.normalized: dict[str, str] = {}
        self.by_name: dict[tuple[str, str], str] = {}
        for component in components:
            ref = component.get("bom-ref")
            if not ref:
                continue
            if component.get("purl"):
                self.exact[component["purl"]] = ref
                self.normalized[_purl_key(component["purl"])] = ref
            self.by_name[(str(component.get("name")), str(component.get("version")))] = ref

    def ref_for(self, artifact: dict[str, Any]) -> str:
        purl = artifact.get("purl")
        if purl and purl in self.exact:
            return self.exact[purl]
        if purl and _purl_key(purl) in self.normalized:
            return self.normalized[_purl_key(purl)]
        key = (str(artifact.get("name")), str(artifact.get("version")))
        if key in self.by_name:
            return self.by_name[key]
        raise MergeError(f"the scanner reported a component that is not in the SBOM: {purl or key}")


# ---------------------------------------------------------------------------------------------------------
# Ratings and facts
# ---------------------------------------------------------------------------------------------------------


def _severity(score: float) -> str:
    if score == 0:
        return "none"
    if score < 4:
        return "low"
    if score < 7:
        return "medium"
    if score < 9:
        return "high"
    return "critical"


def _rating_key(rating: dict[str, Any]) -> tuple[Any, ...]:
    return (
        (rating.get("source") or {}).get("name"),
        rating.get("method"),
        rating.get("vector"),
        rating.get("score"),
    )


def _grype_cvss_ratings(vulnerability: dict[str, Any]) -> list[dict[str, Any]]:
    ratings: list[dict[str, Any]] = []
    for cvss in vulnerability.get("cvss") or []:
        method = _GRYPE_CVSS_METHOD.get(str(cvss.get("version")))
        score = (cvss.get("metrics") or {}).get("baseScore")
        if method is None or score is None:
            continue
        source: dict[str, Any] = {"name": vulnerability.get("namespace") or "grype"}
        if vulnerability.get("dataSource"):
            source["url"] = vulnerability["dataSource"]
        ratings.append(
            {
                "source": source,
                "score": score,
                "severity": _severity(float(score)),
                "method": method,
                "vector": cvss.get("vector"),
            }
        )
    return ratings


def _record_containers(record: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    containers = record.get("containers") or {}
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(containers.get("cna"), dict):
        found.append(((containers["cna"].get("providerMetadata") or {}).get("shortName") or "CNA", containers["cna"]))
    for adp in containers.get("adp") or []:
        if isinstance(adp, dict):
            found.append(((adp.get("providerMetadata") or {}).get("shortName") or "ADP", adp))
    return found


def record_facts(record: dict[str, Any]) -> dict[str, Any]:
    """CVSS ratings, CWE numbers and the CISA-ADP SSVC assessment of a CVE JSON 5 record."""
    ratings: list[dict[str, Any]] = []
    cwes: set[int] = set()
    ssvc: dict[str, Any] | None = None
    for provider, container in _record_containers(record):
        for metric in container.get("metrics") or []:
            for key, method in _RECORD_CVSS_METHOD.items():
                block = metric.get(key)
                if isinstance(block, dict) and block.get("baseScore") is not None:
                    ratings.append(
                        {
                            "source": {"name": provider},
                            "score": block["baseScore"],
                            "severity": str(block.get("baseSeverity") or _severity(float(block["baseScore"]))).lower(),
                            "method": method,
                            "vector": block.get("vectorString"),
                        }
                    )
            other = metric.get("other")
            if provider == "CISA-ADP" and isinstance(other, dict) and other.get("type") == "ssvc":
                ssvc = other.get("content") if isinstance(other.get("content"), dict) else None
        for problem in container.get("problemTypes") or []:
            for description in problem.get("descriptions") or []:
                cwe_id = str(description.get("cweId") or "")
                if cwe_id.startswith("CWE-") and cwe_id[4:].isdigit():
                    cwes.add(int(cwe_id[4:]))
    containers = record.get("containers") or {}
    cna: dict[str, Any] = containers["cna"] if isinstance(containers.get("cna"), dict) else {}
    description = next(
        (
            str(d.get("value"))
            for d in cna.get("descriptions") or []
            if isinstance(d, dict) and str(d.get("lang", "")).lower().startswith("en") and d.get("value")
        ),
        None,
    )
    record_meta: dict[str, Any] = record.get("cveMetadata") or {}
    return {
        "ratings": ratings,
        "cwes": cwes,
        "ssvc": ssvc,
        "published": record_meta.get("datePublished"),
        "updated": record_meta.get("dateUpdated"),
        "title": cna.get("title"),
        "description": description,
    }


def ghsa_facts(advisory: dict[str, Any]) -> dict[str, Any]:
    """Published and updated time, summary, description and page of a GitHub advisory (the REST `advisories` shape)."""
    return {
        "published": advisory.get("published_at"),
        "updated": advisory.get("updated_at"),
        "title": advisory.get("summary"),
        "description": advisory.get("description"),
        "url": advisory.get("html_url"),
    }


def _ssvc_options(ssvc: dict[str, Any]) -> dict[str, str]:
    options: dict[str, str] = {}
    for option in ssvc.get("options") or []:
        if isinstance(option, dict):
            options.update({str(k): str(v) for k, v in option.items()})
    return options


def _prop(name: str, value: object) -> dict[str, str]:
    return {"name": name, "value": str(value)}


def _kev_entry(catalog: dict[str, Any], aliases: list[str]) -> tuple[str, dict[str, Any]] | None:
    wanted = {i for i in aliases if i.startswith("CVE-")}
    for entry in sorted(catalog["vulnerabilities"], key=lambda e: str(e.get("cveID"))):
        if entry.get("cveID") in wanted:
            return str(entry["cveID"]), entry
    return None


class EntryBuilder:
    """Accumulates one merged vulnerability entry from one or more scanner matches."""

    def __init__(self, canonical: str, ref: str, version: str) -> None:
        self.canonical = canonical
        self.ref = ref
        self.version = version
        self.aliases: set[str] = set()
        self.ratings: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.cwes: set[int] = set()
        self.description: str | None = None
        self.source: dict[str, Any] | None = None
        self.fix_versions: set[str] = set()
        self.fix_state: str | None = None
        self.epss: list[dict[str, Any]] = []
        self.grype_kev: list[dict[str, Any]] = []

    def add_match(self, match: dict[str, Any], aliases: list[str]) -> None:
        vulnerability = match["vulnerability"]
        self.aliases.update(aliases)
        for rating in _grype_cvss_ratings(vulnerability):
            self.ratings.setdefault(_rating_key(rating), rating)
        for related in match.get("relatedVulnerabilities") or []:
            for rating in _grype_cvss_ratings(related):
                self.ratings.setdefault(_rating_key(rating), rating)
        for cwe in vulnerability.get("cwes") or []:
            text = str(cwe.get("cwe") if isinstance(cwe, dict) else cwe)
            if text.startswith("CWE-") and text[4:].isdigit():
                self.cwes.add(int(text[4:]))
        self.description = self.description or vulnerability.get("description")
        if self.source is None:
            self.source = {"name": vulnerability.get("namespace") or "grype"}
            if vulnerability.get("dataSource"):
                self.source["url"] = vulnerability["dataSource"]
        fix = vulnerability.get("fix") or {}
        self.fix_versions.update(str(v) for v in fix.get("versions") or [])
        self.fix_state = self.fix_state or fix.get("state")
        self.epss += [e for e in vulnerability.get("epss") or [] if isinstance(e, dict)]
        self.grype_kev += [k for k in vulnerability.get("knownExploited") or [] if isinstance(k, dict)]


def _kev_facts(
    builder: EntryBuilder, kev: Source, meta: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    ratings: list[dict[str, Any]] = []
    props: list[dict[str, str]] = []
    aliases = [builder.canonical, *sorted(builder.aliases)]
    catalog_hit = _kev_entry(kev.data, aliases) if kev.observed else None
    if catalog_hit is not None:
        cve, entry = catalog_hit
        origin = "catalog"
    elif builder.grype_kev:
        # The scanner's own database lists it and the fetched catalog does not (a stale catalog): union, never a miss.
        entry = builder.grype_kev[0]
        cve = str(entry.get("cve"))
        origin = "grype"
    else:
        entry = {}
        cve = ""
        origin = ""
    if not entry:
        listed = "false" if kev.observed else "not-observed"
        return ratings, [_prop("tap:kev:listed", listed)]
    ratings.append(
        {
            "source": {"name": "CISA KEV Catalog"},
            "score": 1,
            "method": "other",
            "justification": "Listed in CISA KEV",
        }
    )
    props += [
        _prop("tap:kev:listed", "true"),
        _prop("tap:kev:source", origin),
        _prop("tap:kev:matched-id", cve),
        _prop("tap:kev:date-added", entry.get("dateAdded", "")),
        _prop("tap:kev:due-date", entry.get("dueDate", "")),
        _prop("tap:kev:required-action", entry.get("requiredAction", "")),
        _prop("tap:kev:ransomware-use", entry.get("knownRansomwareCampaignUse", "")),
    ]
    if kev.observed:
        props += [
            _prop("tap:kev:catalog-version", kev.data["catalogVersion"]),
            _prop("tap:kev:date-released", kev.data["dateReleased"]),
            _prop("tap:kev:fetched-at", (meta.get("kev") or {}).get("fetched_at", "")),
        ]
    return ratings, props


def build_entry(
    builder: EntryBuilder, kev: Source, cve: Source, ghsa: Source, meta: dict[str, Any], grype_version: str
) -> dict[str, Any]:
    ratings = dict(builder.ratings)
    published: str | None = None
    updated: str | None = None
    title: str | None = None
    described: str | None = None
    advisories: list[dict[str, str]] = []
    cwes = set(builder.cwes)
    properties: list[dict[str, str]] = []

    kev_ratings, kev_props = _kev_facts(builder, kev, meta)
    for rating in kev_ratings:
        ratings.setdefault(_rating_key(rating), rating)
    properties += kev_props

    epss_pick = next(
        (e for e in builder.epss if e.get("cve") == builder.canonical), builder.epss[0] if builder.epss else None
    )
    if epss_pick is not None and epss_pick.get("epss") is not None:
        rating = {"source": {"name": "FIRST"}, "score": epss_pick["epss"], "method": "other", "justification": "EPSS"}
        ratings.setdefault(_rating_key(rating), rating)
        properties += [
            _prop("tap:epss:percentile", epss_pick.get("percentile", "")),
            _prop("tap:epss:date", epss_pick.get("date", "")),
        ]

    cve_ids = [i for i in [builder.canonical, *sorted(builder.aliases)] if i.startswith("CVE-")]
    if cve_ids:
        if not cve.observed:
            properties.append(_prop("tap:cve-record:status", "not-observed"))
        else:
            hit = next((i for i in cve_ids if isinstance(cve.data.get(i), dict)), None)
            if hit is None:
                properties.append(_prop("tap:cve-record:status", "not-observed"))
            else:
                record = cve.data[hit]
                facts = record_facts(record)
                published, updated, title, described = (
                    facts["published"],
                    facts["updated"],
                    facts["title"],
                    facts["description"],
                )
                advisories.append({"title": "CVE Record", "url": f"https://www.cve.org/CVERecord?id={hit}"})
                for rating in facts["ratings"]:
                    ratings.setdefault(_rating_key(rating), rating)
                cwes |= facts["cwes"]
                properties += [
                    _prop("tap:cve-record:status", "observed"),
                    _prop("tap:cve-record:id", hit),
                    _prop("tap:cve-record:fetched-at", (meta.get("cve") or {}).get("fetched_at", "")),
                ]
                updated = (record.get("cveMetadata") or {}).get("dateUpdated")
                if updated:
                    properties.append(_prop("tap:cve-record:date-updated", updated))
                if facts["ssvc"] is not None:
                    options = _ssvc_options(facts["ssvc"])
                    vector = "/".join(f"{k}:{v}" for k, v in options.items())
                    ratings.setdefault(
                        ("CISA-ADP", "SSVC", vector, None),
                        {
                            "source": {"name": "CISA-ADP"},
                            "method": "SSVC",
                            "vector": vector,
                            "justification": f"SSVC {facts['ssvc'].get('version', '?')} assessed {facts['ssvc'].get('timestamp', '?')}",
                        },
                    )
                    properties += [
                        _prop("tap:ssvc:exploitation", options.get("Exploitation", "")),
                        _prop("tap:ssvc:automatable", options.get("Automatable", "")),
                        _prop("tap:ssvc:technical-impact", options.get("Technical Impact", "")),
                        _prop("tap:ssvc:assessed-at", facts["ssvc"].get("timestamp", "")),
                        _prop("tap:ssvc:version", facts["ssvc"].get("version", "")),
                    ]

    ghsa_ids = [i for i in [builder.canonical, *sorted(builder.aliases)] if i.startswith("GHSA-")]
    if ghsa_ids:
        if not ghsa.observed:
            properties.append(_prop("tap:ghsa:status", "not-observed"))
        else:
            seen = [(i, ghsa.data.get(i)) for i in ghsa_ids if isinstance(ghsa.data.get(i), dict)]
            if not seen:
                properties.append(_prop("tap:ghsa:status", "not-observed"))
            for ghsa_id, advisory in seen:
                g = ghsa_facts(advisory)
                published = published or g["published"]
                updated = updated or g["updated"]
                title = title or g["title"]
                described = described or g["description"]
                advisories.append(
                    {"title": "GitHub Advisory", "url": g["url"] or f"https://github.com/advisories/{ghsa_id}"}
                )
            if seen:
                properties.append(_prop("tap:ghsa:status", "observed"))
    if title:
        properties.append(_prop("tap:title", title))
    properties.append(_prop("tap:fix:state", builder.fix_state or "unknown"))
    if builder.fix_versions:
        properties.append(_prop("tap:fix:versions", ",".join(sorted(builder.fix_versions))))

    entry: dict[str, Any] = {
        "id": builder.canonical,
        "source": builder.source or {"name": "grype"},
        "references": [{"id": a, "source": {"name": _alias_source(a)}} for a in sorted(builder.aliases)],
        "ratings": sorted(ratings.values(), key=lambda r: json.dumps(_rating_key(r), sort_keys=True, default=str)),
        "cwes": sorted(cwes),
        "affects": [{"ref": builder.ref, "versions": [{"version": builder.version, "status": "affected"}]}],
        "properties": properties,
        "tools": {"components": [{"type": "application", "name": "grype", "version": grype_version}]},
    }
    if builder.description or described:
        entry["description"] = builder.description or described
    if published:
        entry["published"] = published
    if updated:
        entry["updated"] = updated
    if advisories:
        entry["advisories"] = advisories
    if builder.fix_versions:
        entry["recommendation"] = "Upgrade to " + ", ".join(sorted(builder.fix_versions))
    return entry


# ---------------------------------------------------------------------------------------------------------
# The revision
# ---------------------------------------------------------------------------------------------------------


def _replace_properties(metadata: dict[str, Any], prefixes: tuple[str, ...], added: list[dict[str, str]]) -> None:
    kept = [p for p in metadata.get("properties") or [] if not str(p.get("name", "")).startswith(prefixes)]
    metadata["properties"] = kept + added


def _add_tool(metadata: dict[str, Any], name: str, version: str) -> None:
    tool = {"type": "application", "name": name, "version": version}
    tools = metadata.get("tools")
    if isinstance(tools, list):
        if not any(t.get("name") == name and t.get("version") == version for t in tools):
            tools.append({"vendor": "anchore", "name": name, "version": version})
        return
    if not isinstance(tools, dict):
        tools = {}
        metadata["tools"] = tools
    components = tools.setdefault("components", [])
    if not any(c.get("name") == name and c.get("version") == version for c in components):
        components.append(tool)


def merge(
    base: dict[str, Any],
    base_digest: str,
    grype: dict[str, Any],
    grype_digest: str,
    kev: Source,
    cve: Source,
    ghsa: Source,
    meta: dict[str, Any],
) -> dict[str, Any]:
    """The next revision of `base`. Pure: all inputs are values, the clock is `meta["scan_time"]`."""
    if base.get("bomFormat") != "CycloneDX" or not base.get("serialNumber") or not isinstance(base.get("version"), int):
        raise MergeError("the input SBOM is not a CycloneDX document with a serialNumber and an integer version")
    for field in ("scan_time",):
        if not meta.get(field):
            raise MergeError(f"meta.json lacks {field}")
    descriptor = grype.get("descriptor") or {}
    grype_version = str(descriptor.get("version") or "")
    if descriptor.get("name") != "grype" or not grype_version:
        raise MergeError("grype.json is not Grype's native JSON (no descriptor)")
    db_info = descriptor.get("db") or {}
    status = db_info.get("status")
    db: dict[str, Any] = status if isinstance(status, dict) else db_info  # real output nests it under status

    index = ComponentIndex(base.get("components") or [])
    builders: dict[tuple[str, str], EntryBuilder] = {}
    for match in grype.get("matches") or []:
        canonical, aliases = canonical_and_aliases(match)
        artifact = match["artifact"]
        ref = index.ref_for(artifact)
        builder = builders.setdefault((canonical, ref), EntryBuilder(canonical, ref, str(artifact.get("version"))))
        builder.add_match(match, aliases)

    doc = copy.deepcopy(base)
    doc["version"] = base["version"] + 1  # the SAME serialNumber, carried from the verified input (req-cicd-sbom-20-3)
    doc["vulnerabilities"] = [
        build_entry(builders[key], kev, cve, ghsa, meta, grype_version) for key in sorted(builders)
    ]

    metadata = doc.setdefault("metadata", {})
    metadata["timestamp"] = meta["scan_time"]
    _add_tool(metadata, "grype", grype_version)
    source_props = [_prop("tap:source:grype:sha256", grype_digest)]
    if kev.observed:
        source_props += [
            _prop("tap:kev:status", "observed"),
            _prop("tap:source:kev:sha256", kev.digest or ""),
            _prop("tap:kev:catalog-version", kev.data["catalogVersion"]),
            _prop("tap:kev:date-released", kev.data["dateReleased"]),
            _prop("tap:kev:fetched-at", (meta.get("kev") or {}).get("fetched_at", "")),
        ]
    else:
        source_props += [_prop("tap:kev:status", "not-observed"), _prop("tap:kev:reason", kev.reason or "")]
    if cve.observed:
        source_props += [
            _prop("tap:cve-records:status", "observed"),
            _prop("tap:source:cve-records:sha256", cve.digest or ""),
        ]
    else:
        source_props += [
            _prop("tap:cve-records:status", "not-observed"),
            _prop("tap:cve-records:reason", cve.reason or ""),
        ]
    if ghsa.observed:
        source_props += [
            _prop("tap:ghsa-advisories:status", "observed"),
            _prop("tap:source:ghsa-advisories:sha256", ghsa.digest or ""),
        ]
    else:
        source_props += [
            _prop("tap:ghsa-advisories:status", "not-observed"),
            _prop("tap:ghsa-advisories:reason", ghsa.reason or ""),
        ]
    _replace_properties(
        metadata,
        ("tap:scan:", "tap:revision:", "tap:source:", "tap:kev:", "tap:cve-records:", "tap:ghsa-advisories:"),
        [
            _prop("tap:revision:previous-content-digest", f"sha256:{base_digest}"),
            _prop("tap:revision:input-attestation", meta.get("input_attestation_digest") or "not-observed"),
            _prop("tap:scan:grype-version", grype_version),
            _prop("tap:scan:grype-db-built", db.get("built", "")),
            _prop("tap:scan:grype-db-schema", db.get("schemaVersion", "")),
            *source_props,
        ],
    )
    return doc


# ---------------------------------------------------------------------------------------------------------
# Publish only on change (req-cicd-sbom-20-11)
# ---------------------------------------------------------------------------------------------------------


def facts(doc: dict[str, Any]) -> str | None:
    """A digest of the document's facts: components, vulnerability entries and the completeness verdict.

    Left out on purpose: timestamps, scanner database times, fetch times, the KEV catalog version stamp, and EPSS
    (score and percentile move daily; a changed EPSS alone does not publish). None when the document has never been
    scanned (no `vulnerabilities` key), which always counts as changed.
    """
    if "vulnerabilities" not in doc:
        return None
    components = sorted(
        (str(c.get("bom-ref")), str(c.get("name")), str(c.get("version")), str(c.get("purl")))
        for c in doc.get("components") or []
    )
    entries = []
    for entry in doc["vulnerabilities"]:
        normalized = copy.deepcopy(entry)
        normalized.pop("updated", None)  # a record is touched often without its facts changing
        normalized["ratings"] = [
            r for r in normalized.get("ratings") or [] if (r.get("source") or {}).get("name") != "FIRST"
        ]
        normalized["properties"] = [
            p
            for p in normalized.get("properties") or []
            if not str(p.get("name", "")).startswith(_VOLATILE_PROPERTY_PREFIXES)
        ]
        entries.append(normalized)
    completeness = sorted(
        (p["name"], p["value"])
        for p in (doc.get("metadata") or {}).get("properties") or []
        if str(p.get("name", "")).startswith("tap:completeness")
    )
    blob = json.dumps({"c": components, "v": entries, "k": completeness}, sort_keys=True, default=str)
    return _sha256(blob.encode("utf-8"))


def summary(verdict: str, base: dict[str, Any], doc: dict[str, Any] | None, reason: str = "") -> str:
    lines = [f"### SBOM merge: `{verdict}`", ""]
    if verdict == "failed":
        return "\n".join(lines + [f"The merge could not run: {_cell(reason)}"]) + "\n"
    lines.append(f"Compared with revision {base.get('version')} of `{_cell(base.get('serialNumber'))}`.")
    if doc is not None:
        entries = doc["vulnerabilities"]
        listed = sum(
            1 for e in entries for p in e["properties"] if p["name"] == "tap:kev:listed" and p["value"] == "true"
        )
        lines.append(f"Revision {doc['version']}: {len(entries)} vulnerability entries, {listed} on the KEV list.")
        statuses = {
            p["name"]: p["value"]
            for p in doc["metadata"]["properties"]
            if p["name"] in ("tap:kev:status", "tap:cve-records:status")
        }
        lines.append(
            "Sources: " + ", ".join(f"{k.removeprefix('tap:')}={v}" for k, v in sorted(statuses.items())) + "."
        )
    else:
        lines.append("The facts are unchanged; no new revision is published.")
    return "\n".join(lines) + "\n"


def _cell(text: object) -> str:
    cleaned = " ".join(str(text).split())[:200]
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


def main() -> int:
    base: dict[str, Any] = {}
    try:
        base, base_digest = read_required("sbom.cdx.json")
        grype, grype_digest = read_required("grype.json")
        meta, _meta_digest = read_required("meta.json")
        if not all(isinstance(x, dict) for x in (base, grype, meta)):
            raise MergeError("sbom.cdx.json, grype.json and meta.json must each be a JSON object")
        doc = merge(
            base,
            base_digest,
            grype,
            grype_digest,
            check_kev(read_optional("kev.json")),
            check_cve(read_optional("cve.json")),
            check_ghsa(read_optional("ghsa.json")),
            meta,
        )
    except (MergeError, KeyError, TypeError, AttributeError) as exc:
        sys.stderr.write(
            summary("failed", base if isinstance(base, dict) else {}, None, f"{type(exc).__name__}: {exc}")
        )
        return VERDICT_EXIT["failed"]
    if facts(doc) == facts(base):
        sys.stderr.write(summary("unchanged", base, None))
        return VERDICT_EXIT["unchanged"]
    sys.stdout.write(json.dumps(doc, indent=2) + "\n")
    sys.stderr.write(summary("changed", base, doc))
    return VERDICT_EXIT["changed"]


if __name__ == "__main__":
    sys.exit(main())
