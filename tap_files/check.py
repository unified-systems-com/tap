"""The report-only check: the store against itself and against the grid (`req-tap-files-check`).

`specs/spec-tap-file-store.md`. ``manage.py files check`` calls :func:`run_check`. It changes nothing:
the store half is :meth:`LocalBackend.survey`, which writes nothing and takes no lock, and the grid
half only reads. Like boot's initialisation and recovery, it reads the store below the gate
(`req-tap-files-gateway-5`): it is an operator's command, as ``manage.py health`` is.

Each finding is a fault, which makes the exit status non-zero, or a notice, which does only under
``--strict``. The one notice is a store head ahead of its node: the expected leftover of a refused
grid write (`req-tap-files-check-9`).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from tap_files.holding import identifier_for
from tap_files.models import TapFile
from tap_files.store import FileStoreNotEnabled, get_store
from tap_files.store.protocol import StoreSurvey

FAULT, NOTICE = "fault", "notice"
REPORT_SCHEMA = "tap_files/schemas/check-report.schema.json"


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    subject: str
    detail: str
    path: str | None = None


@dataclass
class Report:
    root: str
    deep: bool
    findings: list[Finding] = field(default_factory=list)
    quarantine: list[dict[str, str]] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)

    def failed(self, *, strict: bool = False) -> bool:
        """Any fault, or under *strict* any notice too."""
        return any(f.severity == FAULT or strict for f in self.findings)

    def as_json(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "deep": self.deep,
            "findings": [{k: v for k, v in asdict(f).items() if v is not None} for f in self.findings],
            "quarantine": self.quarantine,
            "totals": self.totals,
        }


def run_check(*, deep: bool = False) -> Report:
    """Survey the store, read the live grid files and their format records, and compare.

    The caller binds the actor the grid is read as (the command uses the bootloader, as the other
    operator commands do).
    """
    store = get_store()
    survey = store.survey(deep=deep)
    report = Report(root=str(store.root), deep=deep, quarantine=list(survey.quarantine))
    report.findings.extend(_store_findings(survey))
    live = cast(list[TapFile], list(TapFile.objects.select_related("entity")))
    nodes = {identifier_for(node.entity_id): node for node in live}
    report.findings.extend(_node_findings(survey, nodes))
    report.findings.extend(_format_record_findings())
    report.totals = {
        "objects": len(survey.objects) + len(survey.damaged),
        "versions": sum(o.head for o in survey.objects),
        "bytes": sum(size for o in survey.objects for _digest, size in set(o.versions) if size > 0),
        "nodes": len(nodes),
    }
    return report


def _store_findings(survey: StoreSurvey) -> list[Finding]:
    found = [
        Finding(FAULT, "link_below_ocfl", where, "a symbolic link below ocfl/; never followed")
        for where in survey.links
    ]
    found += [Finding(FAULT, "damaged_object", subject, why) for subject, why in survey.damaged]
    found += [Finding(FAULT, "interrupted_write", subject, what) for subject, what in survey.interrupted]
    for obj in survey.objects:
        found += [Finding(FAULT, "invalid_object", obj.identifier, finding) for finding in obj.findings]
    return found


def _node_findings(survey: StoreSurvey, nodes: dict[str, TapFile]) -> list[Finding]:
    """Both directions: stored bytes no live node names, and live nodes the store disagrees with."""
    found: list[Finding] = []
    stored = {o.identifier: o for o in survey.objects}
    damaged = {subject for subject, _why in survey.damaged}
    for identifier in sorted(set(stored) | damaged):
        if identifier.startswith("urn:") and identifier not in nodes:
            found.append(Finding(FAULT, "orphan_object", identifier, "no live tap_file has this identifier"))
    for identifier, node in sorted(nodes.items()):
        if identifier in damaged:
            continue  # already a fault; its versions cannot be read to compare
        obj = stored.get(identifier)
        if obj is None:
            found.append(Finding(FAULT, "node_without_bytes", identifier, "the store holds no object", node.path))
            continue
        version = node.file_version
        if version > obj.head:
            found.append(
                Finding(FAULT, "node_ahead_of_store", identifier, f"node v{version}, store head v{obj.head}", node.path)
            )
            continue
        if version < obj.head:
            found.append(
                Finding(
                    NOTICE,
                    "store_ahead_of_node",
                    identifier,
                    f"store head v{obj.head}, node v{version}: a version stored whose grid write did not follow",
                    node.path,
                )
            )
        digest, size = obj.versions[version - 1]
        if digest != node.sha256:
            found.append(
                Finding(
                    FAULT,
                    "node_disagrees",
                    identifier,
                    f"v{version} sha256: node {node.sha256}, store {digest}",
                    node.path,
                )
            )
        if size != node.size_bytes:
            found.append(
                Finding(
                    FAULT,
                    "node_disagrees",
                    identifier,
                    f"v{version} size: node {node.size_bytes}, store {size}",
                    node.path,
                )
            )
    return found


def _format_record_findings() -> list[Finding]:
    """`FILE_CONTENTS` edges the grid cannot yet refuse (`req-tap-files-check-10`, Issue# 1237 - tap)."""
    from tap_grid.models import Edge

    found: list[Finding] = []
    # The grid's managers are typed by the base model; these rows are edges and files.
    edges = cast(
        list[Edge],
        list(
            cast(Any, Edge.objects)
            .filter(edge_type="FILE_CONTENTS", entity__deleted_at__isnull=True)
            .select_related("from_entity")
        ),
    )
    sources = {e.from_entity_id for e in edges}
    holders = cast(list[TapFile], list(TapFile.objects.filter(entity_id__in=sources).select_related("entity")))
    files = {node.entity_id: node for node in holders}
    counts = Counter(e.from_entity_id for e in edges)
    for edge in edges:
        node = files.get(edge.from_entity_id)
        subject = str(edge.entity_id)
        if node is None:
            kind = edge.from_entity.entity_type
            found.append(Finding(FAULT, "format_record_wrong_source", subject, f"from a {kind}, not a tap_file"))
            continue
        if (edge.properties or {}).get("sha256") != node.sha256:
            found.append(
                Finding(
                    FAULT,
                    "format_record_stale",
                    subject,
                    f"edge sha256 {edge.properties.get('sha256')}, file sha256 {node.sha256}",
                    node.path,
                )
            )
    for source, count in sorted(counts.items(), key=lambda item: str(item[0])):
        node = files.get(source)
        if node is not None and count > 1:
            found.append(
                Finding(
                    FAULT,
                    "format_record_duplicate",
                    identifier_for(source),
                    f"{count} FILE_CONTENTS edges out of one file",
                    node.path,
                )
            )
    return found


__all__ = ["FAULT", "NOTICE", "REPORT_SCHEMA", "FileStoreNotEnabled", "Finding", "Report", "run_check"]
