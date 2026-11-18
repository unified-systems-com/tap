"""The file store gateway: capabilities, gating, the actor, logging, and the manifest table.

`specs/spec-tap-file-store.md`: `req-tap-files-capabilities`, `req-tap-files-gateway`,
`req-tap-files-logging`, and the parts of `req-tap-files-root` and `req-tap-files-mount-gate` that
land with them.
"""

from __future__ import annotations

import inspect
import io
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from tap_auth import policy, sync
from tap_auth.capabilities import get_capability
from tap_auth.errors import CapabilityDenied
from tap_auth.models import Capability, User
from tap_files import services
from tap_files.services import contract
from tap_files.store import inventory as inv
from tap_files.store import layout
from tap_files.store.local import LocalBackend
from tap_grid.caller_context import CallerContext

_REPO = Path(__file__).resolve().parents[2]
_MOUNT = "/var/lib/tap/files"
_FILE_CAPS = ("files.create", "files.read", "files.update", "files.delete")

# Each operation, the capability it needs, and a call that would succeed for an actor holding it.
_OPERATIONS = [
    ("store_file", "files.create"),
    ("add_file_version", "files.update"),
    ("rename_file", "files.update"),
    ("open_file", "files.read"),
    ("file_info", "files.read"),
    ("file_exists", "files.read"),
]


@pytest.fixture
def synced(db: Any) -> None:
    sync.sync_auth()


@pytest.fixture
def root(tmp_path: Path, settings: Any) -> Path:
    path = tmp_path / "files"
    path.mkdir()
    LocalBackend(path).initialise()
    settings.TAP_FILES_ROOT = str(path)
    return path


def _user_in(*groups: str) -> User:
    user = User.objects.create_user(username=f"u-{uuid.uuid4().hex[:8]}", password="x")
    for name in groups:
        user.groups.add(Group.objects.get(name=name))
    return user


def _holding(*capabilities: str) -> User:
    """An actor in an ad-hoc group holding exactly *capabilities*."""
    group = Group.objects.create(name=f"g-{uuid.uuid4().hex[:8]}")
    content_type = ContentType.objects.get_for_model(Capability)
    for name in capabilities:
        group.permissions.add(Permission.objects.get(content_type=content_type, codename=name.replace(".", "_")))
    user = User.objects.create_user(username=f"h-{uuid.uuid4().hex[:8]}", password="x")
    user.groups.add(group)
    return user


def _ctx(user: User) -> CallerContext:
    return CallerContext(user=user)


def _new_id() -> str:
    return layout.urn(str(uuid.uuid4()))


def _call(op: str, ident: str, ctx: CallerContext, head: int = 1) -> Any:
    fn = getattr(services, op)
    if op == "store_file":
        return fn(ident, "a.txt", io.BytesIO(b"two"), caller_context=ctx)
    if op == "add_file_version":
        return fn(ident, head, "a.txt", io.BytesIO(b"two"), caller_context=ctx)
    if op == "rename_file":
        return fn(ident, head, "b.txt", caller_context=ctx)
    return fn(ident, caller_context=ctx)


def _records(caplog: pytest.LogCaptureFixture) -> list[Any]:
    return [r for r in caplog.records if getattr(r, "message_code", None) == contract.FILE_OPERATION_CODE]


# --------------------------------------------------------------------------- capabilities


@pytest.mark.spec("req-tap-files-capabilities-1")
def test_the_four_capabilities_are_registered_with_descriptions_and_risks() -> None:
    from tap.jsonfiles import load_json_file

    data = load_json_file(_REPO / "tap_auth" / "tap_auth.capabilities.json")
    by_name = {c["name"]: c for c in data["capabilities"]}
    risks = {name: by_name[name]["risk"] for name in _FILE_CAPS}
    assert risks == {"files.create": "medium", "files.read": "medium", "files.update": "medium", "files.delete": "high"}
    for name in _FILE_CAPS:
        spec = get_capability(name)
        assert spec is not None and spec.description.strip(), name
    # The loader validated the file against its schema at import; check it again directly.
    import jsonschema

    schema = json.loads((_REPO / "tap_auth" / "schemas" / "capabilities.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)
    assert (contract.FILES_CREATE, contract.FILES_READ, contract.FILES_UPDATE, contract.FILES_DELETE) == _FILE_CAPS


@pytest.mark.spec("req-tap-files-capabilities-2")
def test_grid_read_is_not_enough_for_the_bytes(synced: None, root: Path) -> None:
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(b"secret"), caller_context=_ctx(_holding("files.create")))
    reader = _holding("grid.read")
    assert policy.can(_ctx(reader), "grid.read") is True
    with pytest.raises(CapabilityDenied):
        services.open_file(ident, caller_context=_ctx(reader))


@pytest.mark.spec("req-tap-files-capabilities-5")
def test_the_collector_actor_can_store_and_the_grant_is_named_global_and_interim(synced: None) -> None:
    ctx = _ctx(_user_in("tap_cares.collector"))
    assert [policy.can(ctx, c) for c in _FILE_CAPS] == [True, True, True, False]
    from tap.jsonfiles import load_json_file

    role = load_json_file(_REPO / "tap_auth" / "tap_auth.roles.json")["roles"]["tap_cares.collector"]
    assert {"files.create", "files.update", "files.read"} <= set(role["capabilities"])
    sentence = next(s for s in role["description"].split(". ") if "files.create" in s)
    assert "global" in sentence and "interim" in sentence and "1205" in role["description"]


@pytest.mark.spec("req-tap-files-capabilities-4")
def test_the_viewer_can_read_and_nothing_else(synced: None) -> None:
    ctx = _ctx(_user_in("tap_viewer"))
    assert [policy.can(ctx, c) for c in _FILE_CAPS] == [False, True, False, False]


@pytest.mark.spec("req-tap-files-capabilities-3")
def test_no_capability_implies_another(synced: None, root: Path) -> None:
    ident = _new_id()
    updater = _ctx(_holding("files.update"))
    with pytest.raises(CapabilityDenied):
        services.store_file(ident, "a.txt", io.BytesIO(b"x"), caller_context=updater)
    creator = _ctx(_holding("files.create"))
    services.store_file(ident, "a.txt", io.BytesIO(b"x"), caller_context=creator)
    for op in ("open_file", "file_info", "file_exists"):
        with pytest.raises(CapabilityDenied):
            _call(op, ident, creator)


# --------------------------------------------------------------------------- gateway


@pytest.mark.spec("req-tap-files-gateway-1")
def test_every_export_is_a_gated_operation() -> None:
    from tap.guards.service_boundary import ServiceBoundaryGuard

    ServiceBoundaryGuard().check()
    assert sorted(services.__all__) == sorted(op for op, _cap in _OPERATIONS)
    source = Path(services.__file__).read_text(encoding="utf-8")
    for op, cap in _OPERATIONS:
        constant = {v: k for k, v in vars(contract).items() if k.startswith("FILES_")}[cap]
        assert f'@requires_capability({constant}, operation="{op}")\ndef {op}(' in source, op


@pytest.mark.spec("req-tap-files-gateway-2")
@pytest.mark.parametrize(("op", "cap"), _OPERATIONS)
def test_refused_without_the_capability_and_no_backend_call(
    synced: None, root: Path, monkeypatch: pytest.MonkeyPatch, op: str, cap: str
) -> None:
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(b"one"), caller_context=_ctx(_holding("files.create")))
    others = [c for c in _FILE_CAPS if c != cap]
    calls: list[str] = []
    monkeypatch.setattr(services._backend, "backend", lambda: calls.append("backend"))
    with pytest.raises(CapabilityDenied):
        _call(op, ident, _ctx(_holding(*others)))
    assert calls == []


@pytest.mark.spec("req-tap-files-gateway-3")
def test_the_writer_is_the_caller_contexts_actor(synced: None, root: Path) -> None:
    for op, _cap in _OPERATIONS:
        assert "actor" not in inspect.signature(getattr(services, op)).parameters, op
    creator, updater = _holding("files.create"), _holding("files.update")
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(b"one"), caller_context=_ctx(creator))
    services.add_file_version(ident, 1, "a.txt", io.BytesIO(b"two"), caller_context=_ctx(updater))
    services.rename_file(ident, 2, "b.txt", caller_context=_ctx(updater))
    stat = LocalBackend(root).stat(ident)
    assert [v.actor for v in stat.versions] == [str(creator.pk), str(updater.pk), str(updater.pk)]
    # The inventory on disk says the same, as OCFL's `user.name`.
    pair = (root / "ocfl" / layout.object_path(ident) / inv.INVENTORY).read_bytes()
    names = [v["user"]["name"] for v in json.loads(pair)["versions"].values()]
    assert names == [str(creator.pk), str(updater.pk), str(updater.pk)]
    # The ambient context is the actor too, when no explicit one is passed.
    from tap_grid.caller_context import set_caller_context

    set_caller_context(_ctx(creator))
    try:
        other = _new_id()
        services.store_file(other, "c.txt", io.BytesIO(b"three"))
    finally:
        set_caller_context(None)
    assert LocalBackend(root).stat(other).versions[0].actor == str(creator.pk)


@pytest.mark.spec("req-tap-files-gateway-4")
def test_no_operation_writes_the_grid(synced: None, root: Path) -> None:
    from tap_grid.models import Edge, Entity

    before = (Entity.objects.count(), Edge.objects.count())
    admin = _ctx(_user_in("tap_admin"))
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(b"one"), caller_context=admin)
    for op, _cap in _OPERATIONS[1:]:
        result = _call(op, ident, admin, LocalBackend(root).stat(ident).head)
        if op == "open_file":
            result.close()
    assert (Entity.objects.count(), Edge.objects.count()) == before


@pytest.mark.spec("req-tap-files-gateway-5")
def test_the_gateway_module_binds_no_backend() -> None:
    from tap_files import store
    from tap_files.store import local

    handles = {id(store.get_store), id(local.LocalBackend), id(store), id(local)}
    public = {name: value for name, value in vars(services).items() if not name.startswith("_")}
    assert not [name for name, value in public.items() if id(value) in handles], sorted(public)
    assert not hasattr(services, "get_store")


@pytest.mark.spec("req-tap-files-gateway-5")
def test_nothing_else_reaches_the_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.guards import files_backend_reach as reach

    reach.FilesBackendReachGuard().check()
    # Seeded: a download view, a plugin-ish module and a `from tap_files import store` all fail;
    # the gateway, boot and tests do not.
    files = {
        "tap_web/apps.py": "",
        "tap_web/download.py": "from tap_files.store import get_store\n",
        "tap_web/other.py": "from tap_files import store\nimport tap_files.store.local\n",
        "tap_web/fine.py": (
            "from tap_files.services import open_file\nfrom tap_files.services import contract\n"
            "from tap_files.services.contract import FILES_READ\nfrom tap_files.config import configured_root\n"
        ),
        "tap_web/sideways.py": "from tap_files.services import _backend\nfrom tap_files.services import _record\n",
        "tap_web/via_leak.py": "from tap_files.services.leak import get_store\nimport tap_files.services.leak\n",
        "tap_files/services/leak.py": "from tap_files.store import get_store\n",
        "tap_files/services/contract.py": (
            "from tap_files.store.errors import ObjectExists\nfrom tap_files.store.protocol import OpenedFile\n"
            "from tap_files.store import get_store\n"
        ),
        "tap_files/services/_backend.py": "from tap_files.store import get_store\n",
        "tap_web/tests/test_x.py": "from tap_files.store import get_store\n",
        "tap_files/apps.py": "",
        "tap_files/boot.py": "from tap_files.store import get_store\n",
        "tap_files/services/__init__.py": (
            'from tap_files.store import get_store\n__all__ = ["open_file", "store_file"]\n'
        ),
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    monkeypatch.setattr(reach, "REPO_ROOT", tmp_path)
    with pytest.raises(AssertionError) as caught:
        reach.FilesBackendReachGuard().check()
    message = str(caught.value)
    assert "tap_web/download.py:1" in message and "tap_web/other.py:1" in message and "tap_web/other.py:2" in message
    assert "tap_web/sideways.py:1 imports tap_files.services._backend" in message
    assert "tap_web/sideways.py:2 imports tap_files.services._record" in message
    # A public submodule of the gateway may not hold the backend, nor may a caller go through one;
    # the contract may take the store's errors and result types, and nothing else.
    assert "tap_files/services/leak.py:1 imports tap_files.store" in message
    assert "tap_web/via_leak.py:1 imports tap_files.services.leak" in message
    assert "tap_web/via_leak.py:2 imports tap_files.services.leak" in message
    assert "tap_files/services/contract.py:3 imports tap_files.store" in message
    assert "contract.py:1" not in message and "contract.py:2" not in message
    assert "fine.py" not in message and "test_x.py" not in message
    assert "boot.py" not in message and "services/__init__.py" not in message and "_backend.py" not in message


# --------------------------------------------------------------------------- logging


@pytest.mark.spec("req-tap-files-logging-1")
def test_one_record_per_operation_whatever_the_outcome(
    synced: None, root: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    admin, nobody = _ctx(_user_in("tap_admin")), _ctx(_holding())
    ident = _new_id()
    for op, _cap in _OPERATIONS:
        caplog.clear()
        head = LocalBackend(root).stat(ident).head if op != "store_file" else 0
        result = _call(op, ident, admin, head)
        if op == "open_file":
            result.close()
        assert [r.message_data["outcome"] for r in _records(caplog)] == ["done"], op
        caplog.clear()
        with pytest.raises(CapabilityDenied):
            _call(op, ident, nobody)
        assert [r.message_data["outcome"] for r in _records(caplog)] == ["refused"], op
    # A conflict is refused, a missing object is refused, and an integrity failure has failed.
    caplog.clear()
    with pytest.raises(contract.VersionConflict):
        services.add_file_version(ident, 1, "a.txt", io.BytesIO(b"late"), caller_context=admin)
    with pytest.raises(contract.StoredFileNotFound):
        services.open_file(_new_id(), caller_context=admin)
    stat = LocalBackend(root).stat(ident)
    content = next((root / "ocfl" / layout.object_path(ident)).glob("v*/content/*"))
    content.chmod(0o640)
    content.write_bytes(b"tampered")
    with pytest.raises(contract.FileIntegrityError):
        services.open_file(ident, int(content.parts[-3][1:]), caller_context=admin)
    got = [
        (r.message_data["operation"], r.message_data["outcome"], r.message_data["reason_class"])
        for r in _records(caplog)
    ]
    assert got == [
        ("add_file_version", "refused", "VersionConflict"),
        ("open_file", "refused", "StoredFileNotFound"),
        ("open_file", "failed", "FileIntegrityError"),
    ]
    assert stat.head >= 1
    # Not enabled is a refusal too, and still one record.
    from django.conf import settings

    settings.TAP_FILES_ROOT = ""
    caplog.clear()
    with pytest.raises(contract.FileStoreNotEnabled):
        services.file_exists(ident, caller_context=admin)
    assert [(r.message_data["outcome"], r.message_data["reason_class"]) for r in _records(caplog)] == [
        ("refused", "FileStoreNotEnabled")
    ]


@pytest.mark.spec("req-tap-files-logging-2")
def test_a_read_names_the_reader(synced: None, root: Path, caplog: pytest.LogCaptureFixture) -> None:
    ident = _new_id()
    stored = services.store_file(ident, "a.txt", io.BytesIO(b"one"), caller_context=_ctx(_holding("files.create")))
    reader = _user_in("tap_viewer")
    caplog.set_level(logging.INFO)
    caplog.clear()
    services.open_file(ident, caller_context=_ctx(reader)).close()
    (record,) = _records(caplog)
    data = record.message_data
    assert (data["operation"], data["outcome"], data["actor"]) == ("open_file", "done", str(reader.pk))
    assert (data["identifier"], data["version"], data["digest"]) == (ident, 1, stored.digest)
    assert record.entity_id == layout.check_identifier(ident)


@pytest.mark.spec("req-tap-files-logging-3")
def test_a_refused_read_is_recorded(synced: None, root: Path, caplog: pytest.LogCaptureFixture) -> None:
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(b"one"), caller_context=_ctx(_holding("files.create")))
    outsider = _holding("grid.read")
    caplog.set_level(logging.INFO)
    caplog.clear()
    with pytest.raises(CapabilityDenied):
        services.open_file(ident, caller_context=_ctx(outsider))
    (record,) = _records(caplog)
    assert record.levelno == logging.WARNING
    data = record.message_data
    assert (data["operation"], data["outcome"], data["actor"], data["reason_class"]) == (
        "open_file",
        "refused",
        str(outsider.pk),
        "CapabilityDenied",
    )


@pytest.mark.spec("req-tap-files-logging-4")
def test_no_content_in_logs(synced: None, root: Path, caplog: pytest.LogCaptureFixture) -> None:
    marker = f"MARKER-{uuid.uuid4().hex}"
    admin = _ctx(_user_in("tap_admin"))
    caplog.set_level(logging.DEBUG)
    ident = _new_id()
    services.store_file(ident, "a.txt", io.BytesIO(f"one {marker} one".encode()), caller_context=admin)
    services.add_file_version(ident, 1, "a.txt", io.BytesIO(f"two {marker}".encode()), caller_context=admin)
    opened = services.open_file(ident, caller_context=admin)
    assert marker.encode() in opened.stream.read()
    opened.close()
    services.file_info(ident, caller_context=admin)
    assert caplog.records
    for record in caplog.records:
        rendered = record.getMessage() + repr(vars(record))
        assert marker not in rendered, record.name


# --------------------------------------------------------------------------- manifest and boot


_BASE = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "acme"\nname = "Acme"\n'


def _load(tmp_path: Path, body: str) -> Any:
    from tap_plugins.manifest import load_manifest

    (tmp_path / "tap-plugin.toml").write_text(_BASE + body, encoding="utf-8")
    return load_manifest(tmp_path)


@pytest.mark.spec("req-tap-files-mount-gate-8")
@pytest.mark.parametrize(
    ("body", "match"),
    [
        ('[file_store]\nrequired = "yes"\n', "file_store.required must be a boolean"),
        ("[file_store]\nrequired = 1\n", "file_store.required must be a boolean"),
        ("[file_store]\n", "file_store.required must be a boolean"),
        ("[file_store]\nrequired = true\nquota = 5\n", "unknown keys \\['quota'\\]"),
        ('file_store = "required"\n', "'file_store' must be a table"),
    ],
)
def test_the_manifest_table_is_strict(tmp_path: Path, body: str, match: str) -> None:
    from tap_plugins.manifest import FileStoreDeclaration, PluginManifestError

    assert _load(tmp_path, "").file_store is None
    assert _load(tmp_path, "[file_store]\nrequired = true\n").file_store == FileStoreDeclaration(required=True)
    assert _load(tmp_path, "[file_store]\nrequired = false\n").file_store == FileStoreDeclaration(required=False)
    with pytest.raises(PluginManifestError, match=match):
        _load(tmp_path, body)


def _plugin(label: str, required: bool | None) -> Any:
    """An installed plugin's app config, carrying only what the gate reads."""
    from tap_plugins.base import TapPluginConfig
    from tap_plugins.manifest import FileStoreDeclaration

    manifest = type("Manifest", (), {"file_store": None if required is None else FileStoreDeclaration(required)})()
    attrs = {"__module__": f"{label}.apps", "__init__": lambda self: None, "manifest": manifest, "label": label}
    return type(f"{label}Config", (TapPluginConfig,), attrs)()


@pytest.mark.spec("req-tap-files-mount-gate-6")
def test_required_but_not_enabled_aborts_naming_the_plugin(
    tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.apps import apps

    from tap_files import boot

    configs = [_plugin("needs_files", True), _plugin("could_use_files", False), _plugin("no_table", None)]
    real = apps.get_app_configs
    monkeypatch.setattr(apps, "get_app_configs", lambda: [*real(), *configs])
    assert boot.requiring_plugins() == ["needs_files"]
    settings.TAP_FILES_ROOT = ""
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(boot.FileStoreGateError, match="needs_files") as caught:
        boot.run_gate()
    assert "could_use_files" not in str(caught.value) and "no_table" not in str(caught.value)
    assert sorted(tmp_path.rglob("*")) == before


# --------------------------------------------------------------------------- compose


def _compose_web(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.rstrip() == "  web:")
    except StopIteration:
        return []
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    ") and not line.lstrip().startswith("#"):
            break
        block.append(line.strip())
    return block


@pytest.mark.spec("req-tap-files-root-2")
def test_compose_mounts_its_own_volume_and_sets_the_variable() -> None:
    base = _compose_web(_REPO / "docker-compose.yml")
    assert f"- files:{_MOUNT}" in base, base
    assert f"TAP_FILES_ROOT: {_MOUNT}" in base, base
    assert "  files:" in (_REPO / "docker-compose.yml").read_text(encoding="utf-8")
    # Not the plugin data volume, and not inside it.
    mounts = {line.split(":")[0][2:]: line.split(":")[1] for line in base if line.startswith("- ") and ":" in line}
    assert mounts["files"] != mounts["plugin_data"] and not _MOUNT.startswith(mounts["plugin_data"] + "/")
    for overlay in sorted(_REPO.glob("docker-compose.*.yml")):
        web = _compose_web(overlay)
        text = "\n".join(web)
        assert "TAP_FILES_ROOT" not in text and "- files:" not in text, overlay.name
        assert not any(line.startswith(("volumes: !override", "environment: !override")) for line in web)
