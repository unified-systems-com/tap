"""The site glyph (req-web-chrome-branding-glyph*, req-boot-web-branding-6/7): sanitiser, fallback, name order."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from django.test import override_settings

from tap_web import branding
from tap_web.branding import UnsafeGlyphError, sanitize_svg
from tap_web.context_processors import branding as branding_context

NS = 'xmlns="http://www.w3.org/2000/svg"'
GOOD = f'<svg {NS} viewBox="0 0 10 10"><rect width="10" height="10" fill="#f1f0ec"/><path d="M0 0L5 5" fill="#1c2328"/></svg>'


def _svg(inner: str, root_attrs: str = "") -> str:
    return f'<svg {NS} viewBox="0 0 10 10" {root_attrs}>{inner}</svg>'


@pytest.mark.spec("req-web-chrome-branding-glyph")
def test_good_svg_gets_role_label_and_class():
    out = sanitize_svg(GOOD, label='RAMP"ART')
    assert 'role="img"' in out and 'aria-label="RAMP&quot;ART"' in out and "tap-brand-glyph" in out
    assert "#f1f0ec" in out and "<path" in out


@pytest.mark.spec("req-web-chrome-branding-glyph")
@pytest.mark.parametrize(
    "bad",
    [
        _svg("<script>alert(1)</script>"),
        _svg('<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject>'),
        _svg("<style>rect{fill:red}</style>"),
        _svg('<rect width="1" height="1" onload="alert(1)"/>'),
        _svg("<rect/>", 'onclick="x()"'),
        _svg('<a href="http://evil.example/"><rect/></a>'),
        _svg('<path d="M0 0" href="http://evil.example/x"/>'),
        _svg('<image href="data:image/png;base64,AAAA"/>'),
        _svg('<use href="#a"/>'),
        _svg('<rect fill="url(http://evil.example/x#f)"/>'),
        _svg('<rect style="background:url(https://evil.example/x)"/>'),
        _svg('<rect fill="javascript:alert(1)"/>'),
        _svg('<rect xlink:href="http://evil.example" xmlns:xlink="http://www.w3.org/1999/xlink"/>'),
        '<!DOCTYPE svg [<!ENTITY a "aaaa">]>' + _svg("<rect/>"),
        '<?xml version="1.0"?><!DOCTYPE svg SYSTEM "http://evil.example/x.dtd">' + _svg("<rect/>"),
        "<svg",  # not well-formed
        '<html xmlns="http://www.w3.org/1999/xhtml"/>',  # wrong root
        '<svg xmlns="http://evil.example/ns"/>',  # wrong namespace
    ],
)
def test_adversarial_svg_is_refused(bad):
    with pytest.raises(UnsafeGlyphError):
        sanitize_svg(bad, label="X")


@pytest.mark.spec("req-web-chrome-branding-glyph")
def test_comments_are_dropped_not_inlined():
    assert "secret" not in sanitize_svg(_svg("<!-- secret --><rect/>"), label="X")


@pytest.mark.spec("req-web-chrome-branding-glyph")
def test_local_fragment_references_survive():
    out = sanitize_svg(_svg('<defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs><rect fill="url(#g)"/>'), label="X")
    assert "url(#g)" in out


def _point(monkeypatch, tmp_path: Path, text: str) -> None:
    f = tmp_path / "g.svg"
    f.write_text(text)
    monkeypatch.setattr(branding, "_glyph_file", lambda _plugin, _path: f)
    monkeypatch.setattr(branding, "_slot", None)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key in ("NAME", "GLYPH_PLUGIN", "GLYPH_PATH"):
        monkeypatch.delenv(f"TAP_BOOT_WEB__BRANDING__{key}", raising=False)
    monkeypatch.delenv("TAP_BOOT_PROFILE", raising=False)
    monkeypatch.setattr(branding, "_slot", None)


@pytest.mark.spec("req-web-chrome-branding-glyph-favicon")
def test_env_glyph_renders_inline_and_feeds_the_favicon(monkeypatch, tmp_path):
    _point(monkeypatch, tmp_path, GOOD)
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "rampart_20x")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/rampart-rook.svg")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "RAMPART")
    ctx = branding_context(None)
    assert 'aria-label="RAMPART"' in ctx["brand_glyph"]
    assert ctx["brand_glyph_static"] == "rampart_20x/icons/rampart-rook.svg"
    assert ctx["product_name"] == "RAMPART"
    base = (Path(__file__).resolve().parents[1] / "templates/tap_web/base.html").read_text(encoding="utf-8")
    assert 'type="image/svg+xml" href="{% static brand_glyph_static %}"' in base
    assert "tap_web/favicon.ico" in base  # the unchanged fallback


@pytest.mark.spec("req-web-chrome-branding-glyph-fallback")
@pytest.mark.spec("req-boot-web-branding-6")
@pytest.mark.parametrize(
    "setup",
    ["unsafe", "bad_path", "missing_plugin"],
)
def test_unusable_glyph_falls_back_to_text_with_a_warning(setup, monkeypatch, tmp_path, caplog):
    if setup == "unsafe":
        _point(monkeypatch, tmp_path, _svg("<script>1</script>"))
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/x.svg")
    elif setup == "bad_path":
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "../../etc/passwd.svg")
    else:
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/x.svg")
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "no_such_plugin")
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "TEXTNAME")
    if setup != "missing_plugin":
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "rampart_20x")
    with caplog.at_level(logging.WARNING, logger="tap_web.branding"):
        ctx = branding_context(None)
    assert ctx["brand_glyph"] is None and ctx["brand_glyph_static"] is None
    assert ctx["product_name"]  # the text name still renders
    assert "site glyph unusable" in caplog.text


@pytest.mark.spec("req-boot-web-branding-7")
def test_name_precedence(monkeypatch):
    with override_settings(TAP_PRODUCT_NAME="FROMSETTING"):
        assert branding_context(None)["product_name"] == "FROMSETTING"  # TAP_PRODUCT_NAME beats TAP
        monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "FROMENV")
        assert branding_context(None)["product_name"] == "FROMENV"  # branding env beats it
    with override_settings(TAP_PRODUCT_NAME=""):
        monkeypatch.delenv("TAP_BOOT_WEB__BRANDING__NAME")
        assert branding_context(None)["product_name"] == "TAP"


@pytest.mark.spec("req-boot-web-branding-7")
def test_profile_name_beats_product_name_env_setting(monkeypatch, tmp_path):
    p = tmp_path / "pn.boot.json"
    p.write_text('{"web": {"branding": {"name": "PROFILENAME"}}}')
    monkeypatch.setattr("tap_web.boot._profile_path", lambda _pid: p)
    monkeypatch.setattr("tap_web.branding._profile_path", lambda _pid: p)
    monkeypatch.setenv("TAP_BOOT_PROFILE", "pn")
    with override_settings(TAP_PRODUCT_NAME="FROMSETTING"):
        assert branding_context(None)["product_name"] == "PROFILENAME"


@pytest.mark.django_db
@pytest.mark.spec("req-web-chrome-branding-glyph")
@pytest.mark.spec("req-web-chrome-branding-glyph-favicon")
def test_header_renders_the_glyph_and_svg_favicon(monkeypatch, tmp_path):
    from tap_web.tests.test_navigation import _auth_client, _create_page

    _point(monkeypatch, tmp_path, GOOD)
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "rampart_20x")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/rampart-rook.svg")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "RAMPART")
    _create_page("Samsite", "/samsite")
    body = _auth_client().get("/samsite").content.decode()
    assert '<svg xmlns="http://www.w3.org/2000/svg"' in body and 'role="img" aria-label="RAMPART"' in body
    assert 'rel="icon" type="image/svg+xml" href="/static/rampart_20x/icons/rampart-rook.svg"' in body
    assert "favicon.ico" not in body
    assert "RAMPART</a>" not in body  # the glyph replaces the text mark


@pytest.mark.django_db
@pytest.mark.spec("req-web-chrome-branding-glyph-fallback")
def test_header_falls_back_to_the_text_name_and_default_favicon(monkeypatch):
    from tap_web.tests.test_navigation import _auth_client, _create_page

    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PLUGIN", "no_such_plugin")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__GLYPH_PATH", "icons/x.svg")
    monkeypatch.setenv("TAP_BOOT_WEB__BRANDING__NAME", "TEXTNAME")
    _create_page("Samsite", "/samsite")
    body = _auth_client().get("/samsite").content.decode()
    assert ">TEXTNAME<" in body and "tap-brand-glyph" not in body
    assert "favicon.ico" in body
