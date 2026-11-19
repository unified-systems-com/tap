"""The grid file: `tap_file`, `tap_directory`, their edges, and the holding helper.

`specs/spec-tap-file-store.md`: `req-tap-files-node`, `req-tap-files-directory`,
`req-tap-files-format-record` and `req-tap-files-hold`. A `layout` node stands in for a plugin's
format record: `FILE_CONTENTS` leaves its targets open, so any ordinary type will do.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from django.contrib.auth.models import Group

from tap_auth.errors import CapabilityDenied, UnguardedOperation
from tap_auth.models import User, UserKind
from tap_files import holding
from tap_files.holding import HoldError, hold_file, identifier_for
from tap_files.models import TapDirectory, TapFile, path_problem
from tap_files.services import open_file
from tap_files.store.local import LocalBackend
from tap_grid.caller_context import CallerContext
from tap_grid.models import Edge, Entity
from tap_grid.service_types import WriteOperation
from tap_grid.services import create_edge, create_node, write_batch

SPEC = pytest.mark.spec


@pytest.fixture
def store(tmp_path: Path, settings: Any) -> LocalBackend:
    root = tmp_path / "files"
    root.mkdir()
    backend = LocalBackend(root)
    backend.initialise()
    settings.TAP_FILES_ROOT = str(root)
    return backend


def _hold(path: str, data: bytes = b"bytes", **kw: Any) -> holding.HeldFile:
    return hold_file(path, io.BytesIO(data), **kw)


def _file(path: str) -> TapFile:
    return cast(TapFile, TapFile.objects.filter(path=path).select_related("entity").get())


def _edges(edge_type: str, **filters: Any) -> list[Edge]:
    return cast(list[Edge], list(Edge.objects.filter(edge_type=edge_type, **filters)))


def _internal(ops: list[WriteOperation]) -> Any:
    return write_batch(ops, _internal_only_bypass=True)


def _record(name: str) -> uuid.UUID:
    result = create_node("layout", {"name": name})
    assert result.success, result.errors
    return result.entity_id  # type: ignore[return-value]


def _attach(file_id: uuid.UUID, record_id: uuid.UUID, sha256: str) -> Edge:
    return create_edge(
        Entity.objects.get(pk=file_id), Entity.objects.get(pk=record_id), "FILE_CONTENTS", {"sha256": sha256}
    )


def _read(entity_id: uuid.UUID, version: int | None = None) -> bytes:
    opened = open_file(identifier_for(entity_id), version)
    try:
        return opened.stream.read()
    finally:
        opened.close()


# --------------------------------------------------------------------------- the grid file


@SPEC("req-tap-files-node-2")
def test_the_fields_are_declared() -> None:
    schema = TapFile.FIELD_CRUD_SCHEMA
    assert set(schema) == {"name", "path", "media_type", "size_bytes", "sha256", "file_version"}
    assert "null" in schema["media_type"]["type"]
    for field in ("name", "path", "size_bytes", "sha256", "file_version"):
        assert "null" not in schema[field]["type"], field
    assert set(TapFile.CREATE_REQUIRED) == {"name", "path", "size_bytes", "sha256", "file_version"}
    assert TapFile.NATURAL_KEY == ("path",) and TapDirectory.NATURAL_KEY == ("path",)


@pytest.mark.django_db
@SPEC("req-tap-files-node-3")
@pytest.mark.parametrize(
    ("field", "value"),
    [("sha256", "A" * 64), ("sha256", "a" * 63), ("size_bytes", -1), ("file_version", 0)],
)
def test_digest_size_and_version_shapes_are_refused(field: str, value: Any) -> None:
    payload = {"name": "a", "path": "/a", "size_bytes": 1, "sha256": "a" * 64, "file_version": 1, field: value}
    result = _internal([WriteOperation(verb="create_node", type_slug="tap_file", payload=payload)])
    assert not result.success
    assert not TapFile.objects.filter(path="/a").exists()


@pytest.mark.django_db
@SPEC("req-tap-files-node-4")
def test_found_again_by_path(store: LocalBackend) -> None:
    first = _hold("/docs/a.txt", b"one")
    again = _hold("/docs/a.txt", b"two")
    assert first.entity_id == again.entity_id and TapFile.objects.filter(path="/docs/a.txt").count() == 1
    other = _hold("/other/a.txt", b"one")
    assert other.entity_id != first.entity_id
    assert TapFile.objects.filter(name="a.txt").count() == 2


@pytest.mark.django_db
@SPEC("req-tap-files-node-5")
@pytest.mark.parametrize("path", ["a", "a/b", "/", "/a/", "//a", "/a//b", "/./a", "/a/../b", "/a\x00b", "/a\nb"])
def test_a_bad_path_is_refused(path: str) -> None:
    assert path_problem(path) is not None
    with pytest.raises(HoldError):
        hold_file(path, io.BytesIO(b"x"))


@pytest.mark.django_db
@SPEC("req-tap-files-node-5")
def test_a_node_with_a_bad_path_is_refused() -> None:
    payload = {"name": "b", "path": "/a/../b", "size_bytes": 1, "sha256": "a" * 64, "file_version": 1}
    assert not _internal([WriteOperation(verb="create_node", type_slug="tap_file", payload=payload)]).success
    mismatch = {**payload, "path": "/a/c"}
    assert not _internal([WriteOperation(verb="create_node", type_slug="tap_file", payload=mismatch)]).success
    assert not TapFile.objects.exists()


@pytest.mark.django_db
@SPEC("req-tap-files-node-6")
def test_no_body() -> None:
    fields = {f.name for f in TapFile._meta.get_fields()}
    assert not fields & {"content", "body", "data", "bytes", "text", "parsed"}
    payload = {"name": "a", "path": "/a", "size_bytes": 1, "sha256": "a" * 64, "file_version": 1, "content": "x"}
    assert not _internal([WriteOperation(verb="create_node", type_slug="tap_file", payload=payload)]).success
    assert not TapFile.objects.exists()


@pytest.mark.django_db
@SPEC("req-tap-files-node-7")
def test_only_tap_files_writes_a_file(store: LocalBackend) -> None:
    payload = {"name": "a", "path": "/a", "size_bytes": 1, "sha256": "a" * 64, "file_version": 1}
    assert not create_node("tap_file", payload).success
    held = _hold("/b.txt", b"held")
    before = _file("/b.txt").entity.version
    for op in (
        WriteOperation(verb="patch_node", target=held.entity_id, payload={"media_type": "text/plain"}),
        WriteOperation(verb="replace_node", target=held.entity_id, payload=payload),
        WriteOperation(verb="delete_node", target=held.entity_id),
    ):
        assert not write_batch([op]).success, op.verb
    assert _file("/b.txt").entity.version == before and _file("/b.txt").media_type is None
    from tap_grid.grift import grift_import
    from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

    node = {
        "entity": {"entity_id": str(uuid.uuid4()), "entity_type": "tap_file", "name": "c", "dimensions": {}},
        "node": {**payload, "path": "/c", "name": "c"},
    }
    result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
    assert not result.success and not TapFile.objects.filter(path="/c").exists()


@SPEC("req-tap-files-node-8")
def test_no_other_internal_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.guards import files_internal_writers as guard

    guard.FilesInternalWritersGuard().check()
    files = {
        "tap_web/apps.py": "",
        "tap_web/sneaky.py": (
            "from tap_grid.services import _create_node_internal, write_batch\n"
            "_create_node_internal('tap_file', {})\n"
            "write_batch([WriteOperation(verb='create_edge', edge_type='CONTAINS_TAP_FILE')], _internal_only_bypass=True)\n"
        ),
        "tap_web/fine.py": "from tap_grid.services import write_batch\nwrite_batch([WriteOperation(type_slug='layout')])\n",
        "tap_web/tests/test_x.py": "_create_node_internal('tap_directory', {})\n",
        "tap_files/apps.py": "",
        "tap_files/holding.py": "write_batch([WriteOperation(type_slug='tap_file')])\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    monkeypatch.setattr(guard, "REPO_ROOT", tmp_path)
    with pytest.raises(AssertionError) as caught:
        guard.FilesInternalWritersGuard().check()
    message = str(caught.value)
    assert "tap_web/sneaky.py:2 _create_node_internal names tap_file" in message
    assert "tap_web/sneaky.py:3 write_batch names CONTAINS_TAP_FILE" in message
    assert "fine.py" not in message and "test_x.py" not in message and "holding.py" not in message


# --------------------------------------------------------------------------- directories


@SPEC("req-tap-files-directory-1")
def test_the_directory_and_its_edges_are_declared() -> None:
    from tap_grid.constraints import get_edge_type_constraints, is_internal_edge_type

    assert TapDirectory.INTERNAL_ONLY and TapFile.INTERNAL_ONLY
    assert set(TapDirectory.CONTAINMENT_EDGES) == {"CONTAINS_TAP_DIRECTORY", "CONTAINS_TAP_FILE"}
    for slug, target in (("CONTAINS_TAP_DIRECTORY", "tap_directory"), ("CONTAINS_TAP_FILE", "tap_file")):
        assert is_internal_edge_type(slug)
        constraints = get_edge_type_constraints(slug)
        assert constraints is not None and constraints.sources == {"tap_directory"} and constraints.targets == {target}
    assert not is_internal_edge_type("FILE_CONTENTS")


@pytest.mark.django_db
@SPEC("req-tap-files-directory-2")
@SPEC("req-tap-files-directory-3")
@SPEC("req-tap-files-directory-5")
def test_one_parent_right_ends_and_no_cycle(store: LocalBackend) -> None:
    _hold("/a/b/one.txt", b"1")
    _hold("/a/b/two.txt", b"2")
    _hold("/a/c/three.txt", b"3")
    _hold("/a/b/one.txt", b"1 again")
    # The helper is the only writer: every directory and file has at most one parent edge, each edge
    # runs between the right types, and no directory is its own ancestor.
    for edge_type in ("CONTAINS_TAP_DIRECTORY", "CONTAINS_TAP_FILE"):
        targets = [e.to_entity_id for e in _edges(edge_type)]
        assert len(targets) == len(set(targets)), edge_type
    for edge in _edges("CONTAINS_TAP_DIRECTORY"):
        assert (edge.from_entity.entity_type, edge.to_entity.entity_type) == ("tap_directory", "tap_directory")
    for edge in _edges("CONTAINS_TAP_FILE"):
        assert (edge.from_entity.entity_type, edge.to_entity.entity_type) == ("tap_directory", "tap_file")
    parents = {e.to_entity_id: e.from_entity_id for e in _edges("CONTAINS_TAP_DIRECTORY")}
    for start in parents:
        seen, node = set(), start
        while node in parents:
            assert node not in seen
            seen.add(node)
            node = parents[node]
    # And nothing else can add a second parent or a wrong end: the generic verbs refuse both edges.
    a, b = TapDirectory.objects.get(path="/a").entity, TapDirectory.objects.get(path="/a/b").entity
    one = _file("/a/b/one.txt").entity
    for frm, to, slug in ((a, one, "CONTAINS_TAP_FILE"), (b, a, "CONTAINS_TAP_DIRECTORY")):
        from tap_grid.exceptions import InvalidEdgeError

        with pytest.raises(InvalidEdgeError):
            create_edge(frm, to, slug)
    assert len(_edges("CONTAINS_TAP_FILE", to_entity_id=one.pk)) == 1


@pytest.mark.django_db
@SPEC("req-tap-files-directory-4")
def test_retiring_a_directory_retires_what_it_holds(store: LocalBackend) -> None:
    held = [_hold(p, p.encode()) for p in ("/top/a.txt", "/top/sub/b.txt", "/elsewhere/c.txt")]
    top = TapDirectory.objects.get(path="/top").entity_id
    result = _internal([WriteOperation(verb="delete_node", target=top, cascade="contained", reason="operator")])
    assert result.success, result.errors
    assert not TapFile.objects.filter(path__startswith="/top/").exists()
    assert not TapDirectory.objects.filter(path__startswith="/top").exists()
    assert TapFile.objects.filter(path="/elsewhere/c.txt").exists()
    for h in held:
        assert store.exists(h.identifier)


@pytest.mark.django_db
@SPEC("req-tap-files-directory-6")
def test_paths_follow_edges(store: LocalBackend) -> None:
    for p in ("/x/y/z/deep.bin", "/x/y/side.bin", "/x/top.bin", "/loose.bin"):
        _hold(p, p.encode())
    containment: list[Any] = list(Edge.objects.filter(edge_type__startswith="CONTAINS_TAP_"))
    parent_of = {e.to_entity_id: e.from_entity_id for e in containment}
    names = {n.entity_id: n.name for n in [*TapFile.objects.all(), *TapDirectory.objects.all()]}
    for node in [*TapFile.objects.all(), *TapDirectory.objects.all()]:
        chain, here = [], node.entity_id
        while here is not None:
            chain.append(names[here])
            here = parent_of.get(here)
        assert node.path == "/" + "/".join(reversed(chain)), node.path


@pytest.mark.django_db
@SPEC("req-tap-files-directory-7")
def test_only_tap_files_writes_directories_and_containment(store: LocalBackend) -> None:
    from tap_grid.exceptions import InvalidEdgeError
    from tap_grid.grift import grift_import
    from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

    assert not create_node("tap_directory", {"name": "d", "path": "/d"}).success
    _hold("/d/f.txt", b"f")
    d, f = TapDirectory.objects.get(path="/d"), _file("/d/f.txt")
    assert not write_batch([WriteOperation(verb="patch_node", target=d.entity_id, payload={"name": "e"})]).success
    assert not write_batch([WriteOperation(verb="delete_node", target=d.entity_id)]).success
    edge = _edges("CONTAINS_TAP_FILE", to_entity_id=f.entity_id)[0]
    assert not write_batch([WriteOperation(verb="delete_edge", target=edge.entity_id)]).success
    with pytest.raises(InvalidEdgeError):
        create_edge(d.entity, f.entity, "CONTAINS_TAP_FILE")
    envelope = {"entity_type": "edge", "dimensions": {}, "entity_id": str(uuid.uuid4())}
    grift_edge = {
        "entity": envelope,
        "edge": {
            "from_entity_id": str(d.entity_id),
            "to_entity_id": str(f.entity_id),
            "edge_type": "CONTAINS_TAP_FILE",
            "properties": {},
        },
    }
    assert not grift_import(_minimal_doc([_batch_container(_batch_entity_id(), edges=[grift_edge])])).success
    assert TapDirectory.objects.get(path="/d").name == "d" and len(_edges("CONTAINS_TAP_FILE")) == 1


# --------------------------------------------------------------------------- format records


@pytest.mark.django_db
@SPEC("req-tap-files-format-record-1")
def test_file_contents_is_declared_with_open_targets_and_a_required_digest() -> None:
    from tap_grid.constraints import WILDCARD, get_edge_type_constraints, validate_edge_properties
    from tap_grid.exceptions import EdgePropertyValidationError

    constraints = get_edge_type_constraints("FILE_CONTENTS")
    assert constraints is not None and constraints.sources == {"tap_file"} and constraints.targets is WILDCARD
    with pytest.raises(EdgePropertyValidationError):
        validate_edge_properties("FILE_CONTENTS", {})
    with pytest.raises(EdgePropertyValidationError):
        validate_edge_properties("FILE_CONTENTS", {"sha256": "nope"})
    validate_edge_properties("FILE_CONTENTS", {"sha256": "a" * 64})


@pytest.mark.django_db
@SPEC("req-tap-files-format-record-4")
def test_a_plugin_batch_attaches_a_record_to_an_existing_file(store: LocalBackend) -> None:
    from tap_grid.grift import grift_import
    from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

    held = _hold("/sbom.json", b'{"sbom": true}')
    before = _file("/sbom.json").entity.version
    record = str(uuid.uuid4())
    node = {
        "entity": {"entity_id": record, "entity_type": "layout", "name": "parsed", "dimensions": {}},
        "node": {"name": "parsed"},
    }
    edge = {
        "entity": {"entity_type": "edge", "dimensions": {}, "entity_id": str(uuid.uuid4())},
        "edge": {
            "from_entity_id": str(held.entity_id),
            "to_entity_id": record,
            "edge_type": "FILE_CONTENTS",
            "properties": {"sha256": held.sha256},
        },
    }
    result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node], edges=[edge])]))
    assert result.success, [e.message for e in result.errors]
    assert [str(e.to_entity_id) for e in _edges("FILE_CONTENTS", from_entity_id=held.entity_id)] == [record]
    assert _file("/sbom.json").entity.version == before


@pytest.mark.django_db
@SPEC("req-tap-files-format-record-3")
def test_a_shared_record_survives_a_replacement(store: LocalBackend) -> None:
    first, second = _hold("/one.json", b"same"), _hold("/two.json", b"same")
    shared = _record("record of 'same'")
    _attach(first.entity_id, shared, first.sha256)
    _attach(second.entity_id, shared, second.sha256)
    shared_version = Entity.objects.get(pk=shared).version
    replaced = _hold("/two.json", b"different")
    assert _edges("FILE_CONTENTS", from_entity_id=second.entity_id) == []
    fresh = _record("record of 'different'")
    _attach(second.entity_id, fresh, replaced.sha256)
    assert Entity.objects.get(pk=shared).version == shared_version
    assert [e.to_entity_id for e in _edges("FILE_CONTENTS", from_entity_id=first.entity_id)] == [shared]
    assert [e.to_entity_id for e in _edges("FILE_CONTENTS", from_entity_id=second.entity_id)] == [fresh]


# --------------------------------------------------------------------------- holding


@pytest.mark.django_db
@SPEC("req-tap-files-hold-1")
def test_bytes_before_nodes(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.services.contract import DigestMismatch

    def refused(*_a: Any, **_k: Any) -> Any:
        raise DigestMismatch("the store refused the write")

    monkeypatch.setattr(holding, "store_file", refused)
    with pytest.raises(DigestMismatch):
        _hold("/dir/refused.txt", b"x")
    assert not TapFile.objects.exists() and not TapDirectory.objects.exists()
    monkeypatch.undo()
    order: list[str] = []
    from tap_files.services import store_file as real_store

    real_write = holding._write

    def stored(*a: Any, **k: Any) -> Any:
        order.append("store")
        return real_store(*a, **k)

    def written(*a: Any, **k: Any) -> None:
        order.append("grid")
        real_write(*a, **k)

    monkeypatch.setattr(holding, "store_file", stored)
    monkeypatch.setattr(holding, "_write", written)
    held = _hold("/dir/ok.txt", b"ok")
    assert order == ["store", "grid"] and store.exists(held.identifier)


@pytest.mark.django_db
@SPEC("req-tap-files-hold-2")
@SPEC("req-tap-files-hold-3")
def test_facts_from_the_store_and_one_identifier(store: LocalBackend) -> None:
    held = _hold("/facts.bin", b"0123456789", media_type="application/octet-stream")
    node = _file("/facts.bin")
    stat = store.stat(held.identifier)
    head = stat.version(stat.head)
    assert (
        (node.sha256, node.size_bytes, node.file_version) == (head.digest, head.size, stat.head) == (held.sha256, 10, 1)
    )
    assert node.media_type == "application/octet-stream"
    assert held.identifier == identifier_for(node.entity_id) and held.entity_id == node.entity_id
    assert "sha256" not in hold_file.__wrapped__.__code__.co_varnames[: hold_file.__wrapped__.__code__.co_argcount]  # type: ignore[attr-defined]


@pytest.mark.django_db
@SPEC("req-tap-files-hold-4")
@SPEC("req-tap-files-hold-8")
def test_the_helper_writes_the_nodes_and_makes_directories_as_needed(store: LocalBackend) -> None:
    _hold("/p/q/r/first.txt", b"1")
    assert set(TapDirectory.objects.values_list("path", flat=True)) == {"/p", "/p/q", "/p/q/r"}
    assert len(_edges("CONTAINS_TAP_DIRECTORY")) == 2 and len(_edges("CONTAINS_TAP_FILE")) == 1
    directories_before = TapDirectory.objects.count()
    _hold("/p/q/r/second.txt", b"2")
    assert TapDirectory.objects.count() == directories_before and len(_edges("CONTAINS_TAP_DIRECTORY")) == 2
    assert len(_edges("CONTAINS_TAP_FILE")) == 2
    # Written by a program actor through the trusted-internal path; a person is refused first.
    person = User.objects.create_user(username=f"p-{uuid.uuid4().hex[:6]}", password="x")
    person.groups.add(Group.objects.get(name="tap_admin"))
    objects_before = sorted(store.identifiers())
    with pytest.raises(UnguardedOperation):
        hold_file("/p/human.txt", io.BytesIO(b"h"), caller_context=CallerContext(user=person))
    assert sorted(store.identifiers()) == objects_before and not TapFile.objects.filter(path="/p/human.txt").exists()


@pytest.mark.django_db
@SPEC("req-tap-files-hold-5")
def test_a_new_version_updates_the_same_node(store: LocalBackend) -> None:
    first = _hold("/v.txt", b"version one")
    second = _hold("/v.txt", b"version two")
    node = _file("/v.txt")
    assert node.entity_id == first.entity_id and node.file_version == first.file_version + 1 == second.file_version
    history = list(TapFile.history.filter(entity_id=node.entity_id).values_list("sha256", flat=True))
    assert first.sha256 in history and node.sha256 == second.sha256
    assert _read(node.entity_id, 1) == b"version one" and _read(node.entity_id) == b"version two"
    unchanged = _hold("/v.txt", b"version two")
    assert not unchanged.changed and _file("/v.txt").file_version == 2


@pytest.mark.django_db
@SPEC("req-tap-files-hold-6")
def test_a_caller_without_files_create_is_refused_unchanged(store: LocalBackend) -> None:
    scheduler = User.objects.create_user(username=f"s-{uuid.uuid4().hex[:6]}", password="x", user_kind=UserKind.PROGRAM)
    scheduler.groups.add(Group.objects.get(name="tap_cares.scheduler"))
    with pytest.raises(CapabilityDenied) as caught:
        hold_file("/nope.txt", io.BytesIO(b"n"), caller_context=CallerContext(user=scheduler))
    assert "files.create" in str(caught.value)
    assert not list(store.identifiers()) and not TapFile.objects.exists()


@pytest.mark.django_db
@SPEC("req-tap-files-hold-7")
@pytest.mark.parametrize("retry", ["same bytes", "different bytes"])
def test_a_refused_write_then_a_retry(store: LocalBackend, monkeypatch: pytest.MonkeyPatch, retry: str) -> None:
    held = _hold("/retry.txt", b"v1")
    real_write = holding._write

    def refused(*_a: Any, **_k: Any) -> None:
        raise HoldError("the grid refused the write")

    monkeypatch.setattr(holding, "_write", refused)
    with pytest.raises(HoldError):
        _hold("/retry.txt", b"v2")
    node = _file("/retry.txt")
    assert (node.file_version, node.sha256) == (1, held.sha256) and _read(node.entity_id, node.file_version) == b"v1"
    assert store.stat(held.identifier).head == 2
    monkeypatch.setattr(holding, "_write", real_write)
    again = _hold("/retry.txt", b"v2" if retry == "same bytes" else b"v3")
    expected = 2 if retry == "same bytes" else 3
    node = _file("/retry.txt")
    assert store.stat(held.identifier).head == expected == node.file_version == again.file_version
    assert node.sha256 == store.stat(held.identifier).version(expected).digest
    assert _read(node.entity_id, node.file_version) == (b"v2" if retry == "same bytes" else b"v3")


@pytest.mark.django_db
@SPEC("req-tap-files-hold-9")
def test_a_replaced_file_drops_its_old_record(store: LocalBackend) -> None:
    held = _hold("/report.pdf", b"old report")
    record = _record("parse of the old report")
    _attach(held.entity_id, record, held.sha256)
    record_version = Entity.objects.get(pk=record).version
    _hold("/report.pdf", b"new report")
    assert _edges("FILE_CONTENTS", from_entity_id=held.entity_id) == []
    assert Entity.objects.get(pk=record).version == record_version
    # The caller's batch attaching the new record fails: the file still has none.
    failed = write_batch(
        [
            WriteOperation(verb="create_node", type_slug="layout", payload={"name": "parse of the new report"}),
            WriteOperation(verb="create_node", type_slug="layout", payload={}),
        ]
    )
    assert not failed.success
    assert _edges("FILE_CONTENTS", from_entity_id=held.entity_id) == []


# --------------------------------------------------------------------------- capabilities


@pytest.mark.django_db
@SPEC("req-tap-files-capabilities-2")
def test_grid_read_sees_the_node_and_not_the_bytes(store: LocalBackend) -> None:
    from tap_grid.services import get_node

    held = _hold("/secret.txt", b"secret")
    group = Group.objects.create(name=f"g-{uuid.uuid4().hex[:6]}")
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from tap_auth.models import Capability

    group.permissions.add(
        Permission.objects.get(content_type=ContentType.objects.get_for_model(Capability), codename="grid_read")
    )
    reader = User.objects.create_user(username=f"r-{uuid.uuid4().hex[:6]}", password="x")
    reader.groups.add(group)
    ctx = CallerContext(user=reader)
    node = get_node(held.entity_id, caller_context=ctx)
    assert node.path == "/secret.txt" and node.sha256 == held.sha256
    with pytest.raises(CapabilityDenied):
        open_file(held.identifier, caller_context=ctx)
