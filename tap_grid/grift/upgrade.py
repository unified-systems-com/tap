"""The versions a GRIFT document states, and the upgrade an import makes before it validates.

``req-grift-header-versions``, ``req-grid-entity-model-version`` rules 19 to 26 and
``req-grid-entity-spine-version`` rules 3 to 6.

A document at format ``"1"`` states the spine version and the version of every type it carries
or names. :func:`upgrade_document` reads them, refuses what it cannot carry, and returns the
document with every record and every key at the installed version, before anything is validated
and before anything is written. A document whose stated versions all equal the installed ones is
returned as the same object: its records are passed over once to collect the types it carries,
and nothing is copied, no step runs and no query is made.

It runs on the parsed document and is called from one place, the top of the import. It resolves
no identity and reads no row; it reads the model registry and the declared links, and nothing in
the database.

The unversioned format
----------------------
Format ``"0"`` states no versions. It is read as it always was, with no upgrade, which is to
read the spine and every type at version 1 (``req-grift-header-versions`` rule 11). It is
refused, naming the version, under ``TAP_REQUIRE_GRIFT_VERSIONS=1``; that becomes the default
with the release that moves the fleet's documents and collectors to ``"1"`` (rule 12,
Issue# 1288 - tap).
"""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from tap_grid import version_links
from tap_grid.model_version import EDGE, FIRST_VERSION, declared_edge_version, declared_version, types_carried
from tap_grid.version_links import Break, RecordRefused, Step

#: The format that states no versions, and the one that states them.
UNVERSIONED_FORMAT = "0"
VERSIONED_FORMAT = "1"
#: Set to ``1`` to refuse a document at the unversioned format (rule 12).
REQUIRE_VERSIONS_ENV = "TAP_REQUIRE_GRIFT_VERSIONS"

SPINE_VERSION_KEY = "spine_version"
TYPE_VERSIONS_KEY = "type_versions"

#: A step or key function raised something other than a refusal. Distinct from
#: ``record_refused_by_upgrade``, which is a step's own decision about a record.
STEP_FAILED = "upgrade_step_failed"


def formats_read() -> tuple[str, ...]:
    """The format versions this importer reads now."""
    refused = {UNVERSIONED_FORMAT} if os.environ.get(REQUIRE_VERSIONS_ENV, "") == "1" else set()
    return tuple(version for version in (UNVERSIONED_FORMAT, VERSIONED_FORMAT) if version not in refused)


@dataclass(frozen=True)
class UpgradeIssue:
    """One thing the upgrade refused or reports, in the shape the importer turns into its own issue."""

    code: str
    message: str
    path: str
    entity_type: str | None = None
    entity_id: str | None = None


@dataclass
class UpgradeOutcome:
    """What the upgrade made of a document.

    ``document`` is the input object itself where nothing needed upgrading. ``upgraded`` maps a
    type (or ``"spine"``) to the version the document stated and the installed one, for the
    import's batch to record (rule 26). ``dropped`` maps a type to the fields a step dropped
    from at least one record (rule 25).
    """

    document: Any
    refusals: list[UpgradeIssue] = field(default_factory=list)
    upgraded: dict[str, dict[str, int]] = field(default_factory=dict)
    dropped: dict[str, list[str]] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return bool(self.refusals)


def installed_version(type_slug: str) -> int | None:
    """The version the installed code declares for a type; None for a type nothing registers."""
    from tap_grid.constraints import list_registered_edge_types
    from tap_grid.registry import get_model_class, list_entity_types

    if type_slug != EDGE and type_slug in list_entity_types():
        return declared_version(get_model_class(type_slug))
    if type_slug in list_registered_edge_types():
        return declared_edge_version(type_slug)
    return None


def installed_spine_version() -> int:
    from tap_grid import spine_version

    return spine_version.SPINE_VERSION


def _is_version(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= FIRST_VERSION


def _chain(
    label: str, slug: str, stated: int, installed: int, path: str, refusals: list[UpgradeIssue]
) -> list[tuple[int, Step]] | None:
    """The steps from ``stated`` to ``installed``, or None with the refusal recorded."""
    chain = version_links.links_for(slug)
    entity_type = None if slug == version_links.SPINE else slug
    if stated < chain.oldest:
        refusals.append(
            UpgradeIssue(
                "version_too_old",
                f"{label} is stated at version {stated} and the oldest version still imported is {chain.oldest}",
                path,
                entity_type,
            )
        )
        return None
    steps: list[tuple[int, Step]] = []
    for version in range(stated + 1, installed + 1):
        link = chain.links.get(version)
        where = version_links.describe(version)
        if isinstance(link, Break):
            successor = f" Its successor is {link.successor!r}." if link.successor else ""
            refusals.append(
                UpgradeIssue(
                    "version_break",
                    f"{label} is stated at version {stated} and installed at version {installed}; no step "
                    f"exists from {where}: {link.reason}.{successor} The document is refused",
                    path,
                    entity_type,
                )
            )
            return None
        if not isinstance(link, Step):
            refusals.append(
                UpgradeIssue(
                    "version_no_link",
                    f"{label} is stated at version {stated} and installed at version {installed}, and no link "
                    f"is declared from {where}. The document is refused",
                    path,
                    entity_type,
                )
            )
            return None
        steps.append((version, link))
    return steps


def _read_header(document: Any, outcome: UpgradeOutcome) -> tuple[dict[str, list[tuple[int, Step]]], bool]:
    """The steps each stated type needs, keyed by type (and ``"spine"``); and whether any exist.

    Records every refusal the header alone decides: a version not stated, a version newer than
    the installed one, a version too old, a break in the way.
    """
    metadata = document["metadata"]
    refusals = outcome.refusals
    plan: dict[str, list[tuple[int, Step]]] = {}

    stated_spine = metadata.get(SPINE_VERSION_KEY)
    spine_path = f"$.metadata.{SPINE_VERSION_KEY}"
    if stated_spine is None:
        refusals.append(
            UpgradeIssue(
                "version_unstated",
                "The document states no spine version (metadata.spine_version). Nothing is assumed for a "
                "version a document does not state",
                spine_path,
            )
        )
    elif _is_version(stated_spine):
        installed = installed_spine_version()
        if stated_spine > installed:
            refusals.append(
                UpgradeIssue(
                    "version_newer",
                    f"The document is at spine version {stated_spine} and this grid is at spine version "
                    f"{installed}: it was written by a newer core",
                    spine_path,
                )
            )
        elif stated_spine < installed:
            steps = _chain("The spine", version_links.SPINE, stated_spine, installed, spine_path, refusals)
            if steps is not None:
                plan[version_links.SPINE] = steps
                outcome.upgraded[version_links.SPINE] = {"stated": stated_spine, "installed": installed}

    type_versions = metadata.get(TYPE_VERSIONS_KEY)
    if not isinstance(type_versions, Mapping):
        if type_versions is None:
            refusals.append(
                UpgradeIssue(
                    "version_unstated",
                    "The document states no type versions (metadata.type_versions)",
                    f"$.metadata.{TYPE_VERSIONS_KEY}",
                )
            )
        return plan, bool(plan)

    for slug in sorted(types_carried(document)):
        path = f"$.metadata.{TYPE_VERSIONS_KEY}.{slug}"
        stated = type_versions.get(slug)
        if stated is None:
            refusals.append(
                UpgradeIssue(
                    "version_unstated",
                    f"The document carries or names type {slug!r} and states no version for it "
                    f"(metadata.type_versions). Nothing is assumed for a version a document does not state",
                    path,
                    slug,
                )
            )
            continue
        if not _is_version(stated):
            continue  # The schema refuses it, naming the value.
        installed_type = installed_version(slug)
        if installed_type is None:
            continue  # Not a type this grid registers; validation says so.
        if stated > installed_type:
            refusals.append(
                UpgradeIssue(
                    "version_newer",
                    f"Type {slug!r} is stated at version {stated} and installed at version {installed_type}: "
                    "the document was written by a newer definition of the type",
                    path,
                    slug,
                )
            )
        elif stated < installed_type:
            steps = _chain(f"Type {slug!r}", slug, stated, installed_type, path, refusals)
            if steps is not None:
                plan[slug] = steps
                outcome.upgraded[slug] = {"stated": stated, "installed": installed_type}
    return plan, bool(plan)


class _Upgrader:
    """Applies a plan to a copy of the document, one record at a time."""

    def __init__(self, plan: dict[str, list[tuple[int, Step]]], outcome: UpgradeOutcome) -> None:
        self.plan = plan
        self.outcome = outcome
        self.dropped: dict[str, set[str]] = {}

    def record(self, slug: str, fields: Any, path: str, entity_id: str | None) -> Any:
        """One record's fields through its type's steps. Refusals are recorded, not raised."""
        steps = self.plan.get(slug)
        if not steps or not isinstance(fields, dict):
            return fields
        current = fields
        for version, step in steps:
            carried = set(current)
            try:
                result = step.upgrade(copy.deepcopy(current))
            except RecordRefused as refusal:
                self._refuse(slug, version, path, entity_id, str(refusal) or step.may_refuse or "no reason given")
                return fields
            except (
                Exception
            ) as failure:  # noqa: BLE001 — a step is an author's code run on a record nothing has validated yet
                self._failed(slug, version, path, entity_id, "step", failure)
                return fields
            if not isinstance(result, dict):
                self._refuse(slug, version, path, entity_id, "the step did not return the record's fields")
                return fields
            dropped = carried & set(step.drops)
            if dropped and slug != version_links.SPINE:
                self.dropped.setdefault(slug, set()).update(dropped)
            current = result
        return current

    def key(self, endpoint: Any, path: str) -> None:
        """An entity named by type and key: the key through its type's steps, in place (rule 12)."""
        if not isinstance(endpoint, dict) or "entity_id" in endpoint:
            return
        slug = endpoint.get("entity_type")
        steps = self.plan.get(slug) if isinstance(slug, str) else None
        key = endpoint.get("key")
        if not steps or not isinstance(key, dict) or not isinstance(slug, str):
            return
        current = key
        for version, step in steps:
            if step.key_refused:
                self._refuse(slug, version, path, None, f"a key cannot be carried across: {step.key_refused}")
                return
            if step.key is None:
                continue  # The version does not change the key.
            try:
                result = step.key(copy.deepcopy(current))
            except RecordRefused as refusal:
                self._refuse(slug, version, path, None, str(refusal) or "the key was refused")
                return
            except Exception as failure:  # noqa: BLE001 — as for a step: an author's code on an unvalidated key
                self._failed(slug, version, path, None, "key function", failure)
                return
            if not isinstance(result, dict):
                self._refuse(slug, version, path, None, "the step's key function did not return a key")
                return
            current = result
        endpoint["key"] = current

    def _refuse(self, slug: str, version: int, path: str, entity_id: str | None, reason: str) -> None:
        label = "The spine" if slug == version_links.SPINE else f"Type {slug!r}"
        self.outcome.refusals.append(
            UpgradeIssue(
                "record_refused_by_upgrade",
                f"{label}: the step from {version_links.describe(version)} refused this record: {reason}. "
                "One refused record refuses the document",
                path,
                None if slug == version_links.SPINE else slug,
                entity_id,
            )
        )

    def _failed(self, slug: str, version: int, path: str, entity_id: str | None, what: str, failure: Exception) -> None:
        """A step or key function raised something other than a refusal: the document is refused.

        The upgrade runs before validation, so a step meets records of any shape, and a step can
        simply be wrong. Either way the import answers with an issue, not an exception. Only the
        exception's class is named: its message may quote the record at any length.
        """
        label = "The spine" if slug == version_links.SPINE else f"Type {slug!r}"
        self.outcome.refusals.append(
            UpgradeIssue(
                STEP_FAILED,
                f"{label}: the {what} from {version_links.describe(version)} failed on this record "
                f"({type(failure).__name__[:80]}). The record may be malformed, or the {what} may be wrong; "
                "either way the document is refused and nothing is written",
                path,
                None if slug == version_links.SPINE else slug,
                entity_id,
            )
        )

    def envelope(self, holder: dict[str, Any], name: str, path: str) -> None:
        """A record's envelope through the spine's steps; no type's fields are read (rule 6)."""
        envelope = holder.get(name)
        if isinstance(envelope, dict):
            entity_id = envelope.get("entity_id") if isinstance(envelope.get("entity_id"), str) else None
            holder[name] = self.record(version_links.SPINE, envelope, path, entity_id)

    def batch(self, batch: dict[str, Any], path: str) -> None:
        self.envelope(batch, "batch_entity", f"{path}.batch_entity")
        if isinstance(batch.get("batch_node"), dict):
            entity = batch.get("batch_entity")
            batch_id = entity.get("entity_id") if isinstance(entity, dict) else None
            batch["batch_node"] = self.record("batch", batch["batch_node"], f"{path}.batch_node", _text(batch_id))
        for index, node in enumerate(_listed(batch.get("nodes"))):
            if not isinstance(node, dict):
                continue
            where = f"{path}.nodes[{index}]"
            entity = node.get("entity")
            slug = entity.get("entity_type") if isinstance(entity, dict) else None
            entity_id = entity.get("entity_id") if isinstance(entity, dict) else None
            if isinstance(slug, str):
                node["node"] = self.record(slug, node.get("node"), f"{where}.node", _text(entity_id))
            self.envelope(node, "entity", f"{where}.entity")
        for index, edge in enumerate(_listed(batch.get("edges"))):
            if not isinstance(edge, dict):
                continue
            where = f"{path}.edges[{index}]"
            payload = edge.get("edge")
            entity = edge.get("entity")
            entity_id = entity.get("entity_id") if isinstance(entity, dict) else None
            if isinstance(payload, dict):
                slug = payload.get("edge_type")
                if isinstance(slug, str) and "properties" in payload:
                    payload["properties"] = self.record(
                        slug, payload["properties"], f"{where}.edge.properties", _text(entity_id)
                    )
                self.key(payload.get("from_key"), f"{where}.edge.from_key")
                self.key(payload.get("to_key"), f"{where}.edge.to_key")
            self.envelope(edge, "entity", f"{where}.entity")
        deletes = batch.get("deletes")
        for index, target in enumerate(_listed(deletes.get("edges")) if isinstance(deletes, dict) else []):
            # Only a removal by identity names anything by key; one by id is an operation on the
            # spine and no type's link applies to it (rule 22).
            if isinstance(target, dict) and "entity_id" not in target:
                self.key(target.get("from"), f"{path}.deletes.edges[{index}].from")
                self.key(target.get("to"), f"{path}.deletes.edges[{index}].to")
        cases = batch.get("edge_cases")
        for index, claim in enumerate(_listed(cases.get("authority")) if isinstance(cases, dict) else []):
            if isinstance(claim, dict):
                self.key(claim.get("anchor"), f"{path}.edge_cases.authority[{index}].anchor")


def _listed(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def upgrade_document(document: Any) -> UpgradeOutcome:
    """Bring a parsed GRIFT document to the installed versions, or say why it is refused.

    Reads a document of any shape without raising; what is malformed is the importer's to
    report. An unversioned document, and one that already states the installed versions, comes
    back as the same object.

    ``req-grid-entity-model-version`` rules 19 to 25: the upgrade an import makes before it
    validates and before it writes, from the versions the document's header states to the
    installed ones, through the links each type's author declared.
    """
    outcome = UpgradeOutcome(document=document)
    metadata = document.get("metadata") if isinstance(document, dict) else None
    if not isinstance(metadata, dict):
        return outcome
    stated_format = metadata.get("grift_version")
    if stated_format != VERSIONED_FORMAT:
        if stated_format == UNVERSIONED_FORMAT and UNVERSIONED_FORMAT not in formats_read():
            outcome.refusals.append(
                UpgradeIssue(
                    "unsupported_grift_version",
                    f"grift_version {UNVERSIONED_FORMAT!r} states no versions and is not read: this importer "
                    f"reads GRIFT version {VERSIONED_FORMAT!r} only. Add metadata.spine_version and "
                    "metadata.type_versions and state grift_version "
                    f"{VERSIONED_FORMAT!r}",
                    "$.metadata.grift_version",
                )
            )
        return outcome

    plan, needed = _read_header(document, outcome)
    if outcome.refused or not needed:
        if outcome.refused:
            outcome.upgraded = {}
        return outcome

    upgraded = copy.deepcopy(document)
    worker = _Upgrader(plan, outcome)
    for index, batch in enumerate(_listed(upgraded.get("batches"))):
        if isinstance(batch, dict):
            worker.batch(batch, f"$.batches[{index}]")
    if outcome.refused:
        outcome.upgraded = {}
        return outcome
    # The document is now at the installed versions, and says so, so what validates it and what
    # reads its header afterwards see one consistent statement.
    header = upgraded["metadata"]
    if version_links.SPINE in plan:
        header[SPINE_VERSION_KEY] = installed_spine_version()
    stated_types = header.get(TYPE_VERSIONS_KEY)
    if isinstance(stated_types, dict):
        header[TYPE_VERSIONS_KEY] = {
            **stated_types,
            **{slug: change["installed"] for slug, change in outcome.upgraded.items() if slug != version_links.SPINE},
        }
    outcome.document = upgraded
    outcome.dropped = {slug: sorted(names) for slug, names in sorted(worker.dropped.items())}
    return outcome


def build_header(document: Any, *, using: str = "default", unversioned: bool = False) -> dict[str, Any]:
    """The ``metadata`` of a document this grid writes: the format, the spine and every type's version.

    With ``unversioned``, the header of a format ``"0"`` document restated at ``"1"`` (``tap_grid.grift.
    restamp``): what such a document's records are at, which is the spine and every type at version 1
    (rule 11), whatever this grid is at now. The types listed are the same ones, from the same reading
    of the document, so the exporter and the restamp cannot disagree about which types a header names.

    The spine version is the one the database records, and each type's is the version applied to
    this grid's rows, read from the catalog in one query (rule 6 of ``req-grift-header-versions``).
    A type the catalog has no row for is stated at the version its definition declares: an edge
    type no definition declares has neither, and is stated at 1.

    For the exporter, and for any producer in core or a plugin that builds a document in code.

    TAP-IMPLEMENTS: req-grift-header-versions@785dd3dae207/78c1febc624b (derivation) — rules 1, 2, 4 and 6: the header a
        document written by this grid carries, with an entry for every type the document carries
        or names.
    """
    from tap_grid import spine_version
    from tap_grid.models import EntityType

    carried = sorted(types_carried(document))
    if unversioned:
        return {
            "grift_version": VERSIONED_FORMAT,
            SPINE_VERSION_KEY: FIRST_VERSION,
            TYPE_VERSIONS_KEY: dict.fromkeys(carried, FIRST_VERSION),
        }
    applied = dict(EntityType.objects.using(using).filter(slug__in=carried).values_list("slug", "model_version"))
    recorded = spine_version.recorded_version(using=using)
    return {
        "grift_version": VERSIONED_FORMAT,
        SPINE_VERSION_KEY: recorded if recorded is not None else spine_version.SPINE_VERSION,
        TYPE_VERSIONS_KEY: {slug: applied.get(slug) or installed_version(slug) or FIRST_VERSION for slug in carried},
    }
