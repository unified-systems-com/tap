"""Tests for the GRIFT v0 importer (tap_grid/grift.py)."""

import uuid
from typing import Any

import pytest

from tap_grid.grift import (
    grift_import,
)
from tap_grid.models import Batch, Edge, Entity

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _batch_entity_id() -> str:
    return str(uuid.uuid4())


def _node_entity_id() -> str:
    return str(uuid.uuid4())


def _edge_entity_id() -> str:
    return str(uuid.uuid4())


def _minimal_doc(batches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Minimal valid GRIFT document."""
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": batches or [],
    }


def _batch_container(
    batch_entity_id: str,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
    batch_node: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "batch_entity": {
            "entity_id": batch_entity_id,
            "entity_type": "batch",
            "name": "Test batch",
            "dimensions": {},
        },
        "batch_node": batch_node
        or {
            "name": "Test batch",
            "description": "",
            "description_json": None,
            "source": "test",
            "metadata": {},
        },
        "nodes": nodes or [],
        "edges": edges or [],
    }


def _character_node(entity_id: str, name: str = "Frodo", description: str = "A hobbit") -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "grid_fixtures__constrained_source",
            "name": name,
            "dimensions": {},
        },
        "node": {"name": name, "description": description},
    }


def _wields_edge(edge_entity_id: str, from_id: str, to_id: str) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": edge_entity_id,
            "entity_type": "edge",
            "dimensions": {},
        },
        "edge": {
            "from_entity_id": from_id,
            "to_entity_id": to_id,
            "edge_type": "SCHEMA_LINK__grid_fixtures",
            "properties": {},
        },
    }


# ---------------------------------------------------------------------------
# Document-level schema tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftDocumentSchema:
    def test_empty_doc_succeeds(self):
        result = grift_import(_minimal_doc())
        assert result.success
        assert result.grift_version == "0"

    def test_invalid_json_string(self):
        result = grift_import("{ not valid json }")
        assert not result.success
        assert result.errors[0].code == "invalid_json"
        assert result.errors[0].phase == "parse"

    def test_missing_metadata_key(self):
        doc = {"_reserved": {}, "batches": []}
        result = grift_import(doc)
        assert not result.success
        assert any(e.code == "schema_validation_failed" and "metadata" in e.message for e in result.errors)

    def test_missing_batches_key(self):
        doc = {"metadata": {"grift_version": "0"}, "_reserved": {}}
        result = grift_import(doc)
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)

    def test_unknown_top_level_key(self):
        doc = _minimal_doc()
        doc["unknown_key"] = "value"
        result = grift_import(doc)
        assert not result.success
        assert any(e.code == "schema_validation_failed" and "unknown_key" in e.message for e in result.errors)

    def test_reserved_object_is_ignored(self):
        doc = _minimal_doc()
        doc["_reserved"] = {"future": "extension"}
        result = grift_import(doc)
        assert result.success

    def test_bytes_input_parsed(self):
        import json

        result = grift_import(json.dumps(_minimal_doc()).encode())
        assert result.success

    def test_missing_grift_version(self):
        doc = {"metadata": {}, "_reserved": {}, "batches": []}
        result = grift_import(doc)
        assert not result.success
        assert any("grift_version" in e.message for e in result.errors)

    def test_unknown_metadata_key(self):
        doc = _minimal_doc()
        doc["metadata"]["extra"] = "x"
        result = grift_import(doc)
        assert not result.success


# ---------------------------------------------------------------------------
# Entity envelope validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftEnvelopeValidation:
    def test_batch_entity_type_not_batch_fails(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        container["batch_entity"]["entity_type"] = "grid_fixtures__constrained_source"
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any(e.code == "entity_type_mismatch" for e in result.errors)

    def test_edge_entity_type_not_edge_fails(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        aid = _node_entity_id()
        eid = _edge_entity_id()
        char = _character_node(nid)
        char2 = _character_node(aid, name="Sam")
        edge = _wields_edge(eid, nid, aid)
        edge["entity"]["entity_type"] = "wrong"
        container = _batch_container(bid, nodes=[char, char2], edges=[edge])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any(e.code == "entity_type_mismatch" for e in result.errors)

    def test_missing_required_envelope_field(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        del container["batch_entity"]["entity_id"]
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any("entity_id" in e.message for e in result.errors)

    def test_invalid_uuid_in_envelope(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        container["batch_entity"]["entity_id"] = "not-a-uuid"
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)

    def test_unknown_key_in_envelope_rejected(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        container["batch_entity"]["sneaky"] = "extra"
        result = grift_import(_minimal_doc([container]))
        assert not result.success

    def test_name_empty_string_rejected(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        container["batch_entity"]["name"] = ""
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any("name" in e.message or "non-empty" in e.message or "too short" in e.message for e in result.errors)

    def test_dimensions_non_string_value_rejected(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        container["batch_entity"]["dimensions"] = {"key": 123}
        result = grift_import(_minimal_doc([container]))
        assert not result.success


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftDuplicateDetection:
    def test_duplicate_entity_id_across_batches_fails(self):
        shared_id = _node_entity_id()
        bid1 = _batch_entity_id()
        bid2 = _batch_entity_id()
        container1 = _batch_container(bid1, nodes=[_character_node(shared_id)])
        container2 = _batch_container(bid2, nodes=[_character_node(shared_id, name="Sam")])
        result = grift_import(_minimal_doc([container1, container2]))
        assert not result.success
        assert any(e.code == "duplicate_entity_id" for e in result.errors)

    def test_duplicate_batch_entity_id_fails(self):
        shared_bid = _batch_entity_id()
        container1 = _batch_container(shared_bid)
        container2 = _batch_container(shared_bid)
        result = grift_import(_minimal_doc([container1, container2]))
        assert not result.success
        assert any(e.code == "duplicate_batch_id" for e in result.errors)


# ---------------------------------------------------------------------------
# Unknown entity type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftUnknownEntityType:
    def test_unknown_node_type_fails(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        node = {
            "entity": {"entity_id": nid, "entity_type": "nonexistent_type", "dimensions": {}},
            "node": {"name": "X"},
        }
        container = _batch_container(bid, nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any(e.code == "unknown_entity_type" for e in result.errors)


# ---------------------------------------------------------------------------
# Dangling edge handling
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-import-grift-dangling-1")
@pytest.mark.django_db
class TestGriftDanglingEdges:
    def test_dangling_edge_strict_fails_preflight(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        ghost_id = str(uuid.uuid4())  # never imported / not in grid
        eid = _edge_entity_id()

        char = _character_node(nid)
        edge = _wields_edge(eid, nid, ghost_id)
        container = _batch_container(bid, nodes=[char], edges=[edge])

        result = grift_import(_minimal_doc([container]), dangling_edge_mode="strict")
        assert not result.success
        assert any(e.code == "dangling_edge" for e in result.errors)
        assert result.counts.batches_imported == 0

    def test_dangling_edge_permissive_skips_edge(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        ghost_id = str(uuid.uuid4())
        eid = _edge_entity_id()

        char = _character_node(nid)
        edge = _wields_edge(eid, nid, ghost_id)
        container = _batch_container(bid, nodes=[char], edges=[edge])

        result = grift_import(_minimal_doc([container]), dangling_edge_mode="permissive")
        assert result.success
        assert result.counts.nodes_imported == 1
        assert result.counts.edges_skipped == 1
        assert result.counts.edges_imported == 0


# ---------------------------------------------------------------------------
# Upsert: create path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftUpsertCreate:
    def test_creates_node_with_preserved_entity_id(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid)
        container = _batch_container(bid, nodes=[char])

        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert result.counts.nodes_imported == 1
        assert Entity.objects.filter(pk=uuid.UUID(nid)).exists()

    def test_creates_edge_with_preserved_entity_id(self):
        bid = _batch_entity_id()
        nid1 = _node_entity_id()
        nid2 = _node_entity_id()
        eid = _edge_entity_id()

        char1 = _character_node(nid1, name="Frodo")
        artifact_id = nid2
        artifact_node = {
            "entity": {"entity_id": artifact_id, "entity_type": "grid_fixtures__dual_endpoint", "dimensions": {}},
            "node": {"name": "Sting", "description": "glows", "kind": "Erebor"},
        }
        edge = _wields_edge(eid, nid1, artifact_id)
        container = _batch_container(bid, nodes=[char1, artifact_node], edges=[edge])

        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert result.counts.nodes_imported == 2
        assert result.counts.edges_imported == 1
        assert Entity.objects.filter(pk=uuid.UUID(eid), entity_type="edge").exists()
        assert Edge.objects.filter(entity_id=uuid.UUID(eid)).exists()

    def test_creates_batch_with_preserved_entity_id(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert Batch.objects.filter(entity_id=bid).exists()

    def test_import_result_contains_batch_summary(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        container = _batch_container(bid, nodes=[_character_node(nid)])
        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert len(result.imported_batches) == 1
        assert result.imported_batches[0].batch_entity_id == bid
        assert result.imported_batches[0].nodes_imported == 1


# ---------------------------------------------------------------------------
# Upsert: replace path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftUpsertReplace:
    def test_replaces_existing_node_on_second_import(self):
        bid1 = _batch_entity_id()
        nid = _node_entity_id()

        # First import creates the character.
        char = _character_node(nid, name="Frodo", description="Original bio")
        result1 = grift_import(_minimal_doc([_batch_container(bid1, nodes=[char])]))
        assert result1.success

        # Second import replaces with updated data under a new batch.
        bid2 = _batch_entity_id()
        updated_char = _character_node(nid, name="Frodo Updated", description="Updated bio")
        result2 = grift_import(_minimal_doc([_batch_container(bid2, nodes=[updated_char])]))
        assert result2.success
        assert result2.counts.nodes_imported == 1

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        char_obj = ConstrainedSource.objects.get(entity_id=uuid.UUID(nid))
        assert char_obj.name == "Frodo Updated"
        assert char_obj.description == "Updated bio"


# ---------------------------------------------------------------------------
# Idempotency: batch-level skip
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-import-grift-identity-1")
@pytest.mark.django_db
class TestGriftIdempotency:
    def test_same_batch_skipped_on_second_import(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid)
        container = _batch_container(bid, nodes=[char])
        doc = _minimal_doc([container])

        result1 = grift_import(doc)
        assert result1.success
        assert result1.counts.batches_imported == 1

        result2 = grift_import(doc)
        assert result2.success
        assert result2.counts.batches_imported == 0
        assert result2.counts.batches_skipped == 1
        assert len(result2.skipped_batches) == 1
        assert result2.skipped_batches[0].batch_entity_id == bid
        assert result2.skipped_batches[0].reason == "batch_already_imported"

    def test_skipped_batch_does_not_duplicate_entities(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid)
        container = _batch_container(bid, nodes=[char])
        doc = _minimal_doc([container])

        grift_import(doc)
        grift_import(doc)

        assert Entity.objects.filter(pk=uuid.UUID(nid)).count() == 1


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-import-grift-provenance-1")
@pytest.mark.django_db
class TestGriftProvenance:
    def test_description_json_records_importer_metadata(self):
        bid = _batch_entity_id()
        container = _batch_container(bid)
        result = grift_import(_minimal_doc([container]))
        assert result.success

        batch = Batch.objects.get(entity_id=bid)
        assert batch.description_json is not None
        assert batch.description_json["format"] == "tap.grift.import.v0"
        data = batch.description_json["data"]
        assert data["importer"] == "grift"
        assert data["grift_version"] == "0"
        assert data["import_mode"] == "upsert"
        assert data["source_batch_entity_id"] == bid

    def test_custom_format_preserved_importer_metadata_nested(self):
        """Incoming batch with a non-importer format keeps its format; importer
        metadata nests under reserved key `_tap_grift_import`."""
        bid = _batch_entity_id()
        batch_node = {
            "name": "Caller batch",
            "description": "",
            "description_json": {
                "format": "example.caller.v1",
                "data": {"caller_key": "caller_value", "nested": {"k": 1}},
            },
            "source": "test",
            "metadata": {},
        }
        container = _batch_container(bid, batch_node=batch_node)
        result = grift_import(_minimal_doc([container]))
        assert result.success

        batch = Batch.objects.get(entity_id=bid)
        assert batch.description_json["format"] == "example.caller.v1"
        data = batch.description_json["data"]
        # Caller-owned keys survive.
        assert data["caller_key"] == "caller_value"
        assert data["nested"] == {"k": 1}
        # Importer metadata lives under the reserved key.
        importer = data["_tap_grift_import"]
        assert importer["importer"] == "grift"
        assert importer["grift_version"] == "0"
        assert importer["import_mode"] == "upsert"
        assert importer["source_batch_entity_id"] == bid

    def test_legacy_importer_format_is_overwritten(self):
        """Incoming format `tap.grift.import.v0` is overwritten entirely — no
        nested duplicates."""
        bid = _batch_entity_id()
        batch_node = {
            "name": "Replay batch",
            "description": "",
            "description_json": {
                "format": "tap.grift.import.v0",
                "data": {"importer": "stale", "imported_at": "1970-01-01T00:00:00Z"},
            },
            "source": "test",
            "metadata": {},
        }
        container = _batch_container(bid, batch_node=batch_node)
        result = grift_import(_minimal_doc([container]))
        assert result.success

        batch = Batch.objects.get(entity_id=bid)
        assert batch.description_json["format"] == "tap.grift.import.v0"
        data = batch.description_json["data"]
        # Fresh importer data present, stale timestamp gone.
        assert data["importer"] == "grift"
        assert data["imported_at"] != "1970-01-01T00:00:00Z"
        # No nested _tap_grift_import — the whole block was overwritten, not nested.
        assert "_tap_grift_import" not in data

    def test_malformed_description_json_falls_back_to_importer_format(self):
        """Incoming description_json with non-dict data falls back to
        importer-only output instead of crashing."""
        bid = _batch_entity_id()
        batch_node = {
            "name": "Malformed batch",
            "description": "",
            "description_json": {"format": "example.bad", "data": "not an object"},
            "source": "test",
            "metadata": {},
        }
        container = _batch_container(bid, batch_node=batch_node)
        result = grift_import(_minimal_doc([container]))
        assert result.success

        batch = Batch.objects.get(entity_id=bid)
        assert batch.description_json["format"] == "tap.grift.import.v0"
        data = batch.description_json["data"]
        assert data["importer"] == "grift"

    def test_result_import_mode_is_upsert(self):
        result = grift_import(_minimal_doc())
        assert result.import_mode == "upsert"

    def test_result_reference_time_is_set(self):
        result = grift_import(_minimal_doc())
        assert result.reference_time
        # Basic RFC 3339 sanity: contains "T"
        assert "T" in result.reference_time


# ---------------------------------------------------------------------------
# Identity sanity: entity_type consistency
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-import-grift-identity-2")
@pytest.mark.django_db
class TestGriftIdentitySanity:
    def test_existing_entity_wrong_type_fails_preflight(self):
        """If an entity_id exists in the grid as a different type, preflight fails."""
        bid1 = _batch_entity_id()
        nid = _node_entity_id()

        # First import: creates a character.
        result1 = grift_import(_minimal_doc([_batch_container(bid1, nodes=[_character_node(nid)])]))
        assert result1.success

        # Second import: same entity_id but now claims it's an artifact.
        bid2 = _batch_entity_id()
        wrong_type_node = {
            "entity": {"entity_id": nid, "entity_type": "grid_fixtures__dual_endpoint", "dimensions": {}},
            "node": {"name": "Sting", "description": "glows", "kind": "Erebor"},
        }
        result2 = grift_import(_minimal_doc([_batch_container(bid2, nodes=[wrong_type_node])]))
        assert not result2.success
        assert any(e.code == "entity_type_mismatch" and e.entity_id == nid for e in result2.errors)
        assert result2.counts.batches_imported == 0

    def test_existing_entity_matching_type_succeeds(self):
        """Re-importing an entity with the same entity_type passes preflight."""
        bid1 = _batch_entity_id()
        nid = _node_entity_id()
        result1 = grift_import(_minimal_doc([_batch_container(bid1, nodes=[_character_node(nid)])]))
        assert result1.success

        bid2 = _batch_entity_id()
        result2 = grift_import(
            _minimal_doc([_batch_container(bid2, nodes=[_character_node(nid, name="Frodo Updated")])])
        )
        assert result2.success


# ---------------------------------------------------------------------------
# Multi-batch document
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftMultiBatch:
    def test_two_batches_both_imported(self):
        bid1 = _batch_entity_id()
        bid2 = _batch_entity_id()
        nid1 = _node_entity_id()
        nid2 = _node_entity_id()

        doc = _minimal_doc(
            [
                _batch_container(bid1, nodes=[_character_node(nid1, name="Frodo")]),
                _batch_container(bid2, nodes=[_character_node(nid2, name="Sam")]),
            ]
        )

        result = grift_import(doc)
        assert result.success
        assert result.counts.batches_imported == 2
        assert result.counts.nodes_imported == 2
        assert Entity.objects.filter(pk=uuid.UUID(nid1)).exists()
        assert Entity.objects.filter(pk=uuid.UUID(nid2)).exists()

    def test_second_batch_skipped_first_imported(self):
        bid1 = _batch_entity_id()
        bid2 = _batch_entity_id()
        nid1 = _node_entity_id()
        nid2 = _node_entity_id()

        doc1 = _minimal_doc([_batch_container(bid2, nodes=[_character_node(nid2, name="Sam")])])
        grift_import(doc1)

        doc2 = _minimal_doc(
            [
                _batch_container(bid1, nodes=[_character_node(nid1, name="Frodo")]),
                _batch_container(bid2, nodes=[_character_node(nid2, name="Sam")]),
            ]
        )
        result = grift_import(doc2)
        assert result.success
        assert result.counts.batches_imported == 1
        assert result.counts.batches_skipped == 1


# ---------------------------------------------------------------------------
# Envelope dimensions merged onto imported entities (req-grid-dimension-dc-5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGriftEnvelopeDimensions:
    """GRIFT imports honor envelope.dimensions on create (req-grid-dimension-dc-5)."""

    def _dimension_node(self, entity_id: str, envelope_dims: dict[str, str]) -> dict[str, Any]:
        return {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "dimension",
                "name": "scoped-dim",
                "dimensions": envelope_dims,
            },
            "node": {"name": "scoped-dim", "description": ""},
        }

    def test_envelope_dims_merged_with_model_defaults(self):
        """Envelope dimensions merge with DEFAULT_DIMENSIONS; non-overlapping keys both present."""
        batch_id = _batch_entity_id()
        node_id = _node_entity_id()
        doc = _minimal_doc(
            [
                _batch_container(
                    batch_id,
                    nodes=[self._dimension_node(node_id, {"tap.env": "genericom-prod"})],
                )
            ]
        )
        result = grift_import(doc)
        assert result.success, result.issues

        entity = Entity.objects.get(pk=uuid.UUID(node_id))
        assert entity.dimensions == {"tap.meta": "dimension", "tap.env": "genericom-prod"}

    def test_envelope_dims_override_model_defaults(self):
        """Envelope key wins over colliding DEFAULT_DIMENSIONS key."""
        batch_id = _batch_entity_id()
        node_id = _node_entity_id()
        doc = _minimal_doc(
            [
                _batch_container(
                    batch_id,
                    nodes=[self._dimension_node(node_id, {"tap.meta": "overridden"})],
                )
            ]
        )
        result = grift_import(doc)
        assert result.success

        entity = Entity.objects.get(pk=uuid.UUID(node_id))
        assert entity.dimensions == {"tap.meta": "overridden"}

    def test_empty_envelope_dims_leaves_only_model_defaults(self):
        """Empty envelope dimensions still applies DEFAULT_DIMENSIONS."""
        batch_id = _batch_entity_id()
        node_id = _node_entity_id()
        doc = _minimal_doc([_batch_container(batch_id, nodes=[self._dimension_node(node_id, {})])])
        result = grift_import(doc)
        assert result.success

        entity = Entity.objects.get(pk=uuid.UUID(node_id))
        assert entity.dimensions == {"tap.meta": "dimension"}


# ---------------------------------------------------------------------------
# Force re-import + batch-scoped sweep + purge
#   spec-grid-import-grift.md req-grid-import-grift-force-reimport
#                             req-grid-import-grift-batch-scoped-sweep
#                             req-grid-import-grift-sweep-purge
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-import-grift-force-reimport-1")
@pytest.mark.django_db
class TestGriftForceReimport:
    @pytest.fixture(autouse=True)
    def _debug_on(self, settings):
        """Most tests exercise force re-import, which requires DEBUG=True.
        Individual tests that verify the gate flip DEBUG back to False locally."""
        settings.DEBUG = True

    def _initial_doc(self, batch_id: str, node_ids: list[str]) -> dict[str, Any]:
        return _minimal_doc(
            [
                _batch_container(
                    batch_id,
                    nodes=[_character_node(nid, name=f"char-{i}") for i, nid in enumerate(node_ids)],
                )
            ]
        )

    def test_force_reimport_re_applies_edited_content(self):
        """A revised batch passed via force_batches updates nodes that changed."""
        from tap_grid.models import BatchEvent, BatchEventType

        bid = _batch_entity_id()
        nid = _node_entity_id()
        result = grift_import(self._initial_doc(bid, [nid]))
        assert result.success

        # Revise node payload and force re-import.
        revised = _minimal_doc(
            [_batch_container(bid, nodes=[_character_node(nid, name="Renamed", description="New bio")])]
        )
        result2 = grift_import(revised, force_batches=[bid])
        assert result2.success, result2.errors
        assert result2.counts.batches_force_reimported == 1

        # Payload updated in place.
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        c = ConstrainedSource.objects.get(entity_id=uuid.UUID(nid))
        assert c.name == "Renamed"
        assert c.description == "New bio"

        # FORCE_REIMPORT audit event landed.
        evt = BatchEvent.objects.filter(batch__entity_id=bid, event_type=BatchEventType.FORCE_REIMPORT).first()
        assert evt is not None
        assert evt.metadata.get("purge") is False

    def test_force_reimport_refused_without_debug(self, settings):
        """DEBUG=False rejects force re-import with a dedicated error code."""
        settings.DEBUG = False
        bid = _batch_entity_id()
        doc = self._initial_doc(bid, [_node_entity_id()])
        result = grift_import(doc, force_batches=[bid])
        assert not result.success
        assert any(e.code == "force_reimport_refused_production" for e in result.errors)

    def test_purge_requires_force_batches(self):
        """--purge without --force-batches is rejected at the API."""
        result = grift_import(_minimal_doc([]), purge=True)
        assert not result.success
        assert any(e.code == "purge_requires_force_reimport" for e in result.errors)

    def test_purge_refused_without_debug(self, settings):
        """DEBUG=False rejects --purge even when --force-batches is passed."""
        settings.DEBUG = False
        bid = _batch_entity_id()
        doc = self._initial_doc(bid, [_node_entity_id()])
        result = grift_import(doc, force_batches=[bid], purge=True)
        assert not result.success
        # Both gates trip; purge-specific error is reported.
        assert any(
            e.code in ("sweep_purge_refused_production", "force_reimport_refused_production") for e in result.errors
        )

    def test_sweep_tombstones_orphan_nodes(self):
        """A revised batch dropping a node tombstones it via the sweep."""
        bid = _batch_entity_id()
        nid_keep = _node_entity_id()
        nid_drop = _node_entity_id()
        grift_import(self._initial_doc(bid, [nid_keep, nid_drop]))

        revised = _minimal_doc([_batch_container(bid, nodes=[_character_node(nid_keep, name="char-0")])])
        result = grift_import(revised, force_batches=[bid])
        assert result.success, result.errors

        # Swept entity reported.
        batch_summary = result.imported_batches[0]
        swept_ids = {s.entity_id for s in batch_summary.swept_entities}
        assert nid_drop in swept_ids
        assert nid_keep not in swept_ids

        # Tombstone applied (entity present but soft-deleted).
        dropped = Entity.objects.get(pk=uuid.UUID(nid_drop))
        assert dropped.deleted_at is not None
        kept = Entity.objects.get(pk=uuid.UUID(nid_keep))
        assert kept.deleted_at is None

    def test_sweep_skips_externally_written_entity(self):
        """Guardrail A — an entity touched by a different batch is skipped."""
        from tap_grid.batch import create_batch
        from tap_grid.caller_context import CallerContext, get_caller_context
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import write_batch

        bid = _batch_entity_id()
        nid = _node_entity_id()
        grift_import(self._initial_doc(bid, [nid]))

        # Another batch updates the node after initial import.
        other_batch = create_batch(name="other")
        ctx = CallerContext(user=get_caller_context().user, batch_id=str(other_batch.entity_id))
        write_batch(
            [WriteOperation(verb="replace_node", target=nid, payload={"name": "Touched", "description": "By other"})],
            caller_context=ctx,
        )

        # Revise the batch to drop the node — sweep should skip via Guardrail A.
        revised = _minimal_doc([_batch_container(bid, nodes=[])])
        result = grift_import(revised, force_batches=[bid])
        assert result.success, result.errors

        summary = result.imported_batches[0]
        assert len(summary.sweep_skipped) == 1
        assert summary.sweep_skipped[0].reason == "sweep_skipped_external_write"
        assert summary.sweep_skipped[0].entity_id == nid

        # Entity survives.
        kept = Entity.objects.get(pk=uuid.UUID(nid))
        assert kept.deleted_at is None

    def test_sweep_skips_referenced_entity(self):
        """Guardrail B — a node candidate with a surviving edge is skipped."""
        bid = _batch_entity_id()
        wielder = _node_entity_id()
        artifact = _node_entity_id()
        edge_id = _edge_entity_id()

        def _artifact_node(nid: str, name: str) -> dict[str, Any]:
            return {
                "entity": {
                    "entity_id": nid,
                    "entity_type": "grid_fixtures__dual_endpoint",
                    "name": name,
                    "dimensions": {},
                },
                "node": {"name": name, "description": "modest", "kind": "Valinor"},
            }

        initial = _minimal_doc(
            [
                _batch_container(
                    bid,
                    nodes=[_character_node(wielder, "Wielder"), _artifact_node(artifact, "Ring")],
                    edges=[_wields_edge(edge_id, wielder, artifact)],
                )
            ]
        )
        r0 = grift_import(initial)
        assert r0.success, r0.errors

        # Revise to drop the artifact NODE but keep the edge referencing it.
        # The edge's to_entity_id still points at a grid entity (artifact is
        # present from the initial import), so preflight doesn't trip. After
        # the upsert phase the artifact is a sweep candidate; Guardrail B
        # sees the surviving edge and skips the sweep.
        revised = _minimal_doc(
            [
                _batch_container(
                    bid,
                    nodes=[_character_node(wielder, "Wielder")],
                    edges=[_wields_edge(edge_id, wielder, artifact)],
                )
            ]
        )
        result = grift_import(revised, force_batches=[bid])
        assert result.success, result.errors
        assert len(result.imported_batches) == 1
        summary = result.imported_batches[0]
        reasons = {s.reason for s in summary.sweep_skipped}
        assert "sweep_skipped_referenced" in reasons
        # DualEndpoint should still be live (not tombstoned).
        live = Entity.objects.get(pk=uuid.UUID(artifact))
        assert live.deleted_at is None

    def test_sweep_strict_aborts_on_guardrail_miss(self):
        """--sweep-strict aborts the entire force re-import if any candidate fails."""
        from tap_grid.batch import create_batch
        from tap_grid.caller_context import CallerContext, get_caller_context
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import write_batch

        bid = _batch_entity_id()
        nid_keep = _node_entity_id()
        nid_drop = _node_entity_id()
        grift_import(self._initial_doc(bid, [nid_keep, nid_drop]))

        # Another batch touches nid_drop so it fails Guardrail A.
        other_batch = create_batch(name="external")
        ctx = CallerContext(user=get_caller_context().user, batch_id=str(other_batch.entity_id))
        write_batch(
            [WriteOperation(verb="replace_node", target=nid_drop, payload={"name": "Touched", "description": "X"})],
            caller_context=ctx,
        )

        # Strict-mode force re-import should abort — no writes applied.
        revised = _minimal_doc(
            [_batch_container(bid, nodes=[_character_node(nid_keep, name="Changed", description="Y")])]
        )
        result = grift_import(revised, force_batches=[bid], sweep_strict=True)
        assert not result.success
        assert any(e.code == "sweep_strict_aborted" for e in result.errors)

        # Name change on nid_keep was rolled back.
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        unchanged = ConstrainedSource.objects.get(entity_id=uuid.UUID(nid_keep))
        assert unchanged.name == "char-0"  # original

    def test_purge_hard_deletes_orphans(self):
        """--purge removes the entity and its batch-scoped BatchEvent rows."""
        from tap_grid.models import BatchEvent

        bid = _batch_entity_id()
        nid = _node_entity_id()
        grift_import(self._initial_doc(bid, [nid]))

        # Confirm entity + its BatchEvent exist.
        assert Entity.objects.filter(pk=uuid.UUID(nid)).exists()
        assert BatchEvent.objects.filter(entity_id=uuid.UUID(nid)).exists()

        # Revise to drop the node, purge enabled.
        revised = _minimal_doc([_batch_container(bid, nodes=[])])
        result = grift_import(revised, force_batches=[bid], purge=True)
        assert result.success, result.errors

        summary = result.imported_batches[0]
        assert any(s.action == "purge" for s in summary.swept_entities)

        # Entity and its BatchEvent rows are gone from the DB.
        assert not Entity.objects.filter(pk=uuid.UUID(nid)).exists()
        assert not BatchEvent.objects.filter(entity_id=uuid.UUID(nid)).exists()

    def test_force_reimport_unnamed_batch_reports_not_found(self):
        """force_batches naming an unknown id emits a diagnostic error."""
        bogus = str(uuid.uuid4())
        result = grift_import(_minimal_doc([]), force_batches=[bogus])
        assert not result.success
        assert any(e.code == "force_reimport_batch_not_found" for e in result.errors)


# ---------------------------------------------------------------------------
# Identity Sanity: envelope/payload name match
# (req-grid-import-grift-preflight "Envelope/Payload Name Match")
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEnvelopePayloadNameMatch:
    def _node_with_names(self, entity_id: str, envelope_name: str | None, payload_name: str) -> dict[str, Any]:
        envelope: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": "grid_fixtures__constrained_source",
            "dimensions": {},
        }
        if envelope_name is not None:
            envelope["name"] = envelope_name
        return {
            "entity": envelope,
            "node": {"name": payload_name, "description": "A hobbit"},
        }

    def test_matched_names_pass_preflight(self):
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name="Frodo", payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert not any(e.code == "envelope_payload_name_mismatch" for e in result.errors)

    def test_envelope_name_omitted_passes(self):
        """Bundles that omit envelope.name keep working — the spine projection
        is materialized from the model's name on import."""
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name=None, payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert not any(e.code == "envelope_payload_name_mismatch" for e in result.errors)

    def test_envelope_name_empty_rejected_by_schema(self):
        """Explicitly-empty envelope.name is rejected at the document-schema
        layer before the mismatch check runs. This makes the mismatch
        check's empty-envelope-name guard belt-and-suspenders, never the
        primary defense."""
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name="", payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)
        assert not any(e.code == "envelope_payload_name_mismatch" for e in result.errors)

    def test_whitespace_only_difference_passes(self):
        """Surrounding whitespace is trimmed before comparison."""
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name="  Frodo  ", payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert result.success
        assert not any(e.code == "envelope_payload_name_mismatch" for e in result.errors)

    def test_mismatch_fails_preflight(self):
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name="Bilbo", payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        mismatches = [e for e in result.errors if e.code == "envelope_payload_name_mismatch"]
        assert len(mismatches) == 1
        # Issue carries enough context to be operator-actionable.
        assert mismatches[0].entity_id == nid
        assert mismatches[0].entity_type == "grid_fixtures__constrained_source"
        assert "Bilbo" in mismatches[0].message and "Frodo" in mismatches[0].message
        assert mismatches[0].path.endswith(".entity.name")

    def test_mismatches_accrue_across_file(self):
        """Multiple offending nodes each produce their own issue; preflight
        does not stop at the first mismatch."""
        nid_a = _node_entity_id()
        nid_b = _node_entity_id()
        node_a = self._node_with_names(nid_a, envelope_name="X", payload_name="A")
        node_b = self._node_with_names(nid_b, envelope_name="Y", payload_name="B")
        container = _batch_container(_batch_entity_id(), nodes=[node_a, node_b])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        mismatches = [e for e in result.errors if e.code == "envelope_payload_name_mismatch"]
        offending_ids = {e.entity_id for e in mismatches}
        assert offending_ids == {nid_a, nid_b}

    def test_mismatch_blocks_writes(self):
        """A failing preflight must not mutate the database."""
        nid = _node_entity_id()
        node = self._node_with_names(nid, envelope_name="Bilbo", payload_name="Frodo")
        container = _batch_container(_batch_entity_id(), nodes=[node])
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert not Entity.objects.filter(pk=uuid.UUID(nid)).exists()


# ---------------------------------------------------------------------------
# Hotlink integration: GRIFT upsert with hotlink-bearing nodes
# req-grid-hotlink-deferred ↔ req-grid-service-batch-precommit-consistency
# ---------------------------------------------------------------------------


def _page_node(entity_id: str, slug: str, panel_ids: list[str], name: str = "P") -> dict[str, Any]:
    rows = {f"row-{i + 1}": {"panel-id": pid} for i, pid in enumerate(panel_ids)}
    layout = {"columns": {"col-1": {"width": "1fr", "rows": rows}}}
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "page",
            "name": name,
            "dimensions": {"tap.graph": "web"},
        },
        "node": {"name": name, "slug": slug, "description": "", "layout": layout},
    }


def _panel_node(entity_id: str, slug: str, name: str = "Panel") -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "panel",
            "name": name,
            "dimensions": {"tap.graph": "web"},
        },
        "node": {"name": name, "slug": slug, "description": "", "view": "tap_web/panel_error.html"},
    }


def _uses_panel_edge(edge_entity_id: str, from_id: str, to_id: str, panel_id: str) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": edge_entity_id,
            "entity_type": "edge",
            "dimensions": {"tap.graph": "web"},
        },
        "edge": {
            "from_entity_id": from_id,
            "to_entity_id": to_id,
            "edge_type": "USES_PANEL",
            "properties": {"hotlink": {"model": "page", "spec": "page-panels", "value": panel_id}},
        },
    }


@pytest.mark.django_db
class TestGriftHotlinkUpsert:
    """GRIFT bundles that mix hotlink-bearing nodes with their edges must
    succeed on upsert. This exercises req-grid-hotlink-deferred end-to-end via
    the importer (which goes through write_batch).
    """

    def test_upsert_revising_layout_with_new_edge_in_same_batch(self):
        """The originating bug: re-importing a page whose new layout references
        a panel-id whose USES_PANEL edge is in the same batch."""
        # Bundle 1: page + one panel + matching edge.
        b1 = _batch_entity_id()
        page_id = _node_entity_id()
        panel_a_id = _node_entity_id()
        edge_a_id = _edge_entity_id()

        page_v1 = _page_node(page_id, "/grift-hotlink", panel_ids=["a"])
        panel_a = _panel_node(panel_a_id, "panel-a")
        edge_a = _uses_panel_edge(edge_a_id, page_id, panel_a_id, "a")

        result1 = grift_import(_minimal_doc([_batch_container(b1, nodes=[page_v1, panel_a], edges=[edge_a])]))
        assert result1.success, result1.errors

        # Bundle 2: re-import the page with revised layout referencing a NEW
        # panel-id "b", plus the new panel node and the new USES_PANEL edge
        # in the SAME batch. Pre-fix this failed because the importer ran
        # replace_node and validate_hotlinks fired against the old edge set.
        b2 = _batch_entity_id()
        panel_b_id = _node_entity_id()
        edge_b_id = _edge_entity_id()

        page_v2 = _page_node(page_id, "/grift-hotlink", panel_ids=["a", "b"])
        panel_b = _panel_node(panel_b_id, "panel-b")
        edge_b = _uses_panel_edge(edge_b_id, page_id, panel_b_id, "b")

        result2 = grift_import(_minimal_doc([_batch_container(b2, nodes=[page_v2, panel_b], edges=[edge_b])]))
        assert result2.success, result2.errors

        # Verify post-upsert graph: page has both edges, layout has both rows.
        from tap_grid.models import Edge as EdgeModel
        from tap_web.models import Page

        page = Page.objects.get(entity_id=uuid.UUID(page_id))
        rows = page.layout["columns"]["col-1"]["rows"]
        assert {r["panel-id"] for r in rows.values()} == {"a", "b"}
        edge_values = {
            (e.properties or {}).get("hotlink", {}).get("value")
            for e in EdgeModel.objects.filter(from_entity_id=uuid.UUID(page_id), edge_type="USES_PANEL")
        }
        assert edge_values == {"a", "b"}

    def test_grift_bundle_with_inconsistent_hotlink_fails_loudly(self):
        """A GRIFT bundle whose page layout references a panel-id that has no
        matching edge anywhere in the bundle must fail with a clear error and
        leave the graph unchanged."""
        bid = _batch_entity_id()
        page_id = _node_entity_id()
        panel_a_id = _node_entity_id()
        edge_a_id = _edge_entity_id()

        # Layout references "a" AND "ghost", but only the "a" edge is provided.
        page = _page_node(page_id, "/grift-hotlink-bad", panel_ids=["a", "ghost"])
        panel_a = _panel_node(panel_a_id, "panel-a-bad")
        edge_a = _uses_panel_edge(edge_a_id, page_id, panel_a_id, "a")

        result = grift_import(_minimal_doc([_batch_container(bid, nodes=[page, panel_a], edges=[edge_a])]))
        assert not result.success
        # The failure should surface as an execution-phase issue (the importer
        # translates per-op errors into "execution_failed" issues; the per-op
        # WriteResult carries the hotlink_validation_failed code internally).
        assert any("hotlink" in (issue.code + issue.message).lower() for issue in result.errors), [
            (i.code, i.message) for i in result.errors
        ]
        # Atomic rollback — no page persisted.
        assert not Entity.objects.filter(pk=uuid.UUID(page_id)).exists()


# ---------------------------------------------------------------------------
# Imperative removal sections (req-grift-import-deletes,
# req-grid-import-grift-removals, req-grid-import-grift-removal-preflight)
# ---------------------------------------------------------------------------


def _container_with_removals(
    batch_entity_id: str,
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    deletes: dict | None = None,
    purges: dict | None = None,
) -> dict[str, Any]:
    """Variant of _batch_container that includes optional removal sections."""
    c = _batch_container(batch_entity_id, nodes=nodes, edges=edges)
    if deletes is not None:
        c["deletes"] = deletes
    if purges is not None:
        c["purges"] = purges
    return c


def _remove_target(entity_id: str, entity_type: str, reason: str = "test") -> dict:
    return {"entity_id": entity_id, "entity_type": entity_type, "reason": reason}


@pytest.mark.spec("req-grid-import-grift-removal-preflight-1")
@pytest.mark.django_db
class TestGriftRemovalPreflightShape:
    """File-preflight: shape, duplicates, DEBUG gate."""

    def test_deletes_section_requires_policy_fields(self):
        bid = _batch_entity_id()
        # Missing on_missing.
        deletes = {"on_tombstoned": "ignore", "edges": [], "nodes": []}
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" and "on_missing" in e.message for e in result.errors)

    def test_purges_section_does_not_have_on_tombstoned(self):
        bid = _batch_entity_id()
        purges = {"on_missing": "error", "on_tombstoned": "ignore", "edges": [], "nodes": []}
        # Settings.DEBUG=True in tests, so the gate would pass — but
        # additionalProperties=false rejects the extra key first.
        result = grift_import(_minimal_doc([_container_with_removals(bid, purges=purges)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)

    def test_invalid_policy_value_rejected(self):
        bid = _batch_entity_id()
        deletes = {"on_missing": "bogus", "on_tombstoned": "ignore", "edges": [], "nodes": []}
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)

    def test_target_requires_reason(self):
        bid = _batch_entity_id()
        target = {"entity_id": _node_entity_id(), "entity_type": "grid_fixtures__constrained_source"}  # missing reason
        deletes = {"on_missing": "error", "on_tombstoned": "ignore", "edges": [], "nodes": [target]}
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" and "reason" in e.message for e in result.errors)

    def test_duplicate_target_within_sub_array_rejected(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        t1 = _remove_target(nid, "grid_fixtures__constrained_source", "first")
        t2 = _remove_target(nid, "grid_fixtures__constrained_source", "second")
        deletes = {"on_missing": "error", "on_tombstoned": "ignore", "edges": [], "nodes": [t1, t2]}
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "duplicate_removal_target" for e in result.errors)

    def test_duplicate_target_across_deletes_and_purges_rejected(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "delete")],
        }
        purges = {
            "on_missing": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "purge")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes, purges=purges)]))
        assert not result.success
        assert any(e.code == "duplicate_removal_target" for e in result.errors)

    def test_entity_id_in_upsert_and_removal_rejected(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        upsert = _character_node(nid)
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "I changed my mind")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, nodes=[upsert], deletes=deletes)]))
        assert not result.success
        assert any(e.code == "entity_id_in_upsert_and_removal" for e in result.errors)

    def test_edge_target_in_nodes_list_rejected(self):
        bid = _batch_entity_id()
        eid = _edge_entity_id()
        # Edge entity in the 'nodes' sub-array — static type sanity catches it.
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(eid, "edge", "wrong list")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "removal_entity_type_mismatch" for e in result.errors)

    def test_node_entity_type_in_edges_list_rejected(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [_remove_target(nid, "grid_fixtures__constrained_source", "wrong list")],
            "nodes": [],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "removal_entity_type_mismatch" for e in result.errors)


@pytest.mark.spec("req-grid-import-grift-removals-1")
@pytest.mark.django_db
class TestGriftRemovalExecution:
    """Transaction-scoped checks + actual delete/purge execution."""

    def _seed_one_character(self, *, name: str = "Frodo") -> str:
        """Create one character via a first grift_import; return its entity_id."""
        bid = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid, name=name)
        result = grift_import(_minimal_doc([_batch_container(bid, nodes=[char])]))
        assert result.success
        return nid

    def test_delete_existing_node_via_second_grift_import(self):
        nid = self._seed_one_character()
        assert Entity.objects.filter(pk=uuid.UUID(nid)).exists()

        bid = _batch_entity_id()
        deletes = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "retired")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert result.success, result.errors
        assert result.counts.nodes_deleted == 1
        # Tombstoned — Entity row still exists with deleted_at set.
        assert Entity.objects.filter(pk=uuid.UUID(nid), deleted_at__isnull=False).exists()
        # Typed-model live manager (LiveManager) filters it out.
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        assert not ConstrainedSource.objects.filter(entity_id=uuid.UUID(nid)).exists()

    def test_bootloader_cannot_tombstone_via_import(self):
        """Boot cannot tombstone through the grid.import_grift cover: the bootloader
        bundle excludes grid.delete, and the importer authorizes grid.delete
        explicitly for a removal batch — so a removal import run as tap_bootloader
        fails closed (doc-auth-per-app-standards "split cover semantics", decision #3).

        The denial surfaces as an `execution_failed` issue naming grid.delete (the
        importer's broad except records it); the key invariant is that the target is
        never tombstoned. A grid.delete message — not an "unguarded" one — proves the
        importer's explicit authorize fired, not just the write_batch backstop.
        """
        from tap_auth.actors import get_builtin_actor

        nid = self._seed_one_character()
        bid = _batch_entity_id()
        deletes = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "retired")],
        }
        doc = _minimal_doc([_container_with_removals(bid, deletes=deletes)])

        bootloader = get_builtin_actor("tap_bootloader")
        result = grift_import(doc, actor=bootloader)

        assert not result.success
        assert any(
            e.code == "execution_failed" and "grid.delete" in str(e.message) for e in result.errors
        ), result.errors
        # Fails closed: the target is still live (never tombstoned).
        assert Entity.objects.filter(pk=uuid.UUID(nid), deleted_at__isnull=True).exists()

    def test_sweep_tombstone_requires_grid_delete(self):
        """The force-reimport sweep tombstone authorizes grid.delete explicitly (symmetric with
        the imperative-removal path), so an actor lacking it gets a clean CapabilityDenied — not an
        UnguardedOperation — and nothing is tombstoned."""
        from tap_auth.actors import get_builtin_actor
        from tap_auth.errors import CapabilityDenied
        from tap_grid.caller_context import CallerContext
        from tap_grid.grift.importer import _apply_sweep_tombstone

        nid = self._seed_one_character()
        bootloader = get_builtin_actor("tap_bootloader")
        with pytest.raises(CapabilityDenied):
            _apply_sweep_tombstone([(nid, "grid_fixtures__constrained_source")], CallerContext(user=bootloader))
        assert Entity.objects.filter(pk=uuid.UUID(nid), deleted_at__isnull=True).exists()

    def test_delete_missing_target_on_missing_error_fails(self):
        bid = _batch_entity_id()
        missing_id = _node_entity_id()
        deletes = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(missing_id, "grid_fixtures__constrained_source", "delete ghost")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "removal_target_missing" for e in result.errors)

    def test_delete_missing_target_on_missing_ignore_skips(self):
        bid = _batch_entity_id()
        missing_id = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(missing_id, "grid_fixtures__constrained_source", "ok if gone")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert result.success, result.errors
        assert result.counts.nodes_deleted == 0
        assert result.counts.removals_skipped == 1

    def test_delete_already_tombstoned_on_tombstoned_ignore_skips(self):
        nid = self._seed_one_character()
        # First delete: tombstones it.
        bid1 = _batch_entity_id()
        deletes1 = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "first tombstone")],
        }
        r1 = grift_import(_minimal_doc([_container_with_removals(bid1, deletes=deletes1)]))
        assert r1.success
        # Second delete: target already tombstoned; on_tombstoned=ignore → skip.
        bid2 = _batch_entity_id()
        deletes2 = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "second pass")],
        }
        r2 = grift_import(_minimal_doc([_container_with_removals(bid2, deletes=deletes2)]))
        assert r2.success, r2.errors
        assert r2.counts.nodes_deleted == 0
        assert r2.counts.removals_skipped == 1

    def test_purge_existing_node_via_grift_import(self, settings):
        settings.DEBUG = True
        nid = self._seed_one_character()
        bid = _batch_entity_id()
        purges = {
            "on_missing": "error",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "hard remove for dev reset")],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, purges=purges)]))
        assert result.success, result.errors
        assert result.counts.nodes_purged == 1
        # Hard-deleted — gone entirely.
        assert not Entity.objects.filter(pk=uuid.UUID(nid)).exists()

    def test_batch_rolls_back_atomically_on_removal_failure(self):
        """If one removal fails, every upsert + earlier removal in this batch
        also rolls back."""
        nid_alive = self._seed_one_character(name="Sam")
        nid_ghost = _node_entity_id()  # doesn't exist

        bid = _batch_entity_id()
        new_char_id = _node_entity_id()
        upsert = _character_node(new_char_id, name="Pippin")
        deletes = {
            "on_missing": "error",  # ghost triggers failure
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [
                _remove_target(nid_alive, "grid_fixtures__constrained_source", "would tombstone"),
                _remove_target(nid_ghost, "grid_fixtures__constrained_source", "ghost"),
            ],
        }
        result = grift_import(_minimal_doc([_container_with_removals(bid, nodes=[upsert], deletes=deletes)]))
        assert not result.success, [(e.code, e.message) for e in result.errors]
        assert any(e.code == "removal_target_missing" for e in result.errors), [
            (e.code, e.message) for e in result.errors
        ]
        # Atomicity: Pippin (the upsert) should NOT have been created.
        assert not Entity.objects.filter(pk=uuid.UUID(new_char_id)).exists()
        # Sam should still be alive (not tombstoned).
        assert Entity.objects.filter(pk=uuid.UUID(nid_alive), deleted_at__isnull=True).exists()

    def test_cross_section_dupe_across_two_batches_rejected(self):
        """An entity_id appearing in batch A's deletes and batch B's purges
        within the same document triggers duplicate_removal_target."""
        bid_a = _batch_entity_id()
        bid_b = _batch_entity_id()
        nid = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "batch A")],
        }
        purges = {
            "on_missing": "ignore",
            "edges": [],
            "nodes": [_remove_target(nid, "grid_fixtures__constrained_source", "batch B")],
        }
        result = grift_import(
            _minimal_doc(
                [
                    _container_with_removals(bid_a, deletes=deletes),
                    _container_with_removals(bid_b, purges=purges),
                ]
            )
        )
        assert not result.success
        assert any(e.code == "duplicate_removal_target" for e in result.errors)


@pytest.mark.spec("req-grid-import-grift-removals-2")
@pytest.mark.django_db
class TestGriftSkippedBatchHadRemovalsWarning:
    """req-grid-import-grift-skipped-batch-removals — loud warning when a
    skipped batch had non-empty removal sections."""

    def test_skipped_batch_with_deletes_emits_warning(self):
        # First, ingest the batch.
        bid = _batch_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [_remove_target(_node_entity_id(), "grid_fixtures__constrained_source", "first run target")],
        }
        doc = _minimal_doc([_container_with_removals(bid, deletes=deletes)])
        r1 = grift_import(doc)
        assert r1.success
        # Re-run: the batch is now skipped, and removal sections did NOT fire.
        r2 = grift_import(doc)
        assert r2.success  # still a clean import (skip is not an error)
        assert any(w.code == "skipped_batch_had_removals" for w in r2.warnings)
        # Recipe is embedded in the warning message.
        recipe_warning = next(w for w in r2.warnings if w.code == "skipped_batch_had_removals")
        assert f"--force-batches={bid}" in recipe_warning.message

    def test_skipped_batch_without_removals_does_not_warn(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        doc = _minimal_doc([_batch_container(bid, nodes=[_character_node(nid)])])
        r1 = grift_import(doc)
        assert r1.success
        r2 = grift_import(doc)
        assert r2.success
        assert not any(w.code == "skipped_batch_had_removals" for w in r2.warnings)


# ---------------------------------------------------------------------------
# Optimistic concurrency via GRIFT (req-grift-concurrency-version,
# req-grid-import-grift-occ)
# ---------------------------------------------------------------------------


def _entity_version(entity_id: str) -> int:
    return Entity.objects.values_list("version", flat=True).get(pk=uuid.UUID(entity_id))


@pytest.mark.django_db
class TestGriftEnvelopeOCC:
    """Upsert envelopes carry an optional entity_expected_version.

    Locks req-grid-import-grift-occ-1 / -2 / -3 / -5 for the envelope path
    and req-grift-concurrency-version-7 (declared expectation on missing).
    """

    def test_envelope_with_matching_version_succeeds(self):
        # Seed character.
        bid1 = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid, name="Frodo", description="ringbearer")
        result1 = grift_import(_minimal_doc([_batch_container(bid1, nodes=[char])]))
        assert result1.success
        v_after_create = _entity_version(nid)

        # Re-import with envelope declaring matching expected version.
        bid2 = _batch_entity_id()
        char_v2 = _character_node(nid, name="Frodo", description="updated")
        char_v2["entity"]["entity_expected_version"] = v_after_create
        result2 = grift_import(_minimal_doc([_batch_container(bid2, nodes=[char_v2])]))
        assert result2.success, [(e.code, e.message) for e in result2.errors]
        # Single-bump invariant.
        assert _entity_version(nid) == v_after_create + 1

    def test_envelope_with_mismatched_version_emits_entity_version_conflict(self):
        bid1 = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid)
        grift_import(_minimal_doc([_batch_container(bid1, nodes=[char])]))
        v = _entity_version(nid)

        bid2 = _batch_entity_id()
        char_v2 = _character_node(nid, name="Frodo", description="newer")
        char_v2["entity"]["entity_expected_version"] = v + 99  # wrong
        result2 = grift_import(_minimal_doc([_batch_container(bid2, nodes=[char_v2])]))
        assert not result2.success
        conflicts = [e for e in result2.errors if e.code == "entity_version_conflict"]
        assert len(conflicts) == 1
        assert conflicts[0].entity_expected_version == v + 99
        assert conflicts[0].actual_entity_version == v
        # Atomic rollback — no bump.
        assert _entity_version(nid) == v

    def test_envelope_declared_on_missing_entity_emits_conflict_with_null_actual(self):
        """req-grift-concurrency-version-7: a declared expectation on a
        nonexistent entity is a conflict (not a silent route to create)."""
        bid = _batch_entity_id()
        nid = _node_entity_id()  # never created
        char = _character_node(nid)
        char["entity"]["entity_expected_version"] = 1
        result = grift_import(_minimal_doc([_batch_container(bid, nodes=[char])]))
        assert not result.success
        conflicts = [e for e in result.errors if e.code == "entity_version_conflict"]
        assert len(conflicts) == 1
        assert conflicts[0].entity_expected_version == 1
        assert conflicts[0].actual_entity_version is None

    def test_envelope_without_expected_version_is_unaffected(self):
        # Existing behavior: omitting entity_expected_version means no check.
        bid1 = _batch_entity_id()
        nid = _node_entity_id()
        char = _character_node(nid)
        grift_import(_minimal_doc([_batch_container(bid1, nodes=[char])]))

        bid2 = _batch_entity_id()
        char_v2 = _character_node(nid, name="Frodo", description="updated")
        # No entity_expected_version on envelope.
        result2 = grift_import(_minimal_doc([_batch_container(bid2, nodes=[char_v2])]))
        assert result2.success


@pytest.mark.django_db
class TestGriftRemovalOCC:
    """Removal targets carry an optional entity_expected_version."""

    def _seed(self, name: str = "Frodo") -> str:
        bid = _batch_entity_id()
        nid = _node_entity_id()
        result = grift_import(_minimal_doc([_batch_container(bid, nodes=[_character_node(nid, name=name)])]))
        assert result.success
        return nid

    def test_delete_with_matching_version_succeeds(self):
        nid = self._seed()
        v = _entity_version(nid)
        bid = _batch_entity_id()
        deletes = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [
                {
                    "entity_id": nid,
                    "entity_type": "grid_fixtures__constrained_source",
                    "reason": "occ-test",
                    "entity_expected_version": v,
                }
            ],
        }
        from tap_grid.tests.test_grift import _container_with_removals

        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert result.success, [(e.code, e.message) for e in result.errors]
        assert result.counts.nodes_deleted == 1

    def test_delete_with_mismatched_version_emits_conflict(self):
        nid = self._seed()
        v = _entity_version(nid)
        bid = _batch_entity_id()
        deletes = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [
                {
                    "entity_id": nid,
                    "entity_type": "grid_fixtures__constrained_source",
                    "reason": "stale",
                    "entity_expected_version": v + 1,
                }
            ],
        }
        from tap_grid.tests.test_grift import _container_with_removals

        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        conflicts = [e for e in result.errors if e.code == "entity_version_conflict"]
        assert len(conflicts) == 1
        assert conflicts[0].entity_expected_version == v + 1
        assert conflicts[0].actual_entity_version == v
        # Rolled back.
        assert _entity_version(nid) == v


@pytest.mark.django_db
class TestGriftRemovalTargetSchemaOCC:
    """Schema validation of entity_expected_version on removal targets."""

    def test_zero_expected_version_rejected(self):
        # Entity.version starts at 1; expected_version=0 is invalid.
        bid = _batch_entity_id()
        nid = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [
                {
                    "entity_id": nid,
                    "entity_type": "grid_fixtures__constrained_source",
                    "reason": "test",
                    "entity_expected_version": 0,
                }
            ],
        }
        from tap_grid.tests.test_grift import _container_with_removals

        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)

    def test_string_expected_version_rejected(self):
        bid = _batch_entity_id()
        nid = _node_entity_id()
        deletes = {
            "on_missing": "ignore",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [
                {
                    "entity_id": nid,
                    "entity_type": "grid_fixtures__constrained_source",
                    "reason": "test",
                    "entity_expected_version": "1",  # wrong type
                }
            ],
        }
        from tap_grid.tests.test_grift import _container_with_removals

        result = grift_import(_minimal_doc([_container_with_removals(bid, deletes=deletes)]))
        assert not result.success
        assert any(e.code == "schema_validation_failed" for e in result.errors)


# ---------------------------------------------------------------------------
# Dry-run / pre-flight document validation (validate_grift_document)
#
# Regression: import_plugin_grift --dry-run was born broken (commit d76ad85)
# — it imported a never-defined GRIFT_DOCUMENT_SCHEMA, so every dry-run threw
# ImportError. No caller, no test, so it rotted silently. These guard the
# public validation surface the command now uses.
# ---------------------------------------------------------------------------


def test_validate_grift_document_accepts_minimal_valid_doc():
    from tap_grid.grift import validate_grift_document

    assert validate_grift_document(_minimal_doc()) == []


def test_validate_grift_document_flags_structural_error():
    from tap_grid.grift import validate_grift_document

    # `deletes` must be an object, not a list — the exact shape that slipped
    # past the (broken) dry-run and was only caught on real import.
    issues = validate_grift_document(_minimal_doc([{"deletes": []}]))
    assert issues, "expected a schema validation issue for a malformed batch"
    assert all(i.phase == "schema" for i in issues)


# ---------------------------------------------------------------------------
# Importer null semantics mirror the service write path
# (req-grid-service-write-observation-2). Regression for the 2026-08-10 field
# collector rejection: the importer validated RAW payloads, so an explicit null
# on a known non-null field (a collector's graceful-missing None — e.g. an AWS
# response field the API omitted) was rejected here while the service layer,
# which runs _prepare_null_payload before validating, would have accepted the
# very same payload at write time.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImporterNullSemantics:
    def test_null_on_known_optional_non_null_field_is_dropped_and_imports(self):
        nid = _node_entity_id()
        node = _character_node(nid, name="Samwise")
        # The live shape: an optional boolean the source omitted (AWS leaves
        # RotationEnabled off never-rotated secrets), projected as explicit None.
        node["node"]["is_open"] = None
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert result.success, [f"{i.code}: {i.message}" for i in result.errors]
        assert Entity.objects.filter(pk=uuid.UUID(nid)).exists()

    def test_null_on_required_field_still_rejected_as_missing(self):
        # Dropping the null makes the field ABSENT — a required field then fails
        # required-validation, exactly as the service write path would fail it.
        node = _character_node(_node_entity_id())
        node["node"]["description"] = None
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert not result.success
        assert any("required" in i.message for i in result.errors)

    def test_null_on_unknown_field_still_rejected(self):
        node = _character_node(_node_entity_id())
        node["node"]["stranger"] = None  # unknown key: additionalProperties must still fire
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert not result.success
        assert any(i.code == "payload_validation_failed" for i in result.errors)
