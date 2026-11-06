"""The boot profile's `web.branding` block (req-boot-web-branding): schema, ladder, settings-free reader, warn-only check."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from tap_boot.orchestrator import _phase_web
from tap_boot.profile import BootProfileError, load_profile
from tap_boot.record import NullBootRecord
from tap_web.boot import branding_for_profile, branding_from_section, glyph_pointer_problem

_ENV = ("NAME", "GLYPH_PLUGIN", "GLYPH_PATH")
_BLOCK = {"name": "RAMPART", "glyph": {"plugin": "rampart_20x", "path": "icons/rampart-rook.svg"}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(f"TAP_BOOT_WEB__BRANDING__{key}", raising=False)


@pytest.fixture
def boot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("tap_boot.profile.boot_dir", lambda: tmp_path)
    return tmp_path


def _write(boot_dir, profile_id: str, web: dict[str, Any]) -> None:
    (boot_dir / f"{profile_id}.boot.json").write_text(json.dumps({"version": 1, "web": web, "population": {"steps": []}}))


@pytest.mark.spec("req-boot-web-branding-1")
def test_schema_accepts_the_block(boot_dir):
    _write(boot_dir, "p", {"branding": _BLOCK})
    assert load_profile("p").web == {"branding": _BLOCK}
    _write(boot_dir, "q", {"branding": {"name": "X"}})  # glyph is optional
    assert load_profile("q").web == {"branding": {"name": "X"}}


@pytest.mark.spec("req-boot-web-branding-1")
@pytest.mark.parametrize(
    "block",
    [
        {"name": "X", "bogus": 1},
        {"name": "X", "glyph": {"plugin": "rampart_20x"}},  # plugin + path required together
        {"name": "X", "glyph": {"path": "a.svg"}},
        {"name": "X", "glyph": {"plugin": "p", "path": "a.svg", "extra": 1}},
        {"name": ""},
    ],
)
def test_schema_rejects_malformed_block(boot_dir, block):
    _write(boot_dir, "bad", {"branding": block})
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")


@pytest.mark.spec("req-boot-web-branding-3")
@pytest.mark.parametrize(
    "path",
    ["https://evil.example/a.svg", "//evil.example/a.svg", "/etc/a.svg", "../a.svg", "a/../b.svg", "a\\b.svg", "a.png", "C:/a.svg"],
)
def test_glyph_must_be_a_plugin_pointer(boot_dir, path):
    # rejected by the schema at load time AND by the runtime check (defence in depth)
    _write(boot_dir, "bad", {"branding": {"name": "X", "glyph": {"plugin": "p", "path": path}}})
    with pytest.raises(BootProfileError, match="schema validation"):
        load_profile("bad")
    assert glyph_pointer_problem("p", path)


@pytest.mark.spec("req-boot-web-branding-3")
def test_glyph_pointer_accepts_nested_relative_svg_and_rejects_bad_slug():
    assert glyph_pointer_problem("rampart_20x", "icons/rampart-rook.svg") is None
    assert glyph_pointer_problem("../x", "a.svg")
    assert glyph_pointer_problem("Plugin", "a.svg")


@pytest.mark.spec("req-boot-web-branding-4")
def test_env_beats_profile_with_provenance_and_empty_counts_as_absent(monkeypatch):
    assert branding_from_section(None)["name"] is None
    base = branding_from_section({"branding": _BLOCK})
    assert (base["name"], base["glyph_plugin"], base["glyph_path"]) == ("RAMPART", "rampart_20x", "icons/rampart-rook.svg")
    assert set(base["source"].values()) == {"profile"}
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "OTHER")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/other.svg")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "")  # empty = absent -> profile
    over = branding_from_section({"branding": _BLOCK})
    assert (over["name"], over["glyph_plugin"], over["glyph_path"]) == ("OTHER", "rampart_20x", "icons/other.svg")
    assert over["source"] == {"name": "env", "glyph_plugin": "profile", "glyph_path": "env"}


@pytest.mark.spec("req-boot-web-branding-5")
def test_reader_is_tolerant_of_a_bad_file(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("tap_web.boot._profile_path", lambda _pid: tmp_path / "broken.boot.json")
    (tmp_path / "broken.boot.json").write_text("{not json")
    with caplog.at_level(logging.WARNING):
        out = branding_for_profile("broken")
    assert out["name"] is None and out["glyph_plugin"] is None
    assert "could not read web section" in caplog.text


@pytest.mark.spec("req-boot-web-branding-6")
def test_unusable_glyph_warns_and_the_phase_still_completes(caplog):
    class _Profile:
        web = {"branding": {"name": "X", "glyph": {"plugin": "no_such_plugin", "path": "icons/a.svg"}}}

    lines: list[str] = []
    with caplog.at_level(logging.WARNING):
        _phase_web(_Profile(), lines.append, NullBootRecord())  # type: ignore[arg-type]  # no landing declared: returns, never raises
    assert "no_such_plugin" in caplog.text and "icons/a.svg" in caplog.text
    assert any("unusable" in line for line in lines)
