"""The report-only check and the health probe (`req-tap-files-check`, `req-tap-files-health`).

`specs/spec-tap-file-store.md`. Each test seeds one class of defect into a real store under a temporary
root and asserts the check names it; together they are `req-tap-files-check-5`, so a passing check is
not vacuous.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
from django.core.management import call_command

from tap import volume_mount
from tap_auth import sync
from tap_files import health
from tap_files.check import FAULT, NOTICE, REPORT_SCHEMA, Report, run_check
from tap_files.holding import HeldFile, hold_file
from tap_files.models import TapFile
from tap_files.services import add_file_version
from tap_files.store import inventory as inv
from tap_files.store import layout
from tap_files.store.local import LocalBackend
from tap_grid.models import Entity
from tap_grid.service_types import WriteOperation
from tap_grid.services import create_edge, create_node, write_batch
from tap_health.results import ProbeStatus

SPEC = pytest.mark.spec


@pytest.fixture
def store(tmp_path: Path, settings: Any, db: Any) -> LocalBackend:
    root = tmp_path / "files"
    root.mkdir()
    backend = LocalBackend(root)
    backend.initialise()
    settings.TAP_FILES_ROOT = str(root)
    return backend


def _hold(path: str, data: bytes = b"bytes") -> HeldFile:
    return hold_file(path, io.BytesIO(data))


def _kinds(report: Report, severity: str = FAULT) -> list[tuple[str, str]]:
    return [(f.kind, f.subject) for f in report.findings if f.severity == severity]


def _patch(entity_id: uuid.UUID, payload: dict[str, Any]) -> None:
    node = TapFile.objects.select_related("entity").get(entity_id=entity_id)
    op = WriteOperation(
        verb="patch_node", target=entity_id, payload=payload, entity_expected_version=node.entity.version
    )
    assert write_batch([op], _internal_only_bypass=True).success


def _tree(root: Path) -> dict[str, tuple[int, str]]:
    found = {}
    for path in sorted(root.rglob("*")):
        st = os.lstat(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and not path.is_symlink() else ""
        found[str(path.relative_to(root))] = (st.st_mtime_ns, digest)
    return found


def _objdir(store: LocalBackend, identifier: str) -> Path:
    return store.ocfl / layout.object_path(identifier)


def _seed_interrupted(store: LocalBackend) -> tuple[str, str]:
    """A staging leftover and a version directory above its object's head."""
    held = _hold("/interrupted.txt", b"one")
    (store.staging / f"{layout.encode_identifier(held.identifier)}.abc123").mkdir()
    above = _objdir(store, held.identifier) / "v2"
    above.mkdir()
    (above / "stray").write_bytes(b"x")
    return held.identifier, str(above.relative_to(store.root))


# --------------------------------------------------------------------------- the check


@SPEC("req-tap-files-check-1")
def test_a_clean_store_is_clean(store: LocalBackend) -> None:
    _hold("/a/one.txt", b"one")
    _hold("/a/two.txt", b"two")
    report = run_check(deep=True)
    assert report.findings == [] and not report.failed(strict=True)
    assert report.totals == {"objects": 2, "versions": 2, "bytes": 6, "nodes": 2}


@SPEC("req-tap-files-check-2")
@SPEC("req-tap-files-check-5")
def test_an_orphan_object_is_listed(store: LocalBackend) -> None:
    orphan = layout.urn(str(uuid.uuid4()))
    store.create(orphan, "lost.bin", io.BytesIO(b"lost"), "t")
    _hold("/kept.txt")
    assert _kinds(run_check()) == [("orphan_object", orphan)]


@SPEC("req-tap-files-check-2")
def test_a_tombstoned_node_leaves_an_orphan(store: LocalBackend) -> None:
    held = _hold("/gone.txt")
    assert write_batch([WriteOperation(verb="delete_node", target=held.entity_id)], _internal_only_bypass=True).success
    assert _kinds(run_check()) == [("orphan_object", held.identifier)]


@SPEC("req-tap-files-check-3")
@SPEC("req-tap-files-check-5")
def test_deep_finds_a_changed_byte(store: LocalBackend) -> None:
    held = _hold("/changed.txt", b"original")
    (content,) = [p for p in store.ocfl.rglob("*") if p.is_file() and p.read_bytes() == b"original"]
    os.chmod(content, 0o640)
    content.write_bytes(b"0riginal")
    os.chmod(content, 0o440)
    assert run_check().findings == []  # same size, so only re-hashing sees it
    deep = run_check(deep=True)
    (finding,) = deep.findings
    assert (finding.kind, finding.subject) == ("invalid_object", held.identifier)
    assert finding.detail.startswith("v1/content/") and "does not match its digest" in finding.detail


@SPEC("req-tap-files-check-4")
@SPEC("req-tap-files-check-6")
@SPEC("req-tap-files-check-5")
def test_what_recovery_would_do_is_listed_and_nothing_changes(store: LocalBackend) -> None:
    identifier, above = _seed_interrupted(store)
    torn = _hold("/torn.txt", b"torn")
    (_objdir(store, torn.identifier) / inv.SIDECAR).write_text("0" * 64 + " inventory.json\n")
    before = _tree(store.root)
    report = run_check(deep=True)
    assert _tree(store.root) == before
    interrupted = [f for f in report.findings if f.kind == "interrupted_write"]
    subjects = {f.subject for f in interrupted}
    assert any(s.startswith("staging/") for s in subjects)
    assert identifier in subjects and any(f.detail.startswith("v2 above the head v1") for f in interrupted)
    assert torn.identifier in subjects
    assert ("damaged_object", torn.identifier) in _kinds(report)
    assert (store.root / above).is_dir()


@SPEC("req-tap-files-check-7")
@SPEC("req-tap-files-check-5")
def test_a_node_with_no_bytes_is_listed(store: LocalBackend) -> None:
    entity_id = uuid.uuid4()
    op = WriteOperation(
        verb="create_node",
        type_slug="tap_file",
        entity_id=entity_id,
        payload={"name": "ghost.txt", "path": "/ghost.txt", "size_bytes": 1, "sha256": "a" * 64, "file_version": 1},
    )
    assert write_batch([op], _internal_only_bypass=True, batch_name="seed", batch_description="seed").success
    (finding,) = run_check().findings
    assert (finding.kind, finding.subject, finding.path) == (
        "node_without_bytes",
        f"urn:uuid:{entity_id}",
        "/ghost.txt",
    )


@SPEC("req-tap-files-check-8")
@SPEC("req-tap-files-check-5")
def test_a_disagreement_is_listed_with_both_values(store: LocalBackend) -> None:
    held = _hold("/d.txt", b"agreed")
    _patch(held.entity_id, {"sha256": "b" * 64})
    (finding,) = run_check().findings
    assert finding.kind == "node_disagrees" and "b" * 64 in finding.detail and held.sha256 in finding.detail
    ahead = _hold("/e.txt", b"one")
    _patch(ahead.entity_id, {"file_version": 3})
    assert ("node_ahead_of_store", ahead.identifier) in _kinds(run_check())


@SPEC("req-tap-files-check-8")
def test_a_size_disagreement_is_listed(store: LocalBackend) -> None:
    held = _hold("/s.txt", b"sized")
    _patch(held.entity_id, {"size_bytes": 999})
    (finding,) = run_check().findings
    assert finding.kind == "node_disagrees" and "999" in finding.detail and "5" in finding.detail


@SPEC("req-tap-files-check-9")
@SPEC("req-tap-files-check-5")
def test_a_head_ahead_is_a_notice(store: LocalBackend) -> None:
    held = _hold("/h.txt", b"one")
    add_file_version(held.identifier, 1, "h.txt", io.BytesIO(b"two, never recorded"))
    report = run_check()
    assert _kinds(report, NOTICE) == [("store_ahead_of_node", held.identifier)] and _kinds(report) == []
    assert not report.failed() and report.failed(strict=True)


@SPEC("req-tap-files-check-10")
@SPEC("req-tap-files-check-5")
def test_format_records_the_grid_allowed_are_listed(store: LocalBackend) -> None:
    held = _hold("/f.txt", b"formatted")
    first, second, stranger = (
        cast(uuid.UUID, create_node("layout", {"name": n}).entity_id) for n in ("r1", "r2", "not a file")
    )
    file_entity = Entity.objects.get(pk=held.entity_id)
    create_edge(file_entity, Entity.objects.get(pk=first), "FILE_CONTENTS", {"sha256": held.sha256})
    stale = create_edge(file_entity, Entity.objects.get(pk=second), "FILE_CONTENTS", {"sha256": "c" * 64})
    wrong = create_edge(
        Entity.objects.get(pk=stranger), Entity.objects.get(pk=first), "FILE_CONTENTS", {"sha256": held.sha256}
    )
    kinds = _kinds(run_check())
    assert ("format_record_duplicate", held.identifier) in kinds
    assert ("format_record_stale", str(stale.entity_id)) in kinds
    assert ("format_record_wrong_source", str(wrong.entity_id)) in kinds
    assert len(kinds) == 3


@SPEC("req-tap-files-check-5")
def test_a_link_below_ocfl_is_reported_and_not_followed(store: LocalBackend, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    (outside / "bbb" / "ccc").mkdir(parents=True)
    (store.ocfl / "aaa").symlink_to(outside, target_is_directory=True)
    assert _kinds(run_check()) == [("link_below_ocfl", "ocfl/aaa")]
    assert (outside / "bbb" / "ccc").is_dir()


@SPEC("req-tap-files-check-5")
@pytest.mark.parametrize("where", ["version", "content_dir", "content_file"])
def test_a_link_inside_an_object_is_reported_and_never_read(store: LocalBackend, tmp_path: Path, where: str) -> None:
    # Round 1 of the AI review on PR# 1242 - tap: the survey and a deep check must not stat or hash
    # through a link inside an object. The targets are unreadable, so following one would raise.
    held = _hold("/linked.txt", b"inside")
    objdir = _objdir(store, held.identifier)
    (content,) = list((objdir / "v1" / "content").iterdir())
    outside = tmp_path / f"outside-{where}"
    (outside / "content").mkdir(parents=True)
    secret = outside / "content" / content.name
    secret.write_bytes(b"outside")
    secret.chmod(0)
    if where == "version":
        os.rename(objdir / "v1", tmp_path / "moved-v1")
        (objdir / "v1").symlink_to(outside, target_is_directory=True)
    elif where == "content_dir":
        os.rename(objdir / "v1" / "content", tmp_path / "moved-content")
        (objdir / "v1" / "content").symlink_to(outside / "content", target_is_directory=True)
    else:
        content.chmod(0o640)
        content.unlink()
        content.symlink_to(secret)
    try:
        report = run_check(deep=True)
    finally:
        secret.chmod(0o600)
    faults = [(f.kind, f.subject) for f in report.findings if f.severity == FAULT]
    assert faults, report.findings
    if where == "version":
        assert ("link_below_ocfl", str((objdir / "v1").relative_to(store.root))) in faults
    else:
        assert ("invalid_object", held.identifier) in faults


@SPEC("req-tap-files-check-5")
def test_quarantine_is_listed_and_is_not_a_fault(store: LocalBackend) -> None:
    _seed_interrupted(store)
    store.recover()
    report = run_check()
    assert len(report.quarantine) == 2 and report.findings == []
    assert {q["why"].split(":")[0] for q in report.quarantine} == {
        "staging left by an interrupted write",
        "version above the head v1",
    }


# --------------------------------------------------------------------------- the command


@pytest.fixture
def actors(db: Any) -> None:
    sync.sync_auth()


def test_the_command_exits_by_what_it_found(store: LocalBackend, actors: None, capsys: Any) -> None:
    held = _hold("/c.txt", b"one")
    call_command("files", "check")
    assert "0 fault(s), 0 notice(s)" in capsys.readouterr().out
    add_file_version(held.identifier, 1, "c.txt", io.BytesIO(b"two"))
    call_command("files", "check")  # a notice alone exits zero
    with pytest.raises(SystemExit) as strict:
        call_command("files", "check", "--strict")
    assert strict.value.code == 1
    store.create(layout.urn(str(uuid.uuid4())), "o", io.BytesIO(b"o"), "t")
    with pytest.raises(SystemExit) as fault:
        call_command("files", "check")
    assert fault.value.code == 1 and "orphan_object" in capsys.readouterr().out


def test_the_command_says_when_the_store_is_off(settings: Any, actors: None) -> None:
    settings.TAP_FILES_ROOT = ""
    with pytest.raises(SystemExit) as off:
        call_command("files", "check")
    assert off.value.code == 2


@SPEC("req-tap-files-check-5")
def test_the_json_report_validates_against_its_schema(store: LocalBackend, actors: None, capsys: Any) -> None:
    schema = json.loads((Path(__file__).resolve().parents[2] / REPORT_SCHEMA).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    _seed_interrupted(store)
    held = _hold("/j.txt", b"one")
    add_file_version(held.identifier, 1, "j.txt", io.BytesIO(b"two"))
    with pytest.raises(SystemExit):
        call_command("files", "check", "--json")
    report = json.loads(capsys.readouterr().out)
    jsonschema.validate(report, schema)
    assert {f["severity"] for f in report["findings"]} == {"fault", "notice"}
    # Every kind the check can report is in the schema's vocabulary.
    import tap_files.check as check_module

    source = Path(check_module.__file__).read_text(encoding="utf-8")
    kinds = schema["properties"]["findings"]["items"]["properties"]["kind"]["enum"]
    assert all(f'"{kind}"' in source for kind in kinds)


# --------------------------------------------------------------------------- the health probe


@pytest.fixture
def mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    """A temporary directory shares /'s device; the seam the mount test's own tests use."""
    monkeypatch.setattr(volume_mount, "root_device", lambda: -1)


@SPEC("req-tap-files-health-4")
def test_not_enabled_is_healthy(settings: Any) -> None:
    settings.TAP_FILES_ROOT = ""
    result = health.probe_files()
    assert result.status is ProbeStatus.HEALTHY and result.context["enabled"] is False
    assert "not enabled" in result.context["note"]


@SPEC("req-tap-files-health-4")
def test_not_enabled_but_required_is_unhealthy(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files import boot

    settings.TAP_FILES_ROOT = ""
    monkeypatch.setattr(boot, "requiring_plugins", lambda: ["needs_files"])
    result = health.probe_files()
    assert result.status is ProbeStatus.UNHEALTHY and result.code == "files.required_not_enabled"
    assert "needs_files" in (result.detail or "")


@SPEC("req-tap-files-health-1")
def test_unmounted_is_unhealthy_with_the_reason(store: LocalBackend) -> None:
    result = health.probe_files()  # a temporary directory is on /'s device
    assert result.status is ProbeStatus.UNHEALTHY and result.code == "files.volume_unusable"
    assert (result.detail or "").startswith("not_mounted: ")


@SPEC("req-tap-files-health-2")
def test_a_missing_marker_is_unhealthy(store: LocalBackend, mounted: None) -> None:
    assert health.probe_files().status is ProbeStatus.HEALTHY
    (store.ocfl / inv.STORAGE_ROOT_MARKER).unlink()
    result = health.probe_files()
    assert result.status is ProbeStatus.UNHEALTHY and result.code == "files.root_invalid"


@SPEC("req-tap-files-health-3")
def test_quarantine_is_reported_not_failed(store: LocalBackend, mounted: None) -> None:
    _seed_interrupted(store)
    store.recover()
    result = health.probe_files()
    assert result.status is ProbeStatus.HEALTHY and result.context["quarantined"] == 2
    assert result.context["free_bytes"] > 0 and result.context["free_inodes"] > 0
    assert isinstance(result.context["filesystem"], str)


def test_the_probe_touches_no_database(store: LocalBackend, mounted: None, django_assert_num_queries: Any) -> None:
    with django_assert_num_queries(0):
        assert health.probe_files().status is ProbeStatus.HEALTHY


def test_the_probe_is_registered_in_readiness() -> None:
    from tap_health.registry import health_probe_registry
    from tap_health.selection import READINESS

    probe = health_probe_registry.get("files")
    assert probe is not None and READINESS in probe.sets and not probe.critical
