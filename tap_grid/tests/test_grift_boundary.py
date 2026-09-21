"""The parse boundary, and one spelling per id (Issue# 630 - tap; parent Issue# 140 - tap;
George's six rulings of 2026-09-18 on the bad-batch review).

Every case is a document handed to ``grift_import`` and the refusal it must produce: the
code, the phase, the path, and that nothing was written — the entity, batch and batch-event
counts are unchanged and the batch row does not exist. A refusal that merely *looks* right
is not enough; each row pins all four. Case ids borrow JSONTestSuite's ``n_``/``i_`` names
where a case corresponds (Nicolas Seriot, MIT licence, github.com/nst/JSONTestSuite); the
inputs are inline, never fixture files. The recursion cases assert the class of outcome — a
structured refusal, never a raise — not a depth, which is the interpreter's to choose.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import Batch, BatchEvent, Edge, Entity
from tap_grid.tests.test_grift import (
    _batch_container,
    _batch_entity_id,
    _character_node,
    _minimal_doc,
    _node_entity_id,
    _wields_edge,
)

pytestmark = pytest.mark.django_db

VALID = json.dumps(_minimal_doc())
SOURCE_TYPE = "grid_fixtures__constrained_source"


def _snapshot() -> tuple[int, int, int]:
    return Entity.objects.count(), Batch.all_objects.count(), BatchEvent.objects.count()


def _refused(result: Any, code: str, phase: str, path: str, before: tuple[int, int, int]) -> None:
    """One issue, named exactly, and the grid is as it was."""
    assert not result.success
    assert [(e.code, e.phase, e.path) for e in result.errors] == [(code, phase, path)], result.errors
    assert result.imported_batches == [] and result.skipped_batches == []
    assert result.counts.batches_imported == 0 and result.counts.nodes_imported == 0
    assert _snapshot() == before, "the refusal wrote something"


def _doc_text(**overrides: Any) -> str:
    return json.dumps({**_minimal_doc(), **overrides})


# ---------------------------------------------------------------------------
# Rulings 1, 2 and 4 — the str | bytes arm: every decoder failure is a parse-phase refusal
# ---------------------------------------------------------------------------

PARSE_REFUSALS: list[tuple[str, str | bytes, str]] = [
    ("n_structure_no_data", "", "invalid_json"),
    ("whitespace_only", " \n\t ", "invalid_json"),
    ("n_structure_object_unclosed", '{"metadata": {"grift_version": "0"', "invalid_json"),
    (
        "n_object_trailing_comma",
        '{"metadata": {"grift_version": "0",}, "_reserved": {}, "batches": []}',
        "invalid_json",
    ),
    ("n_structure_double_object (two documents)", VALID + " " + VALID, "invalid_json"),
    ("n_structure_trailing_#", VALID + " # a comment", "invalid_json"),
    (
        "n_string_unescaped_ctrl_char",
        '{"metadata": {"grift_version": "0\x01"}, "_reserved": {}, "batches": []}',
        "invalid_json",
    ),
    ("n_structure_UTF8_BOM_no_data", "\ufeff", "invalid_json"),
    ("text_with_BOM (a BOM is tolerated on bytes, never on text)", "\ufeff" + VALID, "invalid_json"),
    (
        "n_string_invalid_utf-8 (bytes)",
        b'{"metadata": {"grift_version": "\xff"}, "_reserved": {}, "batches": []}',
        "invalid_json",
    ),
    (
        "truncated_multibyte (bytes)",
        b'{"metadata": {"grift_version": "\xe2\x82"}, "_reserved": {}, "batches": []}',
        "invalid_json",
    ),
    ("i_number_huge_int (5000 digits; the int-string digit limit)", "[" + "9" * 5000 + "]", "invalid_json"),
    ("n_object_repeated_key (top level)", VALID[:-1] + ', "batches": []}', "duplicate_json_key"),
    (
        "repeated_key_nested",
        '{"metadata": {"grift_version": "0", "grift_version": "1"}, "_reserved": {}, "batches": []}',
        "duplicate_json_key",
    ),
    ("repeated_key (bytes)", (VALID[:-1] + ', "batches": []}').encode(), "duplicate_json_key"),
    ("n_number_NaN", _doc_text(_reserved={"x": 1}).replace('"x": 1', '"x": NaN'), "non_finite_number"),
    ("n_number_infinity", _doc_text(_reserved={"x": 1}).replace('"x": 1', '"x": Infinity'), "non_finite_number"),
    ("n_number_minus_infinity", _doc_text(_reserved={"x": 1}).replace('"x": 1', '"x": -Infinity'), "non_finite_number"),
    (
        "i_number_real_pos_overflow (1e400 overflows to infinity)",
        _doc_text(_reserved={"x": 1}).replace('"x": 1', '"x": 1e400'),
        "non_finite_number",
    ),
]


class TestParseBoundary:
    @pytest.mark.parametrize("raw,code", [pytest.param(raw, code, id=label) for label, raw, code in PARSE_REFUSALS])
    def test_every_decoder_failure_is_a_structured_refusal(self, raw: str | bytes, code: str) -> None:
        before = _snapshot()
        _refused(grift_import(raw), code, "parse", "$", before)

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("[" * 100_000, id="n_structure_100000_opening_arrays"),
            pytest.param("[" * 100_000 + "]" * 100_000, id="closed_100000_deep_arrays"),
        ],
    )
    def test_deep_nesting_is_refused_never_raised(self, raw: str) -> None:
        """The depth at which the decoder gives up is the interpreter's and the host's to choose
        (the C-stack check since 3.12): in the session container both inputs raise
        ``RecursionError`` inside the decoder and become ``invalid_json``; on a CI runner with a
        deeper stack the closed one parses and is refused as a non-object root. The invariant is
        the class of outcome — one structured refusal at ``$``, nothing written, never a raise —
        so that is what is pinned, not a depth."""
        before = _snapshot()
        result = grift_import(raw)
        assert not result.success
        assert len(result.errors) == 1 and result.errors[0].path == "$", result.errors
        assert (result.errors[0].code, result.errors[0].phase) in {
            ("invalid_json", "parse"),
            ("schema_validation_failed", "schema"),
        }, result.errors
        assert result.imported_batches == [] and result.skipped_batches == []
        assert _snapshot() == before

    def test_the_refusal_names_what_the_decoder_could_not_read(self) -> None:
        """The message carries the exception class and the decoder's own position, so a producer can find the byte."""
        result = grift_import(b'{"metadata": {"grift_version": "\xff"}, "_reserved": {}, "batches": []}')
        assert "UnicodeDecodeError" in result.errors[0].message
        result = grift_import(VALID[:-1] + ', "batches": []}')
        assert "'batches'" in result.errors[0].message

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param(("\ufeff" + VALID).encode("utf-8"), id="utf-8 with BOM (bytes)"),
            pytest.param(VALID.encode("utf-16"), id="utf-16 (bytes, auto-detected)"),
            pytest.param(VALID.encode("utf-32"), id="utf-32 (bytes, auto-detected)"),
            pytest.param(
                _doc_text(_reserved={"x": 1.5, "y": -0.0, "z": 1e300, "i": 0, "n": -0}),
                id="ordinary numbers still parse",
            ),
            pytest.param(VALID, id="text"),
        ],
    )
    def test_positive_controls_the_decoder_still_accepts(self, raw: str | bytes) -> None:
        """Ruling 4: bytes decode as ``json.loads`` auto-detects them; the hooks refuse nothing legal."""
        result = grift_import(raw)
        assert result.success, result.errors
        assert result.grift_version == "0"


ROOT_SHAPES: list[tuple[str, str, str]] = [
    ("null_root", "null", "$"),
    ("array_root", "[]", "$"),
    ("string_root", '"grift"', "$"),
    ("number_root", "7", "$"),
    ("true_root", "true", "$"),
    ("batches_as_object", _doc_text(batches={}), "$.batches"),
]


class TestRootShape:
    @pytest.mark.parametrize("raw,path", [pytest.param(raw, path, id=label) for label, raw, path in ROOT_SHAPES])
    def test_a_wrong_root_is_a_schema_refusal_at_its_path(self, raw: str, path: str) -> None:
        before = _snapshot()
        _refused(grift_import(raw), "schema_validation_failed", "schema", path, before)


# ---------------------------------------------------------------------------
# Ruling 3 — the document version is pinned to "0"
# ---------------------------------------------------------------------------


class TestGriftVersionPinned:
    @pytest.mark.parametrize("version", ["1", "banana", "00", " 0", "0.0", "v0"])
    def test_an_unknown_version_refuses_the_file(self, version: str) -> None:
        before = _snapshot()
        doc = _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_character_node(_node_entity_id())])])
        doc["metadata"]["grift_version"] = version
        result = grift_import(doc)
        _refused(result, "unsupported_grift_version", "preflight", "$.metadata.grift_version", before)
        assert result.grift_version == version, "the result still reports what the file declared"
        assert "'0'" in result.errors[0].message

    def test_a_non_string_version_is_the_schema_s_refusal(self) -> None:
        before = _snapshot()
        doc = _minimal_doc()
        doc["metadata"]["grift_version"] = 0
        _refused(grift_import(doc), "schema_validation_failed", "schema", "$.metadata.grift_version", before)

    def test_version_0_imports(self) -> None:
        result = grift_import(
            _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_character_node(_node_entity_id())])])
        )
        assert result.success, result.errors
        assert result.counts.nodes_imported == 1


# ---------------------------------------------------------------------------
# One UUID has one spelling
# ---------------------------------------------------------------------------

SPELLINGS: list[tuple[str, Callable[[str], str]]] = [
    ("upper-case", str.upper),
    ("braced", lambda s: "{" + s + "}"),
    ("urn:uuid", lambda s: "urn:uuid:" + s),
    ("braced upper-case", lambda s: "{" + s.upper() + "}"),
]


def _removal_target(entity_id: str) -> dict[str, Any]:
    return {"entity_id": entity_id, "entity_type": SOURCE_TYPE, "reason": "one id, two spellings"}


def _deletes(*targets: dict[str, Any]) -> dict[str, Any]:
    return {"on_missing": "error", "on_tombstoned": "error", "edges": [], "nodes": list(targets)}


class TestOneSpellingPerId:
    @pytest.mark.parametrize("spell", [pytest.param(fn, id=label) for label, fn in SPELLINGS])
    def test_two_spellings_of_one_id_collide_at_preflight(self, spell: Callable[[str], str]) -> None:
        """Before the fix this reached execution and died on the primary key (observed: a
        duplicate-pkey ``execution_failed`` at nodes[1]); now the file is refused before any write."""
        before = _snapshot()
        eid = _node_entity_id()
        bid = _batch_entity_id()
        doc = _minimal_doc(
            [_batch_container(bid, nodes=[_character_node(eid), _character_node(spell(eid), name="Sam")])]
        )
        result = grift_import(doc)
        _refused(result, "duplicate_entity_id", "preflight", "$.batches[0].nodes[1].entity.entity_id", before)
        assert result.errors[0].entity_id == eid, "the issue names the canonical spelling"
        assert not Batch.all_objects.filter(entity_id=bid).exists()

    @pytest.mark.parametrize(
        "spell_upsert,spell_removal",
        [
            pytest.param(str, str.upper, id="upsert canonical, removal upper-case"),
            pytest.param(str.upper, str, id="upsert upper-case, removal canonical"),
            pytest.param(lambda s: "{" + s + "}", lambda s: "urn:uuid:" + s, id="upsert braced, removal urn"),
        ],
    )
    def test_an_upsert_and_a_removal_target_collide_across_spellings(
        self, spell_upsert: Callable[[str], str], spell_removal: Callable[[str], str]
    ) -> None:
        before = _snapshot()
        eid = _node_entity_id()
        container = _batch_container(_batch_entity_id(), nodes=[_character_node(spell_upsert(eid))])
        container["deletes"] = _deletes(_removal_target(spell_removal(eid)))
        result = grift_import(_minimal_doc([container]))
        _refused(
            result, "entity_id_in_upsert_and_removal", "preflight", "$.batches[0].deletes.nodes[0].entity_id", before
        )
        assert result.errors[0].entity_id == eid

    def test_an_endpoint_in_another_spelling_resolves_to_the_in_file_node(self) -> None:
        """Endpoint resolution compares canonical ids: a differently spelled endpoint is not dangling."""
        a, b, e = _node_entity_id(), _node_entity_id(), _node_entity_id()
        doc = _minimal_doc(
            [
                _batch_container(
                    _batch_entity_id(),
                    nodes=[_character_node(a), _character_node(b, name="Sam")],
                    edges=[_wields_edge(e, "urn:uuid:" + a, b.upper())],
                )
            ]
        )
        # SCHEMA_LINK needs a dual_endpoint target; SYMMETRIC_LINK joins two constrained sources.
        doc["batches"][0]["edges"][0]["edge"]["edge_type"] = "SYMMETRIC_LINK__grid_fixtures"
        result = grift_import(doc)
        assert result.success, result.errors
        assert result.counts.edges_imported == 1 and result.counts.edges_skipped == 0
        edge = Edge.objects.get(entity_id=uuid.UUID(e))
        assert (edge.from_entity_id, edge.to_entity_id) == (uuid.UUID(a), uuid.UUID(b))

    def test_the_result_and_skip_if_exists_carry_the_canonical_spelling(self) -> None:
        bid, eid = _batch_entity_id(), _node_entity_id()
        first = grift_import(_minimal_doc([_batch_container(bid.upper(), nodes=[_character_node("{" + eid + "}")])]))
        assert first.success, first.errors
        assert first.imported_batches[0].batch_entity_id == bid
        assert Entity.objects.filter(pk=uuid.UUID(eid)).exists()
        after_first = _snapshot()
        second = grift_import(_minimal_doc([_batch_container(bid, nodes=[_character_node(eid, name="Renamed")])]))
        assert second.success and second.imported_batches == []
        assert [s.batch_entity_id for s in second.skipped_batches] == [bid]
        assert _snapshot() == after_first
        assert Entity.objects.get(pk=uuid.UUID(eid)).name == "Frodo", "the skipped batch replaced nothing"

    def test_a_removal_target_in_another_spelling_finds_the_row(self) -> None:
        """Positive control: an existing row is found by any spelling of its id."""
        eid = _node_entity_id()
        assert grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[_character_node(eid)])])).success
        container = _batch_container(_batch_entity_id())
        container["deletes"] = _deletes(_removal_target(eid.upper()))
        result = grift_import(_minimal_doc([container]))
        assert result.success, result.errors
        assert result.counts.nodes_deleted == 1
        assert Entity.objects.get(pk=uuid.UUID(eid)).deleted_at is not None


# ---------------------------------------------------------------------------
# Ruling 5 — a NUL or an unpaired surrogate is not scanned for; the database refuses it at
# execution, the batch rolls back, and the issue names the path and the operation
# ---------------------------------------------------------------------------


def _both_names(node: dict[str, Any], name: str) -> None:
    node["entity"]["name"] = name
    node["node"]["name"] = name


UNSTORABLE: list[tuple[str, Callable[[dict[str, Any]], None]]] = [
    ("NUL in the node name", lambda c: _both_names(c["nodes"][0], "Fro\x00do")),
    ("NUL in a text field", lambda c: c["nodes"][0]["node"].__setitem__("description", "a\x00b")),
    ("NUL in a dimension value (jsonb)", lambda c: c["nodes"][0]["entity"].__setitem__("dimensions", {"k": "v\x00"})),
    ("unpaired surrogate in the node name", lambda c: _both_names(c["nodes"][0], "Fro\ud800do")),
    (
        "unpaired surrogate in a dimension value",
        lambda c: c["nodes"][0]["entity"].__setitem__("dimensions", {"k": "\udcff"}),
    ),
]


class TestUnstorableStringsFailAtExecution:
    @pytest.mark.parametrize("mutate", [pytest.param(fn, id=label) for label, fn in UNSTORABLE])
    def test_a_node_value_the_database_refuses_fails_the_batch_at_the_node_path(
        self, mutate: Callable[[dict[str, Any]], None]
    ) -> None:
        before = _snapshot()
        bid = _batch_entity_id()
        container = _batch_container(bid, nodes=[_character_node(_node_entity_id())])
        mutate(container)
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert [(e.code, e.phase, e.path, e.operation) for e in result.errors] == [
            ("execution_failed", "execution", "$.batches[0].nodes[0]", "create_node")
        ], result.errors
        assert "$.batches[0].nodes[0]" in result.errors[0].message and "create_node" in result.errors[0].message
        assert result.errors[0].batch_entity_id == bid
        assert result.counts.batches_imported == 0
        assert result.imported_batches[0].nodes_imported == 0 and result.imported_batches[0].errors_count == 1
        assert _snapshot() == before, "the batch did not roll back cleanly"
        assert not Batch.all_objects.filter(entity_id=bid).exists(), "the batch row survived the rollback"

    def test_a_batch_node_value_the_database_refuses_names_the_batch_node_path(self) -> None:
        """The batch row is the importer's own write from document strings; it is attributed too."""
        before = _snapshot()
        bid = _batch_entity_id()
        container = _batch_container(bid, nodes=[_character_node(_node_entity_id())])
        container["batch_node"]["name"] = "b\x00"
        container["batch_entity"]["name"] = "b\x00"
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        assert [(e.code, e.phase, e.path, e.operation) for e in result.errors] == [
            ("execution_failed", "execution", "$.batches[0].batch_node", "create_batch")
        ], result.errors
        assert "$.batches[0].batch_node" in result.errors[0].message
        assert _snapshot() == before
        assert not Batch.all_objects.filter(entity_id=bid).exists()

    def test_the_text_arm_reaches_execution_too(self) -> None:
        """No preflight string scan (ruled): an escaped NUL parses and fails where the database says so."""
        before = _snapshot()
        bid = _batch_entity_id()
        container = _batch_container(bid, nodes=[_character_node(_node_entity_id())])
        container["nodes"][0]["node"]["description"] = "a\x00b"
        result = grift_import(json.dumps(_minimal_doc([container])))
        assert [(e.code, e.phase, e.path) for e in result.errors] == [
            ("execution_failed", "execution", "$.batches[0].nodes[0]")
        ]
        assert _snapshot() == before
        assert not Batch.all_objects.filter(entity_id=bid).exists()
