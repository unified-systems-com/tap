"""The HTML cleaner (`req-web-panels-html-clean`). Needs only `nh3` and the standard library.

The vectors are selected from the OWASP XSS Filter Evasion Cheat Sheet, the mutation-XSS payloads published against HTML
sanitizers (nested `noscript`, `style`, `select`, `svg` and `math` breakouts) and DOM-clobbering and tabnabbing cases. The check
of every output uses a parser written for this test, not the cleaner's own."""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from tap_web.panels.html import sanitize as h

SPEC = Path(__file__).resolve().parents[1] / "specs" / "spec-web-panels-html.md"

VECTORS = [
    "<script>alert(1)</script>",
    "<SCRIPT SRC=http://evil/x.js></SCRIPT>",
    "<scr<script>ipt>alert(1)</scr</script>ipt>",
    "<img src=x onerror=alert(1)>",
    "<img src=javascript:alert(1)>",
    "<IMG SRC=&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;&#58;alert(1)>",
    "<img src=\"jav&#x09;ascript:alert(1)\">",
    "<a href=\"javascript:alert(1)\">x</a>",
    "<a href=\" javascript:alert(1)\">x</a>",
    "<a href=\"java\nscript:alert(1)\">x</a>",
    "<a href=\"JaVaScRiPt:alert(1)\">x</a>",
    "<a href=\"vbscript:msgbox(1)\">x</a>",
    "<a href=\"data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==\">x</a>",
    "<a href=\"//evil.example/x\">x</a>",
    "<a href=\"\\\\evil.example\\x\">x</a>",
    "<a href=\"https://user:pass@evil.example/\">x</a>",
    "<body onload=alert(1)>",
    "<svg onload=alert(1)>",
    "<svg><script>alert(1)</script></svg>",
    "<svg><animate onbegin=alert(1) attributeName=x dur=1s>",
    "<svg><a><animate attributeName=href values=javascript:alert(1) /><text>x</text></a></svg>",
    "<math><mi xlink:href=\"javascript:alert(1)\">x</mi></math>",
    "<math><annotation-xml encoding=\"text/html\"><img src=x onerror=alert(1)></annotation-xml></math>",
    "<iframe src=javascript:alert(1)></iframe>",
    "<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
    "<object data=javascript:alert(1)></object>",
    "<embed src=javascript:alert(1)>",
    "<form action=https://evil.example><input name=x><button>go</button></form>",
    "<input autofocus onfocus=alert(1)>",
    "<meta http-equiv=refresh content=\"0;url=https://evil.example\">",
    "<base href=https://evil.example/>",
    "<link rel=stylesheet href=https://evil.example/x.css>",
    "<style>@import 'https://evil.example/x.css'; body{display:none}</style>",
    "<div style=\"position:fixed;inset:0;background:url(https://evil.example/x)\">x</div>",
    "<p style=\"background-image:url(javascript:alert(1))\">x</p>",
    "<video><source onerror=alert(1)></video>",
    "<audio src=x onerror=alert(1)>",
    "<details open ontoggle=alert(1)>x</details>",
    "<marquee onstart=alert(1)>x</marquee>",
    "<noscript><p title=\"</noscript><img src=x onerror=alert(1)>\"></noscript>",
    "<style><style/><img src=x onerror=alert(1)>",
    "<select><template><style></select><img src=x onerror=alert(1)>",
    "<textarea><img src=x onerror=alert(1)></textarea>",
    "<title><img src=x onerror=alert(1)></title>",
    "<xmp><img src=x onerror=alert(1)></xmp>",
    "<table><td><svg></p><style><a id=\"</style><img src=x onerror=alert(1)>\">",
    "<a id=location name=cookie>x</a>",
    "<form id=x><input name=attributes></form>",
    "<a href=\"https://ok.example/\" target=_blank>x</a>",
    "<a href=\"https://ok.example/\" rel=opener>x</a>",
    "<p class=\"tap-html-lead\" id=a name=b form=c onclick=1 style=2 data-x=3>x</p>",
    "<!--[if IE]><script>alert(1)</script><![endif]-->",
    "<![CDATA[<script>alert(1)</script>]]>",
    "<?php echo 1; ?>",
    "<!DOCTYPE html><html><head><title>x</title></head><body>y</body></html>",
    "<img src=\"/static/ok.png\" onerror=alert(1) srcset=\"https://evil.example/x.png 1x\">",
    "<img src=\"/static/../../etc/passwd\">",
    "<p>" + "<b>" * 100 + "x",
    "\x00<script>alert(1)</script>",
    "<scr\x00ipt>alert(1)</scr\x00ipt>",
    "<<script>alert(1)//<</script>",
    "<img src=\"x\" alt=\"\"onerror=alert(1) \">",
    "<a href=\"mailto:a@b.example?subject=x\">x</a>",
]
EVERY_FEATURE = h.Policy.from_config({"features": list(h.FEATURES)})


class _Independent(HTMLParser):
    """A separate walker for the test: fails on anything outside the policy, written without the cleaner's helpers."""

    def __init__(self, tags: set[str], attrs: dict[str, set[str]]) -> None:
        super().__init__()
        self.tags, self.attrs, self.bad = tags, attrs, []

    def handle_starttag(self, tag, attrs):  # type: ignore[no-untyped-def]
        if tag not in self.tags:
            self.bad.append(tag)
        for name, value in attrs:
            if name not in self.attrs.get(tag, set()) | {"rel"}:
                self.bad.append(f"{tag}.{name}")
            if name in ("href", "src") and value:
                low = re.sub(r"[\s\x00-\x20]", "", value.lower())
                if low.startswith(("javascript:", "vbscript:", "data:", "//", "\\")) or "javascript:" in low:
                    self.bad.append(f"{tag}.{name}={value}")
            if name == "rel" and "noopener" not in (value or ""):
                self.bad.append("rel")

    def handle_comment(self, data):  # type: ignore[no-untyped-def]
        self.bad.append("comment")


def independent_problems(out: str, policy: h.Policy) -> list[str]:
    walker = _Independent(set(policy.tags), {t: set(a) for t, a in policy.attributes.items()})
    walker.feed(out)
    return walker.bad


@pytest.mark.spec("req-web-panels-html-clean-1")
@pytest.mark.spec("req-web-panels-html-clean-2")
@pytest.mark.parametrize("vector", VECTORS)
def test_every_vector_comes_out_inside_the_allowlist(vector: str) -> None:
    try:
        out = h.clean(vector, EVERY_FEATURE).html
    except h.HtmlRefused:
        return  # refusing a document is also safe
    assert independent_problems(out, EVERY_FEATURE) == [], (vector, out)
    low = out.lower()
    for forbidden in ("<script", "<svg", "<math", "<iframe", "<style", "<form", "<input", "<meta", "<base", "<link", " on", "javascript:", "style=", " id=", " name=", "srcset"):
        assert forbidden not in low or forbidden == " on" and not re.search(r"\son\w+\s*=", low), (vector, out)


@pytest.mark.spec("req-web-panels-html-clean-3")
@pytest.mark.parametrize("vector", VECTORS)
def test_cleaning_is_idempotent(vector: str) -> None:
    try:
        once = h.clean(vector, EVERY_FEATURE).html
    except h.HtmlRefused:
        return
    assert h.clean(once, EVERY_FEATURE).html == once, vector


@pytest.mark.spec("req-web-panels-html-clean-4")
def test_nothing_is_fetched_from_elsewhere() -> None:
    out = h.clean(
        '<img src="https://evil.example/p.png"><img src="/static/ok.png"><a href="https://ok.example/" ping="https://evil.example">x</a>'
        '<link href="https://evil.example"><p style="background:url(https://evil.example)">y</p>',
        h.Policy.from_config({"features": ["images", "links"]}),
    ).html
    assert 'src="/static/ok.png"' in out and "evil.example/p.png" not in out
    assert "ping" not in out and "<link" not in out and "style" not in out


@pytest.mark.spec("req-web-panels-html-clean-5")
def test_links_are_safe() -> None:
    out = h.clean('<a href="https://ok.example/" target="_blank" rel="opener">x</a><a href="/local">y</a>', EVERY_FEATURE).html
    assert out.count('rel="noopener noreferrer nofollow"') == 2 and "target" not in out and "opener\"" not in out.replace("noopener", "")


@pytest.mark.spec("req-web-panels-html-clean-6")
def test_no_names() -> None:
    out = h.clean('<p id="a" name="b" form="c">x</p><a id="d" href="/x">y</a>', EVERY_FEATURE).html
    assert not re.search(r"\s(id|name|form)=", out)


@pytest.mark.spec("req-web-panels-html-clean-7")
def test_only_the_listed_classes_survive_and_the_element_stays() -> None:
    out = h.clean('<p class="tap-html-lead evil tap-html-muted">x</p><p class="evil">y</p>', EVERY_FEATURE).html
    assert out == '<p class="tap-html-lead tap-html-muted">x</p><p>y</p>'


@pytest.mark.spec("req-web-panels-html-clean-8")
def test_limits_refuse() -> None:
    with pytest.raises(h.HtmlRefused, match="size"):
        h.clean("x" * 20, h.Policy.from_config({"max_bytes": 10}))
    with pytest.raises(h.HtmlRefused, match="depth"):
        h.clean("<div>" * (h.DEFAULT_MAX_DEPTH + 5) + "x", EVERY_FEATURE)
    with pytest.raises(h.HtmlRefused, match="element"):
        h.clean("<b>x</b>" * (h.DEFAULT_MAX_ELEMENTS + 1), EVERY_FEATURE)
    with pytest.raises(h.HtmlRefused):
        h.clean(b"<p>x</p>", EVERY_FEATURE)  # type: ignore[arg-type]


@pytest.mark.spec("req-web-panels-html-render-2")
def test_the_library_missing_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "nh3", None)
    with pytest.raises(h.CleanerUnavailable):
        h.clean("<p>x</p>", EVERY_FEATURE)


@pytest.mark.spec("req-web-panels-html-render-2")
def test_a_failed_second_check_refuses_the_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the library ever returned something outside the policy the independent walk must stop it."""
    import nh3

    monkeypatch.setattr(nh3, "clean", lambda html, **kw: '<p onclick="x">hi</p><script>x</script>')
    with pytest.raises(h.HtmlRefused, match="second check"):
        h.clean("<p>hi</p>", EVERY_FEATURE)


class TestFeatures:
    """Per panel, a use of the cleaner selects features from the closed vocabulary and can only narrow it."""

    @pytest.mark.spec("req-web-panels-html-clean-11")
    def test_a_feature_that_is_off_is_stripped_but_its_text_stays(self) -> None:
        p = h.Policy.from_config({"features": ["lists"]})
        out = h.clean("<h2>head</h2><ul><li>a</li></ul><table><tr><td>t</td></tr></table><a href='/x'>l</a>", p).html
        assert "<h2>" not in out and "<ul><li>a</li></ul>" in out and "<table" not in out and "<a" not in out
        assert "head" in out and "t" in out and "l" in out

    @pytest.mark.spec("req-web-panels-html-clean-11")
    def test_images_are_off_by_default_and_prefixes_narrow_them(self) -> None:
        src = '<img src="/static/a.png"><img src="/media/b.png">'
        assert "<img" not in h.clean(src, h.Policy()).html
        on = h.Policy.from_config({"features": ["images"], "image_prefixes": ["/media/"]})
        assert h.clean(src, on).html.count("<img") == 2 and h.clean(src, on).html.count("src=") == 1

    @pytest.mark.spec("req-web-panels-html-clean-11")
    def test_link_schemes_and_hosts_narrow_links(self) -> None:
        src = '<a href="https://a.example/x">1</a><a href="https://b.example/x">2</a><a href="http://a.example/">3</a><a href="mailto:x@y.example">4</a><a href="/p">5</a>'
        p = h.Policy.from_config({"link_schemes": ["https"], "link_hosts": ["a.example"]})
        out = h.clean(src, p).html
        assert out.count("href=") == 2 and "https://a.example/x" in out and 'href="/p"' in out

    @pytest.mark.spec("req-web-panels-html-clean-11")
    def test_classes_narrow(self) -> None:
        out = h.clean('<p class="tap-html-lead tap-html-muted">x</p>', h.Policy.from_config({"classes": ["tap-html-muted"]})).html
        assert out == '<p class="tap-html-muted">x</p>'
        assert "class" not in h.clean('<p class="tap-html-lead">x</p>', h.Policy.from_config({"classes": []})).html

    @pytest.mark.spec("req-web-panels-html-clean-11")
    @pytest.mark.parametrize(
        "config",
        [
            {"features": ["script"]},
            {"features": ["style"]},
            {"features": ["svg"]},
            {"classes": ["evil"]},
            {"link_schemes": ["javascript"]},
            {"link_hosts": ["evil.example/path"]},
            {"image_prefixes": ["//evil.example/"]},
            {"image_prefixes": ["/static/../"]},
            {"max_bytes": h.MAX_BYTES_CEILING + 1},
            {"max_bytes": 0},
        ],
    )
    def test_a_policy_cannot_name_anything_outside_the_vocabulary(self, config: dict) -> None:
        with pytest.raises(ValueError):  # noqa: PT011
            h.Policy.from_config(config)

    @pytest.mark.spec("req-web-panels-html-clean-11")
    def test_no_policy_can_reach_a_forbidden_tag(self) -> None:
        union = set().union(*(tags for tags, _ in h.FEATURES.values()))
        assert not union & {"script", "style", "iframe", "object", "embed", "form", "input", "button", "svg", "math", "link", "meta", "base", "video", "audio", "template"}
        every = set(h.Policy.from_config({"features": list(h.FEATURES)}).attributes.values().__iter__().__next__())
        allattrs = set().union(*h.Policy.from_config({"features": list(h.FEATURES)}).attributes.values())
        assert not allattrs & {"style", "id", "name", "form", "target", "onclick", "srcset", "ping", "formaction"} and every


@pytest.mark.spec("req-web-panels-html-clean-10")
def test_the_configured_allowlist_is_the_one_in_the_spec() -> None:
    """A library default or a code edit cannot widen the allowlist without the spec changing with it."""
    text = SPEC.read_text(encoding="utf-8")
    section = text.split("#### Features", 1)[1].split("####", 1)[0]
    documented: dict[str, tuple[set[str], dict[str, set[str]]]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`") and cells[0] != "`feature`":
            tags = set(re.findall(r"`([a-z0-9]+)`", cells[1]))
            attrs: dict[str, set[str]] = {}
            for part in filter(None, (x.strip() for x in cells[2].split(";"))):
                tag, names = part.split(":")
                attrs[tag.strip(" `")] = set(re.findall(r"`([a-z]+)`", names))
            documented[cells[0].strip("`")] = (tags, attrs)
    assert set(documented) == set(h.FEATURES)
    for name, (tags, attrs) in h.FEATURES.items():
        assert (set(tags), {t: set(a) for t, a in attrs.items()}) == documented[name], name
    for cls in h.CLASSES:
        assert f"`{cls}`" in text
