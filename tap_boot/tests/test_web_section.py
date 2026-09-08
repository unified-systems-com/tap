"""The boot profile's `web` section (req-boot-web-section): schema, settings-free reading, verification."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tap_boot.orchestrator import BootError, _phase_web
from tap_boot.profile import BootProfile, BootProfileError, load_profile
from tap_boot.record import NullBootRecord
from tap_web.boot import landing_from_section, read_web_section

_PAIR = {"landing_entity_id": "01a03f78-11fa-7029-823d-794a7b1f0350", "landing_slug": "/git-serious"}


def _write(boot_dir, profile_id: str, data: dict[str, object]) -> None:
    (boot_dir / f"{profile_id}.boot.json").write_text(json.dumps(data))


@pytest.fixture
def boot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("tap_boot.profile.boot_dir", lambda: tmp_path)
    return tmp_path


@pytest.mark.spec("req-boot-web-section-1")
def test_schema_accepts_the_pair_and_profile_carries_it(boot_dir):
    _write(boot_dir, "p", {"version": 1, "web": _PAIR, "population": {"steps": []}})
    assert load_profile("p").web == _PAIR


@pytest.mark.parametrize(
    "web",
    [
        {"landing_entity_id": _PAIR["landing_entity_id"]},  # lone id: dependentRequired
        {"landing_slug": "/git-serious"},  # lone slug
        {**_PAIR, "bogus": 1},  # unknown key
        {"landing_entity_id": "not-a-uuid", "landing_slug": "/x"},  # shape
        {"landing_entity_id": _PAIR["landing_entity_id"], "landing_slug": "no-slash"},  # shape
    ],
)
def test_schema_rejects_malformed_web_section(boot_dir, web):
    _write(boot_dir, "bad", {"version": 1, "web": web, "population": {"steps": []}})
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")


@pytest.mark.spec("req-boot-web-section-3")
def test_landing_from_section_provenance_and_env_override(monkeypatch):
    monkeypatch.delenv("TAP_BOOT_WEB__LANDING_ENTITY_ID", raising=False)
    monkeypatch.delenv("TAP_BOOT_WEB__LANDING_SLUG", raising=False)
    assert landing_from_section(None) is None
    assert landing_from_section({}) is None
    resolved = landing_from_section(_PAIR)
    assert resolved == {
        "entity_id": _PAIR["landing_entity_id"],
        "slug": "/git-serious",
        "source": {"entity_id": "profile", "slug": "profile"},
    }
    monkeypatch.setenv("TAP_BOOT_WEB__LANDING_SLUG", "/from-env")
    resolved = landing_from_section(_PAIR)
    assert resolved is not None
    assert resolved["slug"] == "/from-env" and resolved["source"] == {"entity_id": "profile", "slug": "env"}
    monkeypatch.setenv("TAP_BOOT_WEB__LANDING_SLUG", "   ")  # empty string counts as absent
    resolved = landing_from_section(_PAIR)
    assert resolved is not None and resolved["source"]["slug"] == "profile"


@pytest.mark.spec("req-boot-web-section-2")
def test_read_web_section_is_tolerant(tmp_path, monkeypatch):
    monkeypatch.setattr("tap_web.boot._profile_path", lambda pid: tmp_path / f"{pid}.boot.json")
    assert read_web_section("") == {}
    assert read_web_section("absent") == {}
    (tmp_path / "broken.boot.json").write_text("{not json")
    assert read_web_section("broken") == {}
    (tmp_path / "ok.boot.json").write_text(json.dumps({"version": 1, "web": _PAIR}))
    assert read_web_section("ok") == _PAIR


def _profile(web: dict[str, Any] | None) -> BootProfile:
    return BootProfile(profile_id="t", version=1, description="", on_failure="abort", steps=(), web=web)


@pytest.mark.django_db
class TestPhaseWeb:
    def test_undeclared_logs_and_continues(self, monkeypatch):
        monkeypatch.delenv("TAP_BOOT_WEB__LANDING_ENTITY_ID", raising=False)
        monkeypatch.delenv("TAP_BOOT_WEB__LANDING_SLUG", raising=False)
        said: list[str] = []
        _phase_web(_profile(None), said.append, NullBootRecord())
        _phase_web(None, said.append, NullBootRecord())
        assert all("not declared" in line for line in said) and len(said) == 2

    @pytest.mark.spec("req-boot-web-section-4")
    def test_wrong_declaration_aborts_naming_values(self):
        missing = str(uuid.uuid4())
        with pytest.raises(BootError, match="web.landing does not resolve") as excinfo:
            _phase_web(
                _profile({"landing_entity_id": missing, "landing_slug": "/nowhere"}), lambda _: None, NullBootRecord()
            )
        assert missing in str(excinfo.value) and "/nowhere" in str(excinfo.value)
        assert excinfo.value.detail["state"] == "missing"

    def test_ok_records_both_variables_with_provenance(self):
        from tap_web.models import Page

        page = Page(
            slug="/phase-web-ok",
            name="ok",
            layout={"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "main"}}}}},
        )
        page.save()
        recorded: list[tuple[str, str, Any, str]] = []

        class Rec(NullBootRecord):
            def record_variable(self, section, key, value, source):
                recorded.append((section, key, value, source))

        said: list[str] = []
        _phase_web(
            _profile({"landing_entity_id": str(page.entity_id), "landing_slug": "/phase-web-ok"}), said.append, Rec()
        )
        assert ("web", "landing_entity_id", str(page.entity_id), "profile") in recorded
        assert ("web", "landing_slug", "/phase-web-ok", "profile") in recorded
        assert said and "/phase-web-ok" in said[0]
