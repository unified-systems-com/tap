"""The versions a GRIFT document states, the chain of links, and the upgrade an import makes.

Specs: ``req-grid-entity-model-version`` (the chain of versions, and import),
``req-grid-entity-spine-version`` rules 3 to 6 in ``tap_grid/specs/spec-grid-entity.md``, and
``req-grift-header-versions`` in ``tap_grid/specs/spec-grift-v0.md``.

A document states each type at the version this core installs and the spine at the spine version
this core installs, so that nothing is upgraded unless a test says so. The spine is at version 2 and
some of core's own types are too (the base-model release, Issue# 1288 - tap); the fixture type is at
version 1. A test that needs a type or the spine to be newer raises it: it declares a greater version
for the length of the test and declares the links that version needs.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import model_definition as definition
from tap_grid import model_version as mv
from tap_grid import spine_version, version_links
from tap_grid.grift import grift_import
from tap_grid.grift import upgrade as grift_upgrade
from tap_grid.grift.exporter import export_grid
from tap_grid.grift.importer import validate_grift_document
from tap_grid.models import Batch, Edge, Entity
from tap_grid.services import create_node
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_grid.version_links import Break, RecordRefused, Step
from tap_web.models import Panel

pytestmark = pytest.mark.django_db

MV = {n: pytest.mark.spec(f"req-grid-entity-model-version-{n}") for n in range(1, 34)}
SV = {n: pytest.mark.spec(f"req-grid-entity-spine-version-{n}") for n in range(1, 8)}
HV = {n: pytest.mark.spec(f"req-grift-header-versions-{n}") for n in range(1, 9)}

NODE = "grid_fixtures__node"
LINK = "SCHEMA_LINK__grid_fixtures"
PLAIN_LINK = "PG_LINKS__grid_fixtures"


@pytest.fixture(autouse=True)
def _process_state() -> Iterator[None]:
    """Declared links and edge versions are per process; put them back after each test.

    The installed apps' links are read before the snapshot. Read lazily, once per process, they would
    otherwise be read inside the first test that asks and then cleared with that test's own, leaving
    every later test without core's spine and type links.
    """
    version_links.any_declared()
    declared, edge_versions, pending = dict(version_links._declared), dict(mv._edge_versions), dict(mv._pending)
    owed = mv._start_incomplete
    mv._pending.clear()
    mv._start_incomplete = False
    try:
        yield
    finally:
        version_links._declared.clear()
        version_links._declared.update(declared)
        mv._edge_versions.clear()
        mv._edge_versions.update(edge_versions)
        mv._pending.clear()
        mv._pending.update(pending)
        mv._start_incomplete = owed


#: The spine version and core's type versions as installed, read before any test raises one.
SPINE = spine_version.SPINE_VERSION
INSTALLED = {slug: mv.declared_version(model) for slug, model in mv.core_node_types().items()}


def _node(name: str, entity_id: str | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id or str(uuid.uuid7()),
            "entity_type": NODE,
            "name": name,
            "dimensions": {},
        },
        "node": {"name": name, **fields},
    }


def _edge(from_id: str, to_id: str, edge_type: str = LINK, **properties: Any) -> dict[str, Any]:
    return {
        "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "edge", "dimensions": {}},
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": edge_type, "properties": properties},
    }


def _document(
    *,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    spine: int | None = SPINE,
    versions: dict[str, int] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """A document at format "1", stating the installed spine and each core type at its installed version.

    Every other type it carries is stated at 1, and ``versions`` overrides any of them.
    """
    container = _batch_container(_batch_entity_id(), nodes=nodes or [], edges=edges or [])
    container.update(extra)
    document = _minimal_doc([container])
    stated = {slug: INSTALLED.get(slug, 1) for slug in sorted(mv.types_carried(document))}
    stated.update(versions or {})
    document["metadata"] = {"grift_version": "1", "type_versions": stated}
    if spine is not None:
        document["metadata"]["spine_version"] = spine
    return document


def _codes(result: Any) -> list[str]:
    return [issue.code for issue in result.errors]


def _rename_kind_to_description(fields: dict[str, Any]) -> dict[str, Any]:
    """Version 1 called it ``summary``; version 2 calls it ``description``. Says nothing it was not told."""
    if "summary" in fields:
        fields["description"] = fields.pop("summary")
    fields.pop("legacy_code", None)
    return fields


def _node_at_2(monkeypatch: pytest.MonkeyPatch, link: Any | None = None) -> None:
    monkeypatch.setattr(PgNode, "MODEL_VERSION", 2)
    if link is not None:
        version_links.declare(NODE, {2: link})


RENAME = Step(_rename_kind_to_description, renames={"description": "summary"}, drops=("legacy_code",))


# ---------------------------------------------------------------------------
# The header
# ---------------------------------------------------------------------------


class TestHeader:
    @HV[1]
    @HV[3]
    @HV[6]
    @MV[21]
    @SV[3]
    def test_an_export_states_the_format_the_spine_and_every_type(self) -> None:
        first = create_node(NODE, {"name": "exported one"})
        second = create_node(NODE, {"name": "exported two"})
        assert first.entity_id is not None and second.entity_id is not None
        from tap_grid.services import create_edge

        create_edge(Entity.objects.get(pk=first.entity_id), Entity.objects.get(pk=second.entity_id), PLAIN_LINK, {})
        with mv._writing_applied_version():
            from tap_grid.models import EntityType

            EntityType.objects.update_or_create(slug=NODE, defaults={"name": "PgNode"})
        document = export_grid().document
        header = document["metadata"]
        assert header["grift_version"] == "1"
        assert header["spine_version"] == spine_version.recorded_version() == spine_version.SPINE_VERSION
        carried = mv.types_carried(document)
        assert {NODE, PLAIN_LINK, "batch"} <= carried
        assert set(header["type_versions"]) == carried
        assert header["type_versions"][NODE] == mv.applied_version(NODE) == 1
        assert header["type_versions"][PLAIN_LINK] == 1
        # The spine version is a field of its own, beside the format and not derived from it.
        assert set(header) == {"grift_version", "spine_version", "type_versions"}
        assert validate_grift_document(document) == []

    @HV[1]
    def test_an_export_states_the_applied_version_the_catalog_records(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.models import EntityType

        assert create_node(NODE, {"name": "at two"}).success
        monkeypatch.setattr(PgNode, "MODEL_VERSION", 2)
        with mv._writing_applied_version():
            EntityType.objects.update_or_create(slug=NODE, defaults={"name": "PgNode", "model_version": 2})
        assert export_grid().document["metadata"]["type_versions"][NODE] == 2

    @HV[2]
    @pytest.mark.parametrize("bad", [0, -1, "1", 1.5, True, None])
    def test_the_schema_refuses_a_version_that_is_not_a_whole_number_from_1(self, bad: Any) -> None:
        good = _document(nodes=[_node("valid")])
        assert validate_grift_document(good) == []
        wrong_spine = copy.deepcopy(good)
        wrong_spine["metadata"]["spine_version"] = bad
        assert validate_grift_document(wrong_spine), bad
        wrong_type = copy.deepcopy(good)
        wrong_type["metadata"]["type_versions"][NODE] = bad
        assert validate_grift_document(wrong_type), bad

    @HV[2]
    def test_the_schema_holds_each_format_to_its_own_header(self) -> None:
        unversioned = _minimal_doc()
        assert validate_grift_document(unversioned) == []
        unversioned["metadata"]["spine_version"] = 1
        assert validate_grift_document(unversioned), "format 0 states no versions"
        versioned = _document()
        del versioned["metadata"]["type_versions"]
        assert validate_grift_document(versioned), "format 1 requires both"
        extra = _document()
        extra["metadata"]["tap_version"] = "0.5.0"
        assert validate_grift_document(extra), "metadata still refuses an unknown key"

    @HV[4]
    @SV[7]
    def test_a_document_with_no_spine_version_is_refused(self) -> None:
        result = grift_import(_document(nodes=[_node("no spine")], spine=None))
        assert not result.success and _codes(result) == ["version_unstated"]
        assert "spine version" in result.errors[0].message
        assert not Entity.objects.filter(name="no spine").exists() and result.imported_batches == []

    @HV[4]
    @MV[13]
    def test_a_carried_type_with_no_stated_version_is_refused_naming_it(self) -> None:
        document = _document(nodes=[_node("unstated")])
        del document["metadata"]["type_versions"][NODE]
        before = Batch.all_objects.count()
        result = grift_import(document)
        assert not result.success and _codes(result) == ["version_unstated"]
        assert NODE in result.errors[0].message and result.errors[0].entity_type == NODE
        assert not Entity.objects.filter(name="unstated").exists()
        assert Batch.all_objects.count() == before

    @HV[4]
    def test_a_type_named_only_by_reference_needs_its_version_too(self) -> None:
        """An edge endpoint named by type and key names a type the document carries no record of."""
        edge = {
            "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "edge", "dimensions": {}},
            "edge": {
                "edge_type": PLAIN_LINK,
                "properties": {},
                "from_key": {"entity_type": "panel", "key": {"slug": "a"}},
                "to_key": {"entity_type": "panel", "key": {"slug": "b"}},
            },
        }
        document = _document(edges=[edge])
        assert "panel" in document["metadata"]["type_versions"]
        del document["metadata"]["type_versions"]["panel"]
        result = grift_import(document)
        assert _codes(result) == ["version_unstated"] and "'panel'" in result.errors[0].message

    @HV[4]
    def test_an_entry_for_a_type_the_document_does_not_carry_is_ignored(self) -> None:
        document = _document(nodes=[_node("with an extra entry")], versions={"no_such_type": 7, "panel": 1})
        assert grift_import(document).success

    @HV[6]
    @HV[7]
    def test_the_two_formats_and_what_refuses_each(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Format "0" is still read until the switch is set; an unknown format names what is read."""
        assert grift_upgrade.formats_read() == ("0", "1")
        assert grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[_node("old form")])])).success

        monkeypatch.setenv(grift_upgrade.REQUIRE_VERSIONS_ENV, "1")
        assert grift_upgrade.formats_read() == ("1",)
        refused = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[_node("refused form")])]))
        assert not refused.success and _codes(refused) == ["unsupported_grift_version"]
        assert "'0'" in refused.errors[0].message and "'1'" in refused.errors[0].message
        assert not Entity.objects.filter(name="refused form").exists()
        assert grift_import(_document(nodes=[_node("new form")])).success

    @HV[5]
    def test_stated_versions_reach_no_row(self) -> None:
        document = _document(nodes=[_node("nothing stored")])
        result = grift_import(document)
        assert result.success, result.errors
        entity = Entity.objects.get(name="nothing stored")
        row = PgNode.objects.get(entity=entity)
        stored = json.dumps(
            {
                "dimensions": entity.dimensions,
                "flip": row.flip_map,
                "batch": Batch.all_objects.get(entity_id=result.imported_batches[0].batch_entity_id).description_json,
            },
            default=str,
        )
        assert "type_versions" not in stored and "spine_version" not in stored
        assert "upgraded" not in stored, "nothing was upgraded, so the batch records no upgrade"


# ---------------------------------------------------------------------------
# The upgrade
# ---------------------------------------------------------------------------


class TestNothingToUpgrade:
    def test_a_document_at_the_installed_versions_is_not_copied_and_reads_no_row(self) -> None:
        document = _document(nodes=[_node(f"n{i}") for i in range(50)])
        with CaptureQueriesContext(connection) as queries:
            outcome = grift_upgrade.upgrade_document(document)
        assert outcome.document is document and not outcome.refused
        assert outcome.upgraded == {} and outcome.dropped == {}
        assert len(queries) == 0

    def test_an_unversioned_document_is_returned_untouched(self) -> None:
        document = _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_node("as before")])])
        with CaptureQueriesContext(connection) as queries:
            outcome = grift_upgrade.upgrade_document(document)
        assert outcome.document is document and not outcome.refused and len(queries) == 0

    @pytest.mark.parametrize("document", [None, [], "text", {}, {"metadata": []}, {"metadata": {"grift_version": 1}}])
    def test_a_malformed_document_is_left_for_the_importer_to_report(self, document: Any) -> None:
        outcome = grift_upgrade.upgrade_document(document)
        assert outcome.document is document and not outcome.refused


class TestOlderRecords:
    @MV[8]
    @MV[12]
    @MV[16]
    @HV[5]
    def test_a_version_1_record_is_upgraded_validated_and_stored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _node_at_2(monkeypatch, RENAME)
        document = _document(nodes=[_node("older", summary="said at version 1", legacy_code="x9")])
        sent = copy.deepcopy(document)
        result = grift_import(document)
        assert result.success, result.errors
        row = PgNode.objects.get(entity__name="older")
        # The stored row holds what the step returned. Version 2 has no `summary` and no
        # `legacy_code`: had the record not been upgraded, validation would have refused it.
        assert row.description == "said at version 1"
        # The dropped field is reported by type and field, never dropped silently.
        dropped = [issue for issue in result.warnings if issue.code == "field_dropped_by_upgrade"]
        assert [(issue.entity_type, "legacy_code" in issue.message) for issue in dropped] == [(NODE, True)]
        # A rename is not a drop: the renamed field is not reported.
        assert not any("summary" in issue.message for issue in dropped)
        # The batch names what was upgraded; the caller's document is not changed.
        batch = Batch.all_objects.get(entity_id=result.imported_batches[0].batch_entity_id)
        assert batch.description_json["data"]["upgraded"] == {NODE: {"stated": 1, "installed": 2}}
        assert document == sent

    @MV[8]
    def test_a_chain_of_two_steps_runs_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(PgNode, "MODEL_VERSION", 3)

        def to_three(fields: dict[str, Any]) -> dict[str, Any]:
            if "description" in fields:
                fields["description"] = fields["description"].upper()
            return fields

        version_links.declare(NODE, {2: RENAME, 3: Step(to_three)})
        result = grift_import(_document(nodes=[_node("twice", summary="quiet")]))
        assert result.success, result.errors
        assert PgNode.objects.get(entity__name="twice").description == "QUIET"
        partial = grift_import(_document(nodes=[_node("from two", description="already two")], versions={NODE: 2}))
        assert partial.success, partial.errors
        assert PgNode.objects.get(entity__name="from two").description == "ALREADY TWO"

    @MV[19]
    def test_a_field_the_record_did_not_send_is_not_asserted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A step adds no default: an old document that sent only a name leaves the stored value alone."""
        made = create_node(NODE, {"name": "kept", "description": "set by an analyst"})
        assert made.success
        _node_at_2(monkeypatch, RENAME)
        result = grift_import(_document(nodes=[_node("kept", entity_id=str(made.entity_id))]))
        assert result.success, result.errors
        assert PgNode.objects.get(entity_id=made.entity_id).description == "set by an analyst"

    @MV[9]
    def test_a_newer_record_refuses_the_document(self) -> None:
        document = _document(nodes=[_node("from the future")], versions={NODE: 3})
        result = grift_import(document)
        assert not result.success and _codes(result) == ["version_newer"]
        message = result.errors[0].message
        assert NODE in message and "version 3" in message and "version 1" in message
        assert not Entity.objects.filter(name="from the future").exists()

    @MV[10]
    def test_a_declared_break_refuses_the_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _node_at_2(monkeypatch, Break("version 2 measures in metres and version 1 did not say its unit"))
        result = grift_import(_document(nodes=[_node("across a break")]))
        assert not result.success and _codes(result) == ["version_break"]
        message = result.errors[0].message
        assert NODE in message and "version 1 to 2" in message and "metres" in message
        assert not Entity.objects.filter(name="across a break").exists()

    def test_a_missing_link_refuses_the_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _node_at_2(monkeypatch)
        result = grift_import(_document(nodes=[_node("no way across")]))
        assert _codes(result) == ["version_no_link"] and "version 1 to 2" in result.errors[0].message

    def test_a_record_older_than_the_oldest_imported_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(PgNode, "MODEL_VERSION", 3)
        version_links.declare(NODE, {2: RENAME, 3: Step(lambda fields: fields)}, oldest=2)
        result = grift_import(_document(nodes=[_node("too old")]))
        assert _codes(result) == ["version_too_old"]
        assert "version 1" in result.errors[0].message and "is 2" in result.errors[0].message

    @MV[11]
    def test_one_refused_record_refuses_every_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def needs_summary(fields: dict[str, Any]) -> dict[str, Any]:
            if fields.get("summary") == "":
                raise RecordRefused("an empty summary has no version 2 form")
            return _rename_kind_to_description(fields)

        _node_at_2(monkeypatch, Step(needs_summary, renames={"description": "summary"}, may_refuse="empty summaries"))
        refused_id = str(uuid.uuid7())
        nodes = [_node("fine one", summary="ok"), _node("the bad one", refused_id, summary=""), _node("fine two")]
        result = grift_import(_document(nodes=nodes))
        assert not result.success and _codes(result) == ["record_refused_by_upgrade"]
        issue = result.errors[0]
        assert issue.entity_id == refused_id and issue.entity_type == NODE
        assert "version 1 to 2" in issue.message and "empty summary" in issue.message
        assert issue.path == "$.batches[0].nodes[1].node"
        assert not Entity.objects.filter(name__in=["fine one", "the bad one", "fine two"]).exists()

    @MV[15]
    def test_an_edge_type_s_properties_go_through_its_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first, second = create_node(NODE, {"name": "from"}), create_node(NODE, {"name": "to"})
        assert first.success and second.success
        mv.register_edge_version(LINK, 2)

        def level_to_proficiency(properties: dict[str, Any]) -> dict[str, Any]:
            if "level" in properties:
                properties["proficiency"] = properties.pop("level")
            return properties

        version_links.declare(LINK, {2: Step(level_to_proficiency, renames={"proficiency": "level"})})
        edge = _edge(str(first.entity_id), str(second.entity_id), level="master")
        result = grift_import(_document(edges=[edge]))
        assert result.success, result.errors
        stored = Edge.objects.get(entity_id=edge["entity"]["entity_id"])
        assert stored.properties == {"proficiency": "master"}
        batch = Batch.all_objects.get(entity_id=result.imported_batches[0].batch_entity_id)
        assert batch.description_json["data"]["upgraded"] == {LINK: {"stated": 1, "installed": 2}}


class TestKeysInReferences:
    """Rule 12: a document that names an entity by key, without its record, has that key upgraded."""

    def _key_document(self) -> dict[str, Any]:
        edge = {
            "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "edge", "dimensions": {}},
            "edge": {
                "edge_type": PLAIN_LINK,
                "properties": {},
                "from_key": {"entity_type": "panel", "key": {"code": "source-panel"}},
                "to_key": {"entity_type": "panel", "key": {"code": "target-panel"}},
            },
        }
        return _document(edges=[edge])

    def _panels(self) -> dict[str, str]:
        nodes: list[dict[str, Any]] = [
            {
                "entity": {
                    "entity_id": str(uuid.uuid4()),
                    "entity_type": "panel",
                    "name": slug,
                    "dimensions": {"tap.graph": "web"},
                },
                "node": {"name": slug, "slug": slug, "description": "", "view": "tap_web/panel_error.html"},
            }
            for slug in ("source-panel", "target-panel")
        ]
        seeded = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=nodes)]))
        assert seeded.success, seeded.errors
        return {node["node"]["slug"]: node["entity"]["entity_id"] for node in nodes}

    @MV[20]
    def test_an_endpoint_named_by_a_version_1_key_resolves_after_the_key_is_upgraded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = self._panels()
        monkeypatch.setattr(Panel, "MODEL_VERSION", 2)
        version_links.declare("panel", {2: Step(lambda fields: fields, key=lambda key: {"slug": key["code"]})})
        document = self._key_document()
        result = grift_import(document)
        assert result.success, result.errors
        assert Edge.objects.filter(
            from_entity_id=ids["source-panel"], to_entity_id=ids["target-panel"], edge_type=PLAIN_LINK
        ).exists()

    @MV[20]
    def test_a_key_that_cannot_be_carried_refuses_before_identity_is_resolved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._panels()
        monkeypatch.setattr(Panel, "MODEL_VERSION", 2)
        version_links.declare(
            "panel", {2: Step(lambda fields: fields, key_refused="version 2 keys on a value version 1 never held")}
        )
        result = grift_import(self._key_document())
        assert not result.success and set(_codes(result)) == {"record_refused_by_upgrade"}
        assert "key cannot be carried" in result.errors[0].message
        assert result.errors[0].path == "$.batches[0].edges[0].edge.from_key"
        assert not Edge.objects.filter(edge_type=PLAIN_LINK).exists()

    def test_removal_endpoints_and_authority_anchors_are_upgraded_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "MODEL_VERSION", 2)
        version_links.declare("panel", {2: Step(lambda fields: fields, key=lambda key: {"slug": key["code"]})})
        old = {"entity_type": "panel", "key": {"code": "p"}}
        by_id = {"entity_id": str(uuid.uuid4())}
        document = _document(
            deletes={
                "on_missing": "ignore",
                "on_tombstoned": "ignore",
                "nodes": [],
                "edges": [
                    {"edge_type": PLAIN_LINK, "from": copy.deepcopy(old), "to": by_id, "reason": "gone"},
                    {"entity_id": str(uuid.uuid4()), "entity_type": "edge", "reason": "by id"},
                ],
            },
            edge_cases={
                "authority": [
                    {"edge_type": PLAIN_LINK, "anchor": copy.deepcopy(old), "direction": "outbound", "read": "full"}
                ]
            },
        )
        outcome = grift_upgrade.upgrade_document(document)
        assert not outcome.refused, outcome.refusals
        batch = outcome.document["batches"][0]
        assert batch["deletes"]["edges"][0]["from"] == {"entity_type": "panel", "key": {"slug": "p"}}
        assert batch["deletes"]["edges"][0]["to"] == by_id
        assert batch["edge_cases"]["authority"][0]["anchor"]["key"] == {"slug": "p"}
        assert outcome.document["metadata"]["type_versions"]["panel"] == 2
        # The caller's document is untouched.
        assert document["batches"][0]["deletes"]["edges"][0]["from"] == old


class TestTheSpineChain:
    @SV[5]
    def test_a_newer_spine_refuses_the_document(self) -> None:
        result = grift_import(_document(nodes=[_node("newer spine")], spine=SPINE + 1))
        assert not result.success and _codes(result) == ["version_newer"]
        message = result.errors[0].message
        assert f"spine version {SPINE + 1}" in message and f"spine version {SPINE}" in message
        assert not Entity.objects.filter(name="newer spine").exists()

    @SV[4]
    def test_an_older_envelope_goes_through_core_s_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(spine_version, "SPINE_VERSION", SPINE + 1)
        seen: list[set[str]] = []

        def rename_title(envelope: dict[str, Any]) -> dict[str, Any]:
            seen.append(set(envelope))
            if "title" in envelope:
                envelope["name"] = envelope.pop("title")
            return envelope

        chain = dict(version_links.links_for(version_links.SPINE).links)
        chain[SPINE + 1] = Step(rename_title, renames={"name": "title"})
        version_links.declare(version_links.SPINE, chain)
        node = _node("spine one")
        node["entity"]["title"] = node["entity"].pop("name")
        result = grift_import(_document(nodes=[node]))
        assert result.success, result.errors
        assert Entity.objects.filter(name="spine one", entity_type=NODE).exists()
        batch = Batch.all_objects.get(entity_id=result.imported_batches[0].batch_entity_id)
        assert batch.description_json["data"]["upgraded"] == {"spine": {"stated": SPINE, "installed": SPINE + 1}}
        # The spine's step was given envelopes and never a type's fields (rule 6).
        assert seen and all("entity_type" in keys and "description" not in keys for keys in seen)

    @SV[6]
    def test_the_two_chains_are_applied_independently(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _node_at_2(monkeypatch, RENAME)
        document = _document(nodes=[_node("type only", summary="s")])
        outcome = grift_upgrade.upgrade_document(document)
        assert set(outcome.upgraded) == {NODE}
        assert outcome.document["batches"][0]["nodes"][0]["entity"] == document["batches"][0]["nodes"][0]["entity"]
        assert outcome.document["metadata"]["spine_version"] == SPINE

    def test_a_missing_spine_link_refuses_the_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(spine_version, "SPINE_VERSION", SPINE + 1)
        result = grift_import(_document(nodes=[_node("no spine link")]))
        assert _codes(result) == ["version_no_link"] and "The spine" in result.errors[0].message


# ---------------------------------------------------------------------------
# The guard between versions
# ---------------------------------------------------------------------------


def _state(version: int, fields: dict[str, dict[str, Any]], **parts: Any) -> definition.TypeState:
    body = {"fields": fields, "key": parts.get("key"), "service_schema": {"create_required": parts.get("required")}}
    return definition.TypeState(kind=mv.NODE, slug="synthetic", version=version, definition=body)


def _entries(*states: definition.TypeState) -> list[dict[str, Any]]:
    record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
    for state in states:
        definition.append_entry(record, state)
    return definition.entries_for(record, states[-1])


TEXT = {"type": "CharField", "null": False, "max_length": 80}


class TestTheGuardBetweenVersions:
    @MV[6]
    def test_a_version_with_no_link_is_a_problem_recorded_or_not(self) -> None:
        third = _state(3, {"name": TEXT})
        version_links.declare("synthetic", {2: Step(lambda fields: fields)})
        problems = definition.link_problems(third, [])
        assert len(problems) == 1 and "version 2 to 3" in problems[0] and "no link" in problems[0]
        version_links.declare("synthetic", {2: Step(lambda fields: fields), 3: Break("a new unit")})
        assert definition.link_problems(third, []) == []

    @MV[6]
    def test_plugin_validation_fails_a_type_whose_chain_is_missing_a_link(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from types import SimpleNamespace

        from tap_plugins.validate import service
        from tap_plugins.validate.service import ValidationResult

        state = _state(3, {"name": TEXT})
        monkeypatch.setattr(definition, "plugin_states", lambda manifest: [state])
        version_links.declare("synthetic", {2: Step(lambda fields: fields)})
        manifest = SimpleNamespace(slug="synthetic_plugin", models=[object()], edges=[], plugin_root=tmp_path)
        result = ValidationResult(ok=True, level="full", plugin_path=str(tmp_path), strict=True)
        service._check_model_version_records(manifest, result)
        check = next(check for check in result.checks if check.id == "model-version-records")
        assert check.status == "fail"
        assert any("version 2 to 3" in message.text for message in check.messages)

    @MV[7]
    def test_a_removed_field_must_be_declared(self) -> None:
        first = _state(1, {"name": TEXT, "nickname": TEXT})
        second = _state(2, {"name": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields)})
        problems = definition.link_problems(second, entries)
        assert len(problems) == 1 and "'nickname'" in problems[0] and "removed" in problems[0]
        version_links.declare("synthetic", {2: Step(lambda fields: fields, drops=("nickname",))})
        assert definition.link_problems(second, entries) == []

    @MV[32]
    def test_a_rename_is_not_a_drop(self) -> None:
        first = _state(1, {"name": TEXT, "nickname": TEXT})
        second = _state(2, {"name": TEXT, "alias": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, renames={"alias": "nickname"})})
        assert definition.link_problems(second, entries) == []
        version_links.declare("synthetic", {2: Step(lambda fields: fields, renames={"alias": "no_such"})})
        assert any("no_such" in problem for problem in definition.link_problems(second, entries))

    def test_narrowing_and_requiring_need_a_step_that_may_refuse(self) -> None:
        first = _state(1, {"name": TEXT, "note": {"type": "TextField", "null": True}})
        second = _state(
            2,
            {"name": {**TEXT, "max_length": 40}, "note": {"type": "TextField", "null": False}},
            required=["note"],
        )
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields)})
        problems = definition.link_problems(second, entries)
        assert any("'name' is narrowed" in problem for problem in problems)
        assert any("'note' can no longer be empty" in problem for problem in problems)
        assert any("'note' is made required" in problem for problem in problems)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, may_refuse="long names; empty notes")})
        assert definition.link_problems(second, entries) == []

    def test_a_changed_key_must_say_how_keys_cross(self) -> None:
        first, second = _state(1, {"name": TEXT}, key=["name"]), _state(2, {"name": TEXT, "code": TEXT}, key=["code"])
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields)})
        assert any("natural key changes" in problem for problem in definition.link_problems(second, entries))
        version_links.declare("synthetic", {2: Step(lambda fields: fields, key_refused="no code at version 1")})
        assert definition.link_problems(second, entries) == []

    def test_a_break_excuses_any_difference(self) -> None:
        first, second = _state(1, {"name": TEXT, "nickname": TEXT}, key=["name"]), _state(
            2, {"code": TEXT}, key=["code"]
        )
        version_links.declare("synthetic", {2: Break("a different thing")})
        assert definition.link_problems(second, _entries(first, second)) == []

    @MV[33]
    def test_a_field_built_from_two_old_fields_is_refused(self) -> None:
        second = _state(2, {"full_name": TEXT})
        version_links.declare(
            "synthetic", {2: Step(lambda fields: fields, derived={"full_name": ("first_name", "last_name")})}
        )
        problems = definition.link_problems(second, [])
        assert len(problems) == 1 and "'full_name'" in problems[0] and "more than one old field" in problems[0]
        version_links.declare("synthetic", {2: Step(lambda fields: fields, derived={"full_name": "first_name"})})
        assert definition.link_problems(second, []) == []

    def test_an_edge_type_s_removed_and_required_properties_are_held_to_the_step(self) -> None:
        def edge(version: int, rules: dict[str, Any]) -> definition.TypeState:
            body = definition.edge_definition(
                sources=None, targets=None, property_schema=rules, event_time=None, identity=None
            )
            return definition.TypeState(kind=mv.EDGE, slug="SYNTHETIC", version=version, definition=body)

        first = edge(1, {"type": "object", "properties": {"level": {"type": "string"}, "note": {"type": "string"}}})
        second = edge(2, {"type": "object", "required": ["level"], "properties": {"level": {"type": "string"}}})
        entries = _entries(first, second)
        version_links.declare("SYNTHETIC", {2: Step(lambda fields: fields)})
        problems = definition.link_problems(second, entries)
        assert any("'note' is removed" in problem for problem in problems)
        assert any("made required" in problem for problem in problems)
        version_links.declare("SYNTHETIC", {2: Step(lambda fields: fields, drops=("note",), may_refuse="no level")})
        assert definition.link_problems(second, entries) == []

    def test_core_declares_a_link_for_each_version_it_moved_and_no_other(self) -> None:
        """Core declares chains for the spine and for its types above version 1, and for nothing else.

        The guard finds nothing missing, and each chain has one link for every version after the
        first, up to the installed one.
        """
        from tap.guards.model_version import core_problems

        assert core_problems() == []
        moved = {slug: version for slug, version in INSTALLED.items() if version > 1}
        expected = {version_links.SPINE: SPINE, **moved} if SPINE > 1 else moved
        core_chains = {
            slug: sorted(version_links.links_for(slug).links)
            for slug in version_links._declared
            if slug == version_links.SPINE or slug in INSTALLED
        }
        assert core_chains == {slug: list(range(2, version + 1)) for slug, version in expected.items()}

    def test_links_are_found_in_an_app_s_model_links_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        from types import ModuleType

        module = ModuleType("tap_grid.model_links")
        chain = version_links.TypeLinks(links={2: Break("found by name")}, oldest=1)
        module.LINKS = {"discovered_type": chain}  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "tap_grid.model_links", module)
        monkeypatch.setattr(version_links, "_discovered", False)
        assert version_links.links_for("discovered_type") is chain


class TestRecordingARaisedVersion:
    def test_the_command_appends_a_version_one_past_the_record(self) -> None:
        """A version declared one past the record's last entry is what recording is for."""
        first, second = _state(1, {"name": TEXT}), _state(2, {"name": TEXT, "code": TEXT})
        record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
        definition.append_entry(record, first)
        entries = definition.entries_for(record, second)
        assert definition.type_problems(second, entries), "check mode reports the unrecorded version"
        assert not definition.chain_problems(second.label, entries) and entries[-1]["version"] == second.version - 1
        assert definition.append_entry(record, second)


# ---------------------------------------------------------------------------
# A step meets records nothing has validated yet
# ---------------------------------------------------------------------------

_UPGRADE_CODES = {"record_refused_by_upgrade", "upgrade_step_failed"}


class TestStepsOnUnvalidatedRecords:
    """The upgrade runs before validation, so a step's own failure is answered with an issue."""

    @MV[11]
    def test_a_step_that_raises_refuses_the_document_naming_the_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def wrong(fields: dict[str, Any]) -> dict[str, Any]:
            return {"description": fields["summary"] + 1}

        _node_at_2(monkeypatch, Step(wrong, renames={"description": "summary"}))
        good = _node("carried", summary=1)
        bad = _node("not-carried", summary="a secret the message must not quote " * 20)
        result = grift_import(_document(nodes=[good, bad]))
        assert not result.success and _codes(result) == ["upgrade_step_failed"]
        issue = result.errors[0]
        assert issue.path == "$.batches[0].nodes[1].node"
        assert issue.entity_type == NODE and issue.entity_id == bad["entity"]["entity_id"]
        assert "TypeError" in issue.message and "version 1 to 2" in issue.message
        assert "a secret" not in issue.message
        assert not PgNode.objects.filter(entity__name__in=["carried", "not-carried"]).exists()

    @MV[20]
    def test_a_key_function_that_indexes_a_missing_key_refuses_the_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(Panel, "MODEL_VERSION", 2)
        version_links.declare("panel", {2: Step(lambda fields: fields, key=lambda key: {"slug": key["code"]})})
        edge = {
            "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "edge", "dimensions": {}},
            "edge": {
                "edge_type": PLAIN_LINK,
                "properties": {},
                "from_key": {"entity_type": "panel", "key": {"not_code": "x"}},
                "to_key": {"entity_type": "panel", "key": {"code": "target-panel"}},
            },
        }
        result = grift_import(_document(edges=[edge]))
        assert not result.success and _codes(result) == ["upgrade_step_failed"]
        assert result.errors[0].path == "$.batches[0].edges[0].edge.from_key"
        assert "KeyError" in result.errors[0].message and "key function" in result.errors[0].message
        assert not Edge.objects.filter(edge_type=PLAIN_LINK).exists()

    def test_a_refusal_and_a_failure_are_told_apart(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def refuses(fields: dict[str, Any]) -> dict[str, Any]:
            raise RecordRefused("no place for it")

        _node_at_2(monkeypatch, Step(refuses, may_refuse="some records have no place"))
        result = grift_import(_document(nodes=[_node("refused")]))
        assert _codes(result) == ["record_refused_by_upgrade"]

    @pytest.mark.parametrize(
        "spoil",
        [
            pytest.param(lambda batch: batch["nodes"].append("not an object"), id="record-not-an-object"),
            pytest.param(lambda batch: batch["nodes"][0].pop("node"), id="no-fields-block"),
            pytest.param(lambda batch: batch["nodes"][0].update(node=["a", "list"]), id="fields-not-an-object"),
            pytest.param(lambda batch: batch["nodes"][0]["entity"].update(entity_type=7), id="type-not-a-string"),
            pytest.param(lambda batch: batch["nodes"][0].update(entity="nope"), id="envelope-not-an-object"),
            pytest.param(lambda batch: batch.update(nodes={"not": "a list"}), id="nodes-not-a-list"),
            pytest.param(lambda batch: batch.update(edges=[{"edge": 3, "entity": None}]), id="edge-not-an-object"),
        ],
    )
    def test_a_malformed_record_is_left_for_validation_to_report(
        self, monkeypatch: pytest.MonkeyPatch, spoil: Any
    ) -> None:
        """With a step in play, the upgrader's own code raises on no shape and reports none itself."""
        _node_at_2(monkeypatch, RENAME)
        document = _document(nodes=[_node("shape", summary="x")])
        spoil(document["batches"][0])
        outcome = grift_upgrade.upgrade_document(copy.deepcopy(document))
        assert not outcome.refused
        result = grift_import(document)
        assert not result.success
        assert not _UPGRADE_CODES & set(_codes(result))
        assert not PgNode.objects.filter(entity__name="shape").exists()

    def test_a_header_that_is_not_an_object_of_versions_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(spine_version, "SPINE_VERSION", SPINE + 1)
        chain = dict(version_links.links_for(version_links.SPINE).links)
        chain[SPINE + 1] = Step(lambda envelope: envelope)
        version_links.declare(version_links.SPINE, chain)
        document = _document(nodes=[_node("header")])
        document["metadata"]["type_versions"] = ["not", "an", "object"]
        outcome = grift_upgrade.upgrade_document(copy.deepcopy(document))
        assert not outcome.refused
        assert not grift_import(document).success


class TestDeclarationsThatNameNoField:
    """A rename or a derivation accounts for a removed field only where both of its fields are real."""

    @MV[7]
    def test_a_derivation_to_a_field_that_does_not_exist_hides_no_loss(self) -> None:
        first = _state(1, {"name": TEXT, "legacy": TEXT})
        second = _state(2, {"name": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, derived={"nonexistent": "legacy"})})
        problems = definition.link_problems(second, entries)
        assert any("'nonexistent' is not a field of the new version" in problem for problem in problems)
        assert any("'legacy'" in problem and "removed" in problem for problem in problems)

    @MV[7]
    def test_a_derivation_from_a_field_the_old_version_never_had_is_a_problem(self) -> None:
        first = _state(1, {"name": TEXT})
        second = _state(2, {"name": TEXT, "label": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, derived={"label": "never_there"})})
        problems = definition.link_problems(second, entries)
        assert len(problems) == 1 and "'never_there' is not a field of the old version" in problems[0]

    @MV[7]
    def test_a_real_derivation_accounts_for_its_source(self) -> None:
        first = _state(1, {"name": TEXT, "legacy": TEXT})
        second = _state(2, {"name": TEXT, "label": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, derived={"label": "legacy"})})
        assert definition.link_problems(second, entries) == []

    @MV[7]
    def test_a_rename_to_a_field_that_does_not_exist_hides_no_loss(self) -> None:
        first = _state(1, {"name": TEXT, "nickname": TEXT})
        second = _state(2, {"name": TEXT})
        entries = _entries(first, second)
        version_links.declare("synthetic", {2: Step(lambda fields: fields, renames={"nowhere": "nickname"})})
        problems = definition.link_problems(second, entries)
        assert any("'nickname'" in problem and "removed" in problem for problem in problems)
        assert any("renamed to 'nowhere'" in problem for problem in problems)

    @MV[7]
    def test_an_edge_type_s_declarations_are_held_to_the_same(self) -> None:
        def edge_state(version: int, *properties: str) -> definition.TypeState:
            body = {"property_rules": {"properties": {name: {"type": "string"} for name in properties}}}
            return definition.TypeState(kind=mv.EDGE, slug="SYNTHETIC_EDGE", version=version, definition=body)

        first, second = edge_state(1, "weight", "legacy"), edge_state(2, "weight")
        entries = _entries(first, second)
        version_links.declare("SYNTHETIC_EDGE", {2: Step(lambda fields: fields, derived={"nonexistent": "legacy"})})
        problems = definition.link_problems(second, entries)
        assert any("'legacy'" in problem and "removed" in problem for problem in problems)
        assert any("'nonexistent' derived from" in problem for problem in problems)
        version_links.declare("SYNTHETIC_EDGE", {2: Step(lambda fields: fields, drops=("legacy",))})
        assert definition.link_problems(second, entries) == []
