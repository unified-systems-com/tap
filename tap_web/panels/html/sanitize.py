"""Clean untrusted HTML against a closed, per-use allowlist (`req-web-panels-html-clean`). Django-free.

The markup is attacker-influenced wherever it came from, so it is never trusted and never stored cleaned: `clean` is run on every
render. What may pass is a closed vocabulary of named *features* (headings, lists, tables, links, images and so on), each a fixed
set of tags and attributes. A use of the cleaner (a `Policy`) selects features from that vocabulary; it can only narrow what the
vocabulary allows, never name a tag, attribute or scheme the vocabulary does not hold. There is no way to allow script, style,
forms, frames, SVG or MathML. The library is `nh3` (Rust `ammonia` on the `html5ever` parser); its output is then walked by a
second, independent parser (the standard library's) that must find nothing outside the policy, or the document is refused.

This file imports nothing from Django and nothing from any plugin, so another panel or a plugin can call `clean` on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

# ---- the vocabulary: the ceiling no policy can exceed -----------------------------------------------------------------------

#: feature -> (tags, {tag: attributes}). `text` is always on.
FEATURES: dict[str, tuple[frozenset[str], dict[str, frozenset[str]]]] = {
    "text": (frozenset({"p", "br", "strong", "em", "b", "i", "u", "s", "sub", "sup", "span", "div"}), {}),
    "headings": (frozenset({"h2", "h3", "h4"}), {}),
    "lists": (frozenset({"ul", "ol", "li", "dl", "dt", "dd"}), {}),
    "tables": (
        frozenset({"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption"}),
        {"th": frozenset({"colspan", "rowspan", "scope"}), "td": frozenset({"colspan", "rowspan"})},
    ),
    "code": (frozenset({"code", "pre", "kbd"}), {}),
    "quotes": (frozenset({"blockquote", "hr"}), {}),
    "figures": (frozenset({"figure", "figcaption"}), {}),
    "disclosure": (frozenset({"details", "summary"}), {}),
    "links": (frozenset({"a"}), {"a": frozenset({"href", "title"})}),
    "images": (frozenset({"img"}), {"img": frozenset({"src", "alt", "width", "height", "title"})}),
}
ALWAYS = "text"
DEFAULT_FEATURES = frozenset(FEATURES) - {"images"}  # an image is opt-in
CLASSES = frozenset(
    {
        "tap-html-lead",
        "tap-html-muted",
        "tap-html-callout",
        "tap-html-callout-note",
        "tap-html-callout-warning",
        "tap-html-columns",
        "tap-html-badge",
        "tap-html-figure",
        "tap-html-table",
        "tap-html-quote",
    }
)
SCHEMES = ("http", "https", "mailto")
GLOBAL_ATTRS = frozenset({"lang", "dir"})
#: Tags whose content is dropped along with the tag, not left behind as text.
DROP_CONTENT = frozenset(
    {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math", "select", "textarea", "title", "head",
     "frameset", "frame", "applet", "xmp", "plaintext", "noembed", "noframes", "audio", "video", "canvas", "form", "button"}
)  # fmt: skip
VOID = frozenset({"br", "hr", "img"})
LINK_REL = "noopener noreferrer nofollow"

MAX_BYTES_CEILING = 262_144
DEFAULT_MAX_BYTES = 65_536
DEFAULT_MAX_ELEMENTS = 2_000
DEFAULT_MAX_DEPTH = 20

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$")
PATH_PREFIX_RE = re.compile(r"^/[A-Za-z0-9._~/-]*$")
_LANG = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")
_DIGITS = re.compile(r"^[0-9]{1,4}$")


class HtmlError(Exception):
    """Base of the cleaner's refusals."""


class HtmlRefused(HtmlError):
    """The document is over a limit, or the cleaned output failed the second check."""


class CleanerUnavailable(HtmlError):
    """The sanitizer library cannot be imported: nothing is shown rather than anything uncleaned."""


@dataclass(frozen=True)
class Policy:
    """What one use of the cleaner allows. Built only through `from_config`, which holds it to the vocabulary."""

    features: frozenset[str] = DEFAULT_FEATURES
    classes: frozenset[str] = CLASSES
    link_schemes: frozenset[str] = frozenset(SCHEMES)
    link_hosts: frozenset[str] = frozenset()  # empty means any host
    image_prefixes: tuple[str, ...] = ("/static/",)
    max_bytes: int = DEFAULT_MAX_BYTES
    max_elements: int = DEFAULT_MAX_ELEMENTS
    max_depth: int = DEFAULT_MAX_DEPTH

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Policy:
        """A policy from a panel config; a name outside the vocabulary or a value past a ceiling raises `ValueError`."""
        features = config.get("features")
        chosen = DEFAULT_FEATURES if features is None else frozenset(features) | {ALWAYS}
        bad = sorted(chosen - set(FEATURES))
        if bad:
            raise ValueError(f"unknown feature {', '.join(bad)}")
        classes = CLASSES if config.get("classes") is None else frozenset(config["classes"])
        if classes - CLASSES:
            raise ValueError(f"unknown class {', '.join(sorted(classes - CLASSES))}")
        schemes = frozenset(SCHEMES) if config.get("link_schemes") is None else frozenset(config["link_schemes"])
        if schemes - set(SCHEMES):
            raise ValueError(f"unknown link scheme {', '.join(sorted(schemes - set(SCHEMES)))}")
        hosts = frozenset(h.lower() for h in config.get("link_hosts", ()))
        if any(not HOST_RE.match(h) for h in hosts):
            raise ValueError("link_hosts must be plain host names")
        prefixes = tuple(config.get("image_prefixes", ("/static/",)))
        if any(not PATH_PREFIX_RE.match(p) or ".." in p or p.startswith("//") for p in prefixes):
            raise ValueError("image_prefixes must be paths on this site")
        max_bytes = config.get("max_bytes", DEFAULT_MAX_BYTES)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= MAX_BYTES_CEILING:
            raise ValueError(f"max_bytes must be between 1 and {MAX_BYTES_CEILING}")
        return cls(chosen, classes, schemes, hosts, prefixes, max_bytes)

    # -- derived views, used by both the cleaner and the check ---------------------------------------------------------

    @property
    def tags(self) -> frozenset[str]:
        return frozenset().union(*(FEATURES[f][0] for f in self.features))

    @property
    def attributes(self) -> dict[str, frozenset[str]]:
        out: dict[str, set[str]] = {}
        for feature in self.features:
            for tag, attrs in FEATURES[feature][1].items():
                out.setdefault(tag, set()).update(attrs)
        generic = set(GLOBAL_ATTRS) | ({"class"} if self.classes else set())
        for tag in self.tags:
            out.setdefault(tag, set()).update(generic)
        return {tag: frozenset(attrs) for tag, attrs in out.items()}


@dataclass(frozen=True)
class Cleaned:
    html: str
    removed: int  # start tags in the input that the output does not have: a count, never content
    elements: int
    depth: int


# ---- value rules ------------------------------------------------------------------------------------------------------------


def _plain(value: str) -> bool:
    """No control character, space or backslash: a browser strips or reinterprets those inside a URL."""
    return all(ord(c) > 0x20 and ord(c) != 0x7F and c != "\\" for c in value)


def _site_path(value: str) -> bool:
    return value.startswith("/") and not value.startswith("//") and "/../" not in value + "/" and _plain(value)


def link_ok(value: str, policy: Policy) -> bool:
    if not value or not _plain(value) or len(value) > 2048:
        return False
    if value.startswith("#"):
        return len(value) > 1 and "#" not in value[1:]
    if value.startswith("/"):
        return _site_path(value)
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme not in policy.link_schemes:
        return False
    if scheme == "mailto":
        return bool(parts.path) and not parts.netloc
    host = (parts.hostname or "").lower()
    return bool(host) and parts.username is None and (not policy.link_hosts or host in policy.link_hosts)


def image_ok(value: str, policy: Policy) -> bool:
    return _site_path(value) and any(value.startswith(p) for p in policy.image_prefixes) and len(value) <= 2048


def attribute_value(tag: str, attr: str, value: str, policy: Policy) -> str | None:
    """The value to keep for an attribute that is on the allowlist, or None to drop it."""
    if attr == "rel" and tag == "a":
        return LINK_REL if value == LINK_REL else None
    if attr == "class":
        kept = [c for c in value.split() if c in policy.classes]
        return " ".join(dict.fromkeys(kept)) or None
    if attr == "href":
        return value if link_ok(value, policy) else None
    if attr == "src":
        return value if image_ok(value, policy) else None
    if attr in ("width", "height", "colspan", "rowspan"):
        return value if _DIGITS.match(value) else None
    if attr == "scope":
        return value if value in ("row", "col", "rowgroup", "colgroup") else None
    if attr == "lang":
        return value if _LANG.match(value) else None
    if attr == "dir":
        return value if value in ("ltr", "rtl", "auto") else None
    if attr in ("title", "alt"):
        return value[:300]
    return None


# ---- the second check -------------------------------------------------------------------------------------------------------


class _Walker(HTMLParser):
    """Walks cleaned output with the standard library's parser and records anything the policy does not allow."""

    def __init__(self, policy: Policy) -> None:
        super().__init__(convert_charrefs=True)
        self.policy = policy
        self.allowed = policy.attributes
        self.stack: list[str] = []
        self.elements = 0
        self.depth = 0
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements += 1
        if tag not in self.policy.tags:
            self.problems.append(f"tag {tag}")
            return
        for name, value in attrs:
            if name == "rel" and tag == "a":
                if value != LINK_REL:
                    self.problems.append("rel")
                continue
            if name not in self.allowed.get(tag, frozenset()) or value is None:
                self.problems.append(f"attribute {tag}.{name}")
            elif attribute_value(tag, name, value, self.policy) != value:
                self.problems.append(f"value {tag}.{name}")
        if tag == "a" and not any(n == "rel" for n, _ in attrs) and any(n == "href" for n, _ in attrs):
            self.problems.append("a without rel")
        if tag not in VOID:
            self.stack.append(tag)
            self.depth = max(self.depth, len(self.stack))

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.problems.append(f"unbalanced {tag}")
            return
        self.stack.pop()

    def handle_comment(self, data: str) -> None:
        self.problems.append("comment")

    def handle_decl(self, decl: str) -> None:
        self.problems.append("declaration")

    def handle_pi(self, data: str) -> None:
        self.problems.append("processing instruction")

    def unknown_decl(self, data: str) -> None:
        self.problems.append("declaration")


def audit(html: str, policy: Policy) -> tuple[int, int, list[str]]:
    """`(elements, depth, problems)` of ``html`` read by the standard library's parser."""
    walker = _Walker(policy)
    walker.feed(html)
    walker.close()
    if walker.stack:
        walker.problems.append("unclosed " + walker.stack[-1])
    return walker.elements, walker.depth, walker.problems


class _Counter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.starts = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.starts += 1


def _start_tags(html: str) -> int:
    counter = _Counter()
    counter.feed(html)
    counter.close()
    return counter.starts


# ---- the cleaner ------------------------------------------------------------------------------------------------------------


def clean(html: str, policy: Policy | None = None) -> Cleaned:
    """``html`` cleaned to ``policy``, or `HtmlRefused` / `CleanerUnavailable`; never the input back unchanged on a fault."""
    policy = policy or Policy()
    if not isinstance(html, str):
        raise HtmlRefused("not text")
    if len(html.encode("utf-8", "surrogatepass")) > policy.max_bytes:
        raise HtmlRefused("over the size limit")
    try:
        import nh3
    except ImportError as exc:  # pragma: no cover - exercised by a test that blocks the import
        raise CleanerUnavailable("the HTML cleaner is not installed") from exc

    allowed = policy.attributes
    out = nh3.clean(
        html,
        tags=set(policy.tags),
        clean_content_tags=set(DROP_CONTENT),
        attributes={tag: set(attrs - {"rel"}) for tag, attrs in allowed.items()},
        attribute_filter=lambda tag, attr, value: attribute_value(tag, attr, value, policy),
        strip_comments=True,
        link_rel=LINK_REL,
        url_schemes=set(policy.link_schemes),
    )
    elements, depth, problems = audit(out, policy)
    if problems:
        raise HtmlRefused("the cleaned output failed the second check: " + problems[0])
    if elements > policy.max_elements:
        raise HtmlRefused("over the element limit")
    if depth > policy.max_depth:
        raise HtmlRefused("over the depth limit")
    return Cleaned(out, max(0, _start_tags(html) - elements), elements, depth)
