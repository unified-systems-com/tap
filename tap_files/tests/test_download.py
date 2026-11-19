"""The download route: `GET /files/<identifier>/download` (`req-tap-files-download`).

`specs/spec-tap-file-store.md`. Files are held through the helper as the harness's program actor;
requests come from a Django test client logged in as a person, whom the login wall's middleware binds
as the caller context.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client

from tap import serving
from tap_auth import sync
from tap_auth.models import Capability, User
from tap_files import views
from tap_files.holding import HeldFile, hold_file
from tap_files.models import TapFile
from tap_files.services import add_file_version
from tap_files.services.contract import FILE_OPERATION_CODE
from tap_files.store.local import LocalBackend
from tap_grid.service_types import WriteOperation
from tap_grid.services import write_batch
from tap_web.reserved import get_reserved_url_prefixes

SPEC = pytest.mark.spec


@pytest.fixture
def root(tmp_path: Path, settings: Any, db: Any) -> Path:
    sync.sync_auth()
    path = tmp_path / "files"
    path.mkdir()
    LocalBackend(path).initialise()
    settings.TAP_FILES_ROOT = str(path)
    return path


def _client(*groups: str, capabilities: tuple[str, ...] = ()) -> Client:
    user = User.objects.create_user(username=f"u-{uuid.uuid4().hex[:8]}", password="x")
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
    if capabilities:
        group = Group.objects.create(name=f"g-{uuid.uuid4().hex[:8]}")
        content_type = ContentType.objects.get_for_model(Capability)
        for cap in capabilities:
            codename = cap.replace(".", "_")
            group.permissions.add(Permission.objects.get(content_type=content_type, codename=codename))
        user.groups.add(group)
    client = Client()
    client.force_login(user)
    return client


def _reader() -> Client:
    """A person in `tap_viewer`, which holds `grid.read` and `files.read`."""
    return _client("tap_viewer")


def _hold(path: str, data: bytes, **kw: Any) -> HeldFile:
    return hold_file(path, io.BytesIO(data), **kw)


def _url(entity_id: Any) -> str:
    return f"/files/{entity_id}/download"


def _body(response: Any) -> bytes:
    return b"".join(response.streaming_content) if response.streaming else response.content


def _patch(entity_id: uuid.UUID, payload: dict[str, Any]) -> None:
    node = TapFile.objects.select_related("entity").get(entity_id=entity_id)
    op = WriteOperation(
        verb="patch_node", target=entity_id, payload=payload, entity_expected_version=node.entity.version
    )
    assert write_batch([op], _internal_only_bypass=True).success


def _store_ahead(held: HeldFile, version: int, data: bytes) -> None:
    """A version stored with no node recording it, as the helper leaves one after a refused grid write."""
    name = TapFile.objects.get(entity_id=held.entity_id).name
    add_file_version(held.identifier, version, name, io.BytesIO(data))


def _records(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [r.__dict__["message_data"] for r in caplog.records if r.__dict__.get("message_code") == FILE_OPERATION_CODE]


# --------------------------------------------------------------------------- what is sent


@SPEC("req-tap-files-node-1")
@SPEC("req-tap-files-download-1")
@SPEC("req-tap-files-download-2")
@SPEC("req-tap-files-download-9")
def test_a_reader_gets_the_bytes_as_an_attachment(root: Path, settings: Any) -> None:
    # The development profile's middleware overwrites Cache-Control with its own no-store.
    settings.TAP_SERVE_PROFILE = serving.PROFILE_PRODUCTION
    data = b"<html><script>alert(1)</script></html>"
    held = _hold("/reports/page.html", data, media_type="text/html")
    response = _reader().get(_url(held.entity_id))
    assert response.status_code == 200
    body = _body(response)
    assert body == data
    digest = hashlib.sha256(body).hexdigest()
    node = TapFile.objects.get(entity_id=held.entity_id)
    assert response["ETag"].strip('"') == digest == node.sha256
    assert response["Content-Disposition"] == 'attachment; filename="page.html"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Content-Type"] == "text/html"
    assert response["Content-Length"] == str(len(data))
    assert response["Cache-Control"] == "private, no-store"


@SPEC("req-tap-files-download-2")
def test_head_sends_the_headers_and_no_body(root: Path) -> None:
    held = _hold("/a.txt", b"twelve bytes", media_type="text/plain")
    response = _reader().head(_url(held.entity_id))
    assert response.status_code == 200
    assert _body(response) == b""
    assert response["Content-Length"] == "12" and response["Content-Disposition"].startswith("attachment")


@SPEC("req-tap-files-download-9")
@pytest.mark.parametrize(
    ("media_type", "sent"),
    [
        ("application/pdf", "application/pdf"),
        ("application/vnd.oasis.opendocument.text", "application/vnd.oasis.opendocument.text"),
        (None, "application/octet-stream"),
        ("", "application/octet-stream"),
        ("text/html; charset=utf-7", "application/octet-stream"),
        ("text/ html", "application/octet-stream"),
        ("text/html\r\nSet-Cookie: x=1", "application/octet-stream"),
        ("text/html\x00", "application/octet-stream"),
        ("texthtml", "application/octet-stream"),
    ],
)
def test_the_recorded_type_is_sent_only_when_well_formed(media_type: Any, sent: str) -> None:
    assert views.content_type_for(media_type) == sent


@SPEC("req-tap-files-download-9")
def test_a_malformed_recorded_type_goes_out_as_octet_stream(root: Path) -> None:
    held = _hold("/b.bin", b"x", media_type="text/html; charset=utf-7")
    response = _reader().get(_url(held.entity_id))
    assert response["Content-Type"] == "application/octet-stream"


@SPEC("req-tap-files-download-6")
def test_a_hostile_name_makes_one_well_formed_header(root: Path) -> None:
    name = 'a"b;c d é́ü.txt'
    held = _hold(f"/{name}", b"x")
    response = _reader().get(_url(held.entity_id))
    header = response["Content-Disposition"]
    assert header.startswith("attachment; filename*=utf-8''")
    assert "\n" not in header and "\r" not in header and '"' not in header and header.count(";") == 1
    # A name a node cannot carry (paths refuse control characters) still makes one header line.
    for hostile in ('evil"\r\nSet-Cookie: a=b', "x\nContent-Type: text/html", "plain;name.txt"):
        value = views.disposition_for(hostile)
        assert value.startswith("attachment; ") and "\n" not in value and "\r" not in value
    assert views.disposition_for("plain;name.txt") == 'attachment; filename="plain;name.txt"'


# --------------------------------------------------------------------------- which version


@SPEC("req-tap-files-download-10")
def test_the_node_version_is_served_not_the_head(root: Path) -> None:
    held = _hold("/v.txt", b"version one")
    _store_ahead(held, 1, b"version two")
    response = _reader().get(_url(held.entity_id))
    assert _body(response) == b"version one"
    assert response["ETag"].strip('"') == hashlib.sha256(b"version one").hexdigest()
    # The helper takes the stored head as the node's next version when it holds these bytes.
    _hold("/v.txt", b"version two")
    assert TapFile.objects.get(entity_id=held.entity_id).file_version == 2
    response = _reader().get(_url(held.entity_id))
    assert _body(response) == b"version two"
    assert response["ETag"].strip('"') == hashlib.sha256(b"version two").hexdigest()


@SPEC("req-tap-files-download-12")
def test_no_query_parameter_chooses_a_version(root: Path) -> None:
    held = _hold("/q.txt", b"one")
    _store_ahead(held, 1, b"refused two")
    _hold("/q.txt", b"three")
    assert TapFile.objects.get(entity_id=held.entity_id).file_version == 3
    client = _reader()
    for query in ("?version=2", "?version=1", "?v=2&version=2", "?head=1"):
        assert _body(client.get(_url(held.entity_id) + query)) == b"three"


@SPEC("req-tap-files-download-12")
def test_a_version_stored_ahead_of_the_node_is_never_served(root: Path) -> None:
    held = _hold("/r.txt", b"one")
    _store_ahead(held, 1, b"two")
    _store_ahead(held, 2, b"three, not yet recorded")
    for query in ("", "?version=3", "?version=2"):
        assert _body(_reader().get(_url(held.entity_id) + query)) == b"one"


@SPEC("req-tap-files-download-13")
def test_a_node_with_no_recorded_version_is_refused(
    root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    held = _hold("/n.txt", b"one")
    _store_ahead(held, 1, b"two")
    node = cast(TapFile, TapFile.objects.select_related("entity").get(entity_id=held.entity_id))
    # The field is non-null in the schema, so a malformed node is staged at the read.
    for missing in (None, 0):
        node.file_version = missing  # type: ignore[assignment]
        monkeypatch.setattr(views, "_live_file", lambda identifier, node=node: node)
        caplog.clear()
        with caplog.at_level(logging.INFO):
            response = _reader().get(_url(held.entity_id))
        assert response.status_code == 500
        assert b"file_version" in response.content
        assert b"one" not in response.content and b"two" not in response.content
        assert any("records no file_version" in r.getMessage() for r in caplog.records)
        assert [r["outcome"] for r in _records(caplog)] == ["failed"]


@SPEC("req-tap-files-download-14")
def test_a_recorded_version_the_store_does_not_hold_is_not_found(root: Path, tmp_path: Path, settings: Any) -> None:
    held = _hold("/m.txt", b"one")
    _store_ahead(held, 1, b"two")
    _patch(held.entity_id, {"file_version": 3})
    response = _reader().get(_url(held.entity_id))
    assert response.status_code == 404 and b"one" not in response.content and b"two" not in response.content
    # And with no object at all for the identifier.
    empty = tmp_path / "empty"
    empty.mkdir()
    LocalBackend(empty).initialise()
    settings.TAP_FILES_ROOT = str(empty)
    response = _reader().get(_url(held.entity_id))
    assert response.status_code == 404


# --------------------------------------------------------------------------- integrity


@SPEC("req-tap-files-download-11")
@pytest.mark.parametrize("field", ["sha256", "size_bytes"])
def test_node_and_store_must_agree(root: Path, field: str, caplog: pytest.LogCaptureFixture) -> None:
    held = _hold("/i.txt", b"agreed bytes")
    _patch(held.entity_id, {"sha256": "0" * 64} if field == "sha256" else {"size_bytes": 999})
    with caplog.at_level(logging.INFO):
        response = _reader().get(_url(held.entity_id))
    assert response.status_code == 500 and b"agreed" not in _body(response)
    assert any("integrity finding" in r.getMessage() for r in caplog.records)
    # The download's one record says the read failed, not that it was done.
    assert [(r["outcome"], r["reason_class"]) for r in _records(caplog)] == [("failed", "FileIntegrityError")]


@SPEC("req-tap-files-download-8")
def test_a_changed_file_fails_visibly(root: Path, caplog: pytest.LogCaptureFixture) -> None:
    data = b"original content"
    held = _hold("/c.txt", data)
    (content,) = [p for p in root.rglob("*") if p.is_file() and p.read_bytes() == data]
    os.chmod(content, 0o640)
    content.write_bytes(b"tampered content")
    with caplog.at_level(logging.INFO):
        response = _reader().get(_url(held.entity_id))
    assert response.status_code == 500 and b"content" not in _body(response)
    assert [(r["outcome"], r["reason_class"]) for r in _records(caplog)] == [("failed", "FileIntegrityError")]


# --------------------------------------------------------------------------- who may


@SPEC("req-tap-files-download-3")
def test_login_is_required(root: Path, settings: Any) -> None:
    held = _hold("/l.txt", b"private")
    response = Client().get(_url(held.entity_id))
    assert response.status_code == 302 and b"private" not in response.content
    assert not any("/files".startswith(p.rstrip("/")) for p in settings.TAP_LOGIN_EXEMPT_PREFIXES)


@SPEC("req-tap-files-download-4")
@pytest.mark.parametrize("held_caps", [("grid.read",), ()])
def test_without_files_read_the_refusal_does_not_reveal_existence(
    root: Path, held_caps: tuple[str, ...], caplog: pytest.LogCaptureFixture
) -> None:
    held = _hold("/s.txt", b"secret")
    client = _client(capabilities=held_caps)
    with caplog.at_level(logging.INFO):
        present = client.get(_url(held.entity_id))
        absent = client.get(_url(uuid.uuid4()))
        garbage = client.get(_url("not-a-uuid"))
    assert present.status_code == absent.status_code == garbage.status_code == 403
    assert present.content == absent.content == garbage.content
    assert [r["outcome"] for r in _records(caplog)] == ["refused"] * 3


@SPEC("req-tap-files-download-4")
def test_files_read_without_grid_read_is_refused_alike(root: Path) -> None:
    held = _hold("/g.txt", b"secret")
    client = _client(capabilities=("files.read",))
    present, absent = client.get(_url(held.entity_id)), client.get(_url(uuid.uuid4()))
    assert present.status_code == absent.status_code == 403 and present.content == absent.content


def test_an_unknown_identifier_is_not_found(root: Path) -> None:
    client = _reader()
    assert client.get(_url(uuid.uuid4())).status_code == 404
    assert client.get(_url("not-a-uuid")).status_code == 404


def test_a_node_of_another_type_is_not_found(root: Path) -> None:
    from tap_grid.services import create_node

    result = create_node("layout", {"name": "not a file"})
    assert _reader().get(_url(result.entity_id)).status_code == 404


@SPEC("req-tap-files-download-5")
def test_a_tombstoned_file_is_not_served_and_its_object_remains(root: Path) -> None:
    held = _hold("/t.txt", b"kept")
    assert write_batch([WriteOperation(verb="delete_node", target=held.entity_id)], _internal_only_bypass=True).success
    response = _reader().get(_url(held.entity_id))
    assert response.status_code == 404 and b"kept" not in response.content
    assert LocalBackend(root).exists(held.identifier)


@SPEC("req-tap-files-download-7")
def test_the_files_prefix_is_reserved() -> None:
    assert "/files" in get_reserved_url_prefixes()


# --------------------------------------------------------------------------- through the gateway


@SPEC("req-tap-files-download-15")
@SPEC("req-tap-files-logging-1")
def test_a_download_is_one_gateway_read_record(
    root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    held = _hold("/o.txt", b"logged")
    calls: list[tuple[Any, ...]] = []
    real = getattr(views, "open_file")  # noqa: B009 — the name the view calls, patched below

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(views, "open_file", spy)
    caplog.clear()
    with caplog.at_level(logging.INFO):
        response = _reader().get(_url(held.entity_id))
        _body(response)
    assert calls == [(held.identifier, 1)]
    (record,) = _records(caplog)
    assert record["operation"] == "open_file" and record["outcome"] == "done"
    assert record["route"] == views.ROUTE and record["digest"] == held.sha256 and record["version"] == 1
    assert record["actor"] == str(response.wsgi_request.user.pk)
    # The route itself reaches no backend module (the reach guard holds it to that).
    source = Path(views.__file__).read_text(encoding="utf-8")
    assert "tap_files.store" not in source and "_backend" not in source and "Entity.objects" not in source
