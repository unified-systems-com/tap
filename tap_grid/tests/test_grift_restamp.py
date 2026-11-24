"""Restating a format "0" GRIFT document at "1" (req-grift-header-versions rule 12, Issue# 1288 - tap).

``tap_grid.grift.restamp`` and ``manage.py restamp_grift``: the header is the only text that changes,
it says what a "0" document has always been read as (the spine and every type at version 1, rule 11),
and an import of the restated document leaves every record as the "0" document would have.
"""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import CommandError, call_command

from tap_grid import model_version
from tap_grid.grift import grift_import
from tap_grid.grift.restamp import RestampRefused, metadata_span, restamp_text
from tap_grid.grift.upgrade import installed_version, upgrade_document
from tap_grid.tests.test_entity_batch_pointers import _panel
from tap_grid.tests.test_grift import _batch_container, _minimal_doc
from tap_plugins.base import TapPluginConfig
from tap_web.models import Panel

FLEET = pytest.mark.spec("req-grift-header-versions-8")
REPO = Path(__file__).resolve().parents[2]
CORE_DOCUMENTS = [
    REPO / "tap_grid/data/dimensions.grift.json",
    REPO / "tap_grid/tests/data/test_dimensions.grift.json",
]


def _zero_document(*panels: str) -> tuple[str, dict[str, object]]:
    document = _minimal_doc([_batch_container(str(uuid.uuid4()), nodes=[_panel(p, str(uuid.uuid4())) for p in panels])])
    return json.dumps(document, indent=2), document


def _outside_header(text: str) -> tuple[str, str]:
    start, end = metadata_span(text)
    return text[:start], text[end:]


@FLEET
def test_only_the_header_changes_and_it_states_version_1_for_everything() -> None:
    text, _ = _zero_document("restamp-a", "restamp-b")
    result = restamp_text(text)
    assert result.changed
    assert _outside_header(result.text) == _outside_header(text)
    header = json.loads(result.text)["metadata"]
    assert header == {"grift_version": "1", "spine_version": 1, "type_versions": {"batch": 1, "panel": 1}}


@FLEET
@pytest.mark.parametrize("path", CORE_DOCUMENTS, ids=lambda p: p.name)
def test_a_committed_core_document_keeps_every_record_byte_for_byte(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    result = restamp_text(text)
    assert result.changed
    assert _outside_header(result.text) == _outside_header(text)
    assert json.loads(result.text)["batches"] == json.loads(text)["batches"]
    assert json.loads(result.text)["metadata"]["grift_version"] == "1"


@FLEET
@pytest.mark.django_db
def test_a_restamped_document_round_trips_through_the_importer_with_no_record_change() -> None:
    text, original = _zero_document("restamp-import")
    restated = json.loads(restamp_text(text).text)
    # The importer's upgrade carries each record from version 1 (spine 1 to 2, batch 1 to 2) and
    # changes none of them: every step on the way is the identity.
    outcome = upgrade_document(copy.deepcopy(restated))
    assert not outcome.refused, outcome.refusals
    assert outcome.document["batches"] == original["batches"]
    result = grift_import(restated)
    assert result.success, result.errors
    node = original["batches"][0]["nodes"][0]  # type: ignore[index]
    panel = Panel.objects.get(entity_id=node["entity"]["entity_id"])
    assert (panel.name, panel.slug, panel.view) == (node["node"]["name"], node["node"]["slug"], node["node"]["view"])


@FLEET
def test_a_type_nothing_registers_is_refused_by_name() -> None:
    _, document = _zero_document("restamp-unknown")
    document["batches"][0]["nodes"][0]["entity"]["entity_type"] = "nowhere__ghost"  # type: ignore[index]
    with pytest.raises(RestampRefused, match="nowhere__ghost"):
        restamp_text(json.dumps(document))


@FLEET
@pytest.mark.parametrize(
    ("first", "second"),
    [('{"grift_version": "0"}', '{"grift_version": "1"}'), ('{"grift_version": "1"}', '{"grift_version": "0"}')],
    ids=["0-then-1", "1-then-0"],
)
def test_a_repeated_top_level_metadata_is_refused(first: str, second: str) -> None:
    """json.loads keeps the last "metadata" and the rewrite edits the first: refuse, never guess (PR 1352 review)."""
    text, _ = _zero_document("restamp-repeated")
    body = text.rstrip().removesuffix("}")
    doubled = f'{{"metadata": {first},{body.lstrip().removeprefix("{")}, "metadata": {second}}}'
    with pytest.raises(RestampRefused, match=r"repeats the top-level key\(s\) metadata"):
        restamp_text(doubled)


@FLEET
def test_any_repeated_top_level_key_is_refused_by_name() -> None:
    text, document = _zero_document("restamp-repeated-batches")
    doubled = text.rstrip().removesuffix("}") + ', "batches": ' + json.dumps(document["batches"]) + "}"
    with pytest.raises(RestampRefused, match=r"repeats the top-level key\(s\) batches"):
        restamp_text(doubled)


# grid_fixtures' wildcard edges: no sources, no targets, no version, so they register no constraint.
WILDCARD_EDGES = ("PG_LINKS__grid_fixtures", "PG_NESTS__grid_fixtures", "PG_OPTIONAL__grid_fixtures")


def _wildcard_edge(edge_type: str, from_id: str, to_id: str) -> dict[str, object]:
    return {
        "entity": {"entity_id": str(uuid.uuid4()), "entity_type": "edge", "dimensions": {}},
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": edge_type, "properties": {}},
    }


@FLEET
def test_a_wildcard_manifest_edge_is_installed_and_restated_at_version_1() -> None:
    """A wildcard edge is installed although it registers no constraint (PR 1352 review): rule 11 reads it at 1."""
    a, b = _panel("restamp-wild-a", str(uuid.uuid4())), _panel("restamp-wild-b", str(uuid.uuid4()))
    ends = (a["entity"]["entity_id"], b["entity"]["entity_id"])
    edges = [_wildcard_edge(edge_type, *ends) for edge_type in WILDCARD_EDGES]
    text = json.dumps(_minimal_doc([_batch_container(str(uuid.uuid4()), nodes=[a, b], edges=edges)]), indent=2)
    result = restamp_text(text)
    assert result.changed
    assert result.header["type_versions"] == {"batch": 1, "panel": 1, **dict.fromkeys(WILDCARD_EDGES, 1)}
    assert _outside_header(result.text) == _outside_header(text)


@pytest.fixture
def restored_edge_declarations() -> Iterator[None]:
    declared, versions = set(model_version._edge_types), dict(model_version._edge_versions)
    try:
        yield
    finally:
        model_version._edge_types.clear()
        model_version._edge_types.update(declared)
        model_version._edge_versions.clear()
        model_version._edge_versions.update(versions)


def _manifest_edge(slug: str, version: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        slug=slug,
        sources=None,
        targets=None,
        property_schema=None,
        default_dimensions=None,
        identity=None,
        internal_only=False,
        event_time=None,
        version=version,
    )


@FLEET
def test_a_manifest_edge_with_no_endpoints_is_installed_at_its_declared_version(
    restored_edge_declarations: None,
) -> None:
    assert installed_version("RESTAMP_WILD_PLAIN") is None
    edges = [_manifest_edge("RESTAMP_WILD_PLAIN", None), _manifest_edge("RESTAMP_WILD_V2", 2)]
    TapPluginConfig._register_edges_from_manifest(SimpleNamespace(_manifest=SimpleNamespace(edges=edges)))  # type: ignore[arg-type]
    assert installed_version("RESTAMP_WILD_PLAIN") == 1
    assert installed_version("RESTAMP_WILD_V2") == 2
    # A "0" document is read at version 1 whatever the installed version (rule 11), so that is what
    # its restated header says; the import then carries the record up the declared links.
    a, b = _panel("restamp-wild-c", str(uuid.uuid4())), _panel("restamp-wild-d", str(uuid.uuid4()))
    ends = (a["entity"]["entity_id"], b["entity"]["entity_id"])
    edge = _wildcard_edge("RESTAMP_WILD_V2", *ends)
    result = restamp_text(json.dumps(_minimal_doc([_batch_container(str(uuid.uuid4()), nodes=[a, b], edges=[edge])])))
    assert result.header["type_versions"]["RESTAMP_WILD_V2"] == 1


@FLEET
def test_a_document_already_at_1_is_left_alone() -> None:
    text, _ = _zero_document("restamp-twice")
    once = restamp_text(text).text
    again = restamp_text(once)
    assert not again.changed and again.text == once and "already" in again.note


@FLEET
def test_the_command_restamps_a_directory_refuses_a_second_run_and_checks(tmp_path: Path) -> None:
    for name in ("one", "two"):
        (tmp_path / f"{name}.grift.json").write_text(_zero_document(f"restamp-{name}")[0], encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")  # not a *.grift.json: not read
    with pytest.raises(CommandError, match="still at"):
        call_command("restamp_grift", str(tmp_path), "--check")
    assert all('"0"' in p.read_text() for p in tmp_path.glob("*.grift.json"))  # --check wrote nothing
    call_command("restamp_grift", str(tmp_path))
    assert all(json.loads(p.read_text())["metadata"]["grift_version"] == "1" for p in tmp_path.glob("*.grift.json"))
    with pytest.raises(CommandError, match="refused"):
        call_command("restamp_grift", str(tmp_path))
    call_command("restamp_grift", str(tmp_path), "--check")  # all at "1": clean


def test_the_command_writes_to_a_new_path(tmp_path: Path) -> None:
    source, out = tmp_path / "in.grift.json", tmp_path / "out.grift.json"
    text = _zero_document("restamp-out")[0]
    source.write_text(text, encoding="utf-8")
    call_command("restamp_grift", str(source), "--out", str(out))
    assert source.read_text(encoding="utf-8") == text
    assert json.loads(out.read_text(encoding="utf-8"))["metadata"]["grift_version"] == "1"
