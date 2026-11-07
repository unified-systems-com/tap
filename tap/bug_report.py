"""The mechanics behind the `submit-a-bug` and `submit-a-fix` skills (specs/spec-dev-bug-reporting.md).

Two skills, one module. `submit-a-bug` runs in a reporter's install and writes a report;
`submit-a-fix` reads one. Everything that has to be exact lives here so it can be tested rather
than trusted to a prompt: the report schema both skills share (`tap/skills/bug-report.schema.json`),
the renderer and the reader that round-trip through it, the tripwire, the consent binding, the
author gate, and the sanitising intake.

Version 0 (George, 2026-10-25): reports carry no dataset and no value from the reporter's instance,
and `submit-a-fix` runs only on an issue a maintainer session account wrote. The sandbox and the
synthetic dataset are Backlog and deliberately absent.

Stdlib plus `jsonschema` (already a core dependency). Run it in the container:
`scripts/bug-report <subcommand>` wraps `python -m tap.bug_report`.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import json
import re
import socket
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from tap.credential_patterns import CREDENTIAL_PATTERNS

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "tap" / "skills" / "bug-report.schema.json"
SESSION_IDENTITY_PATH = REPO_ROOT / "scripts" / "pr_session_identity.py"
#: Where a report, its consent record and a fetched issue live, relative to the directory the
#: command runs in (the wrapper runs it at the repository root). Gitignored; every file argument of
#: the CLI must resolve inside it, so a prompt cannot point a subcommand at an arbitrary file.
WORK_DIR_NAME = ".bug-reports"

OUR_ORG = "unified-systems-com"
CORE_REPOSITORY = f"{OUR_ORG}/tap"

#: The headings of every report, in order. The same words as tap's bug issue form.
HEADINGS = ("What happened", "Steps to reproduce", "TAP version", "How it is run", "Health output", "Screenshots", "Anything else")
DATA_HEADING = "Report data"
DISCLOSURE_PREFIX = "Disclosure:"
_JSON_FENCE = "```json"
_FENCE = "```"

#: The fixed words of the tripwire's pass message (req-dev-bugreport-tripwire-3): never "safe".
TRIPWIRE_PASS = "no match against your instance's values"  # nosec B105 - a fixed message, not a credential

#: Deny-list values shorter than this match too much ordinary text to be a tripwire.
MIN_DENY_LENGTH = 4

_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9_.-]+$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class BugReportError(Exception):
    """A refusal the skills show to their user verbatim."""


# --------------------------------------------------------------------------------------------
# The schema both skills share (req-dev-bugreport-shape-1, -3)
# --------------------------------------------------------------------------------------------


def load_schema() -> dict[str, Any]:
    """Return the one report schema. Both skills name this file and neither restates its fields."""
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return schema


def schema_errors(data: Any) -> list[str]:
    """Every way ``data`` fails the report schema, as ``path: message`` lines (empty means valid)."""
    validator = jsonschema.Draft202012Validator(load_schema())
    return sorted(f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(data))


def fill_descriptions(data: dict[str, Any], node: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return ``data`` with each object's `description` key set from the schema node's own wording.

    The report's objects carry a `description` (the JSON-structures rule). The wording lives in
    the schema, so the builder takes it from there rather than restating it in a skill.
    """
    node = node or load_schema()
    props = node.get("properties", {})
    out = dict(data)
    if "description" in props and "description" not in out:
        out["description"] = node.get("description", "")
    for key, value in data.items():
        child = props.get(key, {})
        if isinstance(value, dict) and child.get("type") == "object":
            out[key] = fill_descriptions(value, child)
    return out


# --------------------------------------------------------------------------------------------
# submit-a-bug writes the report
# --------------------------------------------------------------------------------------------


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def render_report(data: dict[str, Any]) -> str:
    """Render the Markdown report from a validated data block (the template of `submit-a-bug`).

    Fixed headings, one fenced JSON block, and the disclosure line last. Refuses a value holding a
    code fence, which could end a block early and let a report carry two data blocks.
    """
    errors = schema_errors(data)
    if errors:
        raise BugReportError("report data does not match the schema:\n  " + "\n  ".join(errors))
    for text in _all_strings(data):
        if _FENCE in text:
            raise BugReportError("a report value contains a code fence (three backticks); reword it")
    versions, env = data["versions"], data["environment"]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(data["steps"], start=1))
    health = env.get("health_output")
    health_block = f"```shell\n{health}\n```" if health else "Not attached."
    sections = {
        "What happened": (
            f"{data['title']}\n\nFailing operation: {data['failing_operation']}\n\n"
            f"Expected: {data['expected']['summary']}\n\nActual: {data['actual']['summary']}"
        ),
        "Steps to reproduce": steps,
        "TAP version": versions["tap_version"] + (f" (commit {versions['tap_commit']})" if versions.get("tap_commit") else ""),
        "How it is run": env["run_mode"],
        "Health output": health_block,
        "Screenshots": "\n".join(f"![{shot['description']}](./{shot['file']})" for shot in data.get("screenshots") or []) or "None attached.",
        "Anything else": data.get("anything_else") or "Nothing further.",
    }
    parts = [f"## {name}\n\n{sections[name]}" for name in HEADINGS]
    block = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    parts.append(f"## {DATA_HEADING}\n\n{_JSON_FENCE}\n{block}\n{_FENCE}")
    parts.append(
        f"{DISCLOSURE_PREFIX} drafted with an AI agent (Claude Code, submit-a-bug); "
        "reproduced on synthetic data: no (version 0 carries no dataset); "
        "reviewed by the reporter before it was sent."
    )
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------------------------
# submit-a-fix reads the report: the report is data (req-dev-bugfix-untrusted-intake)
# --------------------------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DETAILS_RE = re.compile(r"<details\b.*?</details\s*>", re.DOTALL | re.IGNORECASE)
_VARIATION_SELECTORS = {chr(c) for c in (*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0))}


@dataclass
class Stripped:
    """What the sanitiser removed, so the human is told (req-dev-bugfix-untrusted-intake-2)."""

    invisible_characters: int = 0
    html_comments: int = 0
    details_blocks: int = 0

    def any(self) -> bool:
        return bool(self.invisible_characters or self.html_comments or self.details_blocks)

    def describe(self) -> str:
        return (
            f"stripped {self.invisible_characters} invisible character(s), "
            f"{self.html_comments} HTML comment(s), {self.details_blocks} collapsed <details> block(s)"
        )


def sanitize(text: str) -> tuple[str, Stripped]:
    """Remove invisible characters, HTML comments and collapsed blocks; return the text and a count.

    Order matters: invisible characters go first, because one placed inside `<!--` or `<details>`
    would otherwise hide the construct from the patterns that remove it.
    """
    stripped = Stripped()
    kept = []
    for ch in text:
        if unicodedata.category(ch) == "Cf" or ch in _VARIATION_SELECTORS:
            stripped.invisible_characters += 1
        else:
            kept.append(ch)
    text = "".join(kept)
    for pattern, attr in ((_COMMENT_RE, "html_comments"), (_DETAILS_RE, "details_blocks")):
        while True:
            text, n = pattern.subn("", text)
            if not n:
                break
            setattr(stripped, attr, getattr(stripped, attr) + n)
    return text, stripped


@dataclass(frozen=True)
class Finding:
    """A passage that reads like an instruction to an agent. It is reported, never obeyed."""

    line: int
    rule: str
    excerpt: str


_INSTRUCTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("override", re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|instructions?|rules?)\b", re.I)),
    ("directive", re.compile(r"\b(also|then|now|please|next|first)\s+(run|execute|update|push|install|fetch|download|delete|commit|open|post|send|apply|merge|curl|wget)\b", re.I)),
    ("command", re.compile(r"\b(curl|wget|git\s+push|git\s+remote|gh\s+(pr|issue|api|auth)|pip\s+install|npm\s+install|uv\s+add|rm\s+-rf|sudo|chmod|base64\s+-d)\b", re.I)),
    ("url", re.compile(r"https?://", re.I)),
    ("addressing the agent", re.compile(r"\b(you must|you should|as an? (ai|assistant|agent|llm)|system prompt|new instructions?|assistant:)\b", re.I)),
)


def instruction_findings(text: str) -> list[Finding]:
    """Every line of ``text`` that reads like an instruction, a command, or a URL to fetch.

    The skill's own reading is the primary control; this is a floor that cannot be talked out of
    a rule. A finding stops the run and the human is asked (req-dev-bugfix-untrusted-intake-3).
    """
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule, pattern in _INSTRUCTION_RULES:
            match = pattern.search(line)
            if match:
                findings.append(Finding(lineno, rule, line.strip()[:160]))
                break
    return findings


@dataclass
class Extracted:
    """A report read as data: the schema-valid block, the human sections, and what was stripped."""

    data: dict[str, Any]
    sections: dict[str, str]
    disclosure: str
    stripped: Stripped
    findings: list[Finding] = field(default_factory=list)


def extract_report(markdown: str) -> Extracted:
    """Read a report into the report shape (the reader of `submit-a-fix`).

    TAP-IMPLEMENTS: req-dev-bugfix-untrusted-intake@7c887a462172/8ca9e5ae9f91 (derivation) — the one reader: sanitise, extract the block, flag instruction-shaped text.

    Raises BugReportError unless the text has exactly one fenced JSON block that validates against
    the schema, the fixed headings, and the closing disclosure (req-dev-bugreport-shape-1, -2).
    """
    text, stripped = sanitize(markdown)
    fences = [m.start() for m in re.finditer(rf"(?m)^{re.escape(_JSON_FENCE)}\s*$", text)]
    if len(fences) != 1:
        raise BugReportError(f"expected exactly one fenced JSON block, found {len(fences)}")
    after = text[fences[0] + len(_JSON_FENCE) :]
    end = re.search(rf"(?m)^{re.escape(_FENCE)}\s*$", after)
    if end is None:
        raise BugReportError("the JSON block is never closed")
    try:
        data = json.loads(after[: end.start()])
    except ValueError as exc:
        raise BugReportError(f"the JSON block is not JSON: {exc}") from exc
    errors = schema_errors(data)
    if errors:
        raise BugReportError("the JSON block does not match the report schema:\n  " + "\n  ".join(errors))
    sections: dict[str, str] = {}
    for name in (*HEADINGS, DATA_HEADING):
        m = re.search(rf"(?m)^## {re.escape(name)}\s*$", text)
        if m is None:
            raise BugReportError(f"missing heading: {name}")
        nxt = re.search(r"(?m)^## ", text[m.end() :])
        body = text[m.end() : m.end() + nxt.start()] if nxt else text[m.end() :]
        sections[name] = body.strip()
    tail = [ln for ln in text.splitlines() if ln.strip()][-1]
    if not tail.startswith(DISCLOSURE_PREFIX):
        raise BugReportError("the report does not end with the disclosure line")
    human = "\n".join(sections[n] for n in HEADINGS)
    return Extracted(data=data, sections=sections, disclosure=tail, stripped=stripped, findings=instruction_findings(human + "\n" + json.dumps(data, indent=1)))


# --------------------------------------------------------------------------------------------
# The author gate (req-dev-bugfix-ownreports)
# --------------------------------------------------------------------------------------------


def _session_identity() -> Any:
    """Load scripts/pr_session_identity.py by path: the one derivation `req-cicd-issue-link-7` uses."""
    spec = importlib.util.spec_from_file_location("pr_session_identity", SESSION_IDENTITY_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is in the tree
        raise BugReportError(f"cannot load {SESSION_IDENTITY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def author_gate(author_id: Any, author_type: Any, login: str = "", *, authors_path: Path | None = None) -> tuple[bool, str]:
    """May ``submit-a-fix`` read this issue's body? True only for a maintainer session account.

    TAP-IMPLEMENTS: req-dev-bugfix-ownreports@2007130ffeb7/281006dcc4e3 (enforcement) — the one author check; it asks scripts/pr_session_identity.py.

    The authority is the numeric account id plus the type from the issue as GitHub returned it,
    never a name in the text. Anything but a listed session account, including an unreadable
    allowlist or a malformed identity, is a stop (fail closed).
    """
    module = _session_identity()
    try:
        authors = module.load_session_authors(authors_path) if authors_path else module.load_session_authors()
    except module.SessionAuthorsError as exc:
        return False, f"the session-author allowlist cannot be read ({exc}); the issue body was not read"
    verdict, reason = module.classify(str(author_id or ""), str(author_type or ""), login, authors)
    if verdict == module.SESSION:
        return True, reason
    return False, (
        f"author check failed ({verdict}): {reason}. Version 0 reads only issues written by a maintainer "
        "session account (req-dev-bugfix-ownreports); bugs from other accounts wait for the sandbox. "
        "The issue body was not read."
    )


def filter_comments(comments: list[dict[str, Any]], issue_author_id: int, maintainer_ids: set[int]) -> tuple[list[dict[str, Any]], int]:
    """Keep only comments written by the issue's author or a maintainer; return them and the count dropped.

    Identity is the numeric account id from GitHub's response. The text of a comment is not
    consulted, so a comment that claims to be from a maintainer is still an outsider's.
    """
    keep_ids = {issue_author_id, *maintainer_ids}
    kept = [c for c in comments if isinstance(c.get("user"), dict) and c["user"].get("id") in keep_ids]
    return kept, len(comments) - len(kept)


# --------------------------------------------------------------------------------------------
# Routing and environment (req-dev-bugreport-route, -environment)
# --------------------------------------------------------------------------------------------


def read_boot_record(profile_id: str | None, root: Path = REPO_ROOT) -> dict[str, Any]:
    """The running install's boot record: `boot/<TAP_BOOT_PROFILE>.boot.json`. {} when no profile is set."""
    if not profile_id:
        return {}
    if not _ID_RE.match(profile_id):
        raise BugReportError("the boot profile id is not a plain identifier")
    path = root / "boot" / f"{profile_id}.boot.json"
    try:
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return record
    except OSError as exc:
        raise BugReportError(f"cannot read the boot record {path.name}: {exc}") from exc
    except ValueError as exc:
        raise BugReportError(f"the boot record {path.name} is not JSON: {exc}") from exc


def _owner_name(url: str) -> tuple[str, str] | None:
    m = re.match(r"^https://github\.com/([A-Za-z0-9][A-Za-z0-9_.-]*)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url or "")
    return (m.group(1), m.group(2)) if m else None


def _enabled_plugins(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in (record.get("install") or {}).get("plugins", []) if p.get("enabled", True) is not False]


def _is_ours(plugin: dict[str, Any]) -> bool:
    parsed = _owner_name((plugin.get("source") or {}).get("url", ""))
    return parsed is not None and parsed[0] == OUR_ORG


def plugin_facts(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The plugin list for the report: only plugins sourced from unified-systems-com, with slug, rev and commit.

    A plugin from anywhere else is not listed at all, not even as a blank entry, so the list's
    length never reveals how many third-party plugins the reporter runs.
    """
    return [
        {
            "slug": plugin.get("slug"),
            "rev": (plugin.get("source") or {}).get("rev") or "unknown",
            "commit": (plugin.get("source") or {}).get("commit"),
        }
        for plugin in _enabled_plugins(record)
        if _is_ours(plugin)
    ]


def third_party_plugins_in_use(record: dict[str, Any]) -> bool:
    """One flag, no count: is any enabled plugin sourced from outside unified-systems-com?"""
    return any(not _is_ours(plugin) for plugin in _enabled_plugins(record))


def route_target(record: dict[str, Any], plugin_slug: str | None) -> tuple[str, str]:
    """Where a bug goes: ``(repository, note)``. A plugin's repository is read from the boot record, never inferred.

    Core or an unattributed failure goes to `unified-systems-com/tap`. A source outside
    unified-systems-com is third-party: the caller is told, and no repository of ours is returned
    (req-dev-bugreport-route-2, -3).
    """
    if not plugin_slug:
        return CORE_REPOSITORY, "core or unattributed failure"
    for plugin in (record.get("install") or {}).get("plugins", []):
        if plugin.get("slug") == plugin_slug:
            parsed = _owner_name((plugin.get("source") or {}).get("url", ""))
            if parsed is None:
                raise BugReportError(f"plugin {plugin_slug!r} has no readable source URL in the boot record")
            owner, name = parsed
            if owner != OUR_ORG:
                raise BugReportError(
                    f"plugin {plugin_slug!r} is a third-party plugin from {owner}/{name}. Report it there; "
                    f"this skill does not file into {OUR_ORG} on its behalf."
                )
            return f"{owner}/{name}", "plugin source from the boot record"
    raise BugReportError(f"plugin {plugin_slug!r} is not in the install's boot record")


def require_repository(repo: str) -> str:
    """A repository argument must be a plain owner/name; nothing else ever reaches a command."""
    if not _REPO_RE.match(repo or ""):
        raise BugReportError("repository must be a plain owner/name")
    return repo


def require_ours(repo: str) -> str:
    """Only a `unified-systems-com` repository may be filed into (req-dev-bugreport-route-3)."""
    require_repository(repo)
    if repo.split("/", 1)[0] != OUR_ORG:
        raise BugReportError(f"{repo} is not in {OUR_ORG}: a third-party repository is not ours to file into")
    return repo


# --------------------------------------------------------------------------------------------
# The tripwire (req-dev-bugreport-tripwire)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    """One thing that blocks the send, with its line."""

    line: int
    kind: str
    match: str


def build_deny_list(
    record: dict[str, Any],
    *,
    hostnames: list[str] | None = None,
    local_user: str | None = None,
    home_path: str | None = None,
) -> list[tuple[str, str]]:
    """The reporter's own identifiers, as ``(kind, value)``. Held in memory; never written anywhere.

    From the spec: the instance's hostnames; every owner,
    repository name and slug of a plugin sourced outside unified-systems-com; the local username
    and home path. Values shorter than ``MIN_DENY_LENGTH`` are dropped: they match ordinary words.
    """
    entries: list[tuple[str, str]] = []
    entries += [("instance hostname", h) for h in (hostnames or [])]
    for plugin in (record.get("install") or {}).get("plugins", []):
        source = plugin.get("source") or {}
        parsed = _owner_name(source.get("url", ""))
        if parsed is not None and parsed[0] == OUR_ORG:
            continue
        if parsed is not None:
            entries += [("third-party plugin owner", parsed[0]), ("third-party plugin repository", parsed[1])]
        if source.get("url"):
            entries.append(("third-party plugin source", source["url"]))
        if plugin.get("slug"):
            entries.append(("third-party plugin slug", plugin["slug"]))
    if local_user:
        entries.append(("local username", local_user))
    if home_path:
        entries.append(("local home path", home_path))
    seen: set[tuple[str, str]] = set()
    out = []
    for kind, value in entries:
        value = (value or "").strip()
        if len(value) >= MIN_DENY_LENGTH and (kind, value) not in seen:
            seen.add((kind, value))
            out.append((kind, value))
    return out


def tripwire(text: str, deny: list[tuple[str, str]]) -> list[Hit]:
    """Check outgoing text against the deny list and `CREDENTIAL_PATTERNS`; every hit blocks the send.

    TAP-IMPLEMENTS: req-dev-bugreport-tripwire@229b2097b67e/14d3c66dc3c6 (enforcement) — the one scan every outgoing report and search query passes.

    The credential scan uses the patterns directly. `credential_patterns.scan_text` skips a line
    carrying its `TAP-CREDENTIAL-OK` marker, and a draft must not be able to switch the tripwire
    off by containing that word. Matching is case-insensitive for the deny list.
    """
    hits: list[Hit] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        for kind, value in deny:
            if value.lower() in lowered:
                hits.append(Hit(lineno, kind, value))
        for pattern in CREDENTIAL_PATTERNS:
            for found in pattern.regex.finditer(line):
                hits.append(Hit(lineno, f"credential shape ({pattern.name})", f"{found.group()[:10]}...<masked>"))
    return hits


def format_hits(hits: list[Hit]) -> str:
    if not hits:
        return f"Tripwire: {TRIPWIRE_PASS}. This is a tripwire, not a guarantee that the report is safe."
    lines = [f"  line {h.line}: {h.kind}: {h.match}" for h in hits]
    return "Tripwire BLOCKED the send:\n" + "\n".join(lines)


_VOCABULARY_QUERY_RE = re.compile(r"^[A-Za-z0-9_ .:/-]{1,120}$")


def check_search_query(query: str, deny: list[tuple[str, str]]) -> list[Hit]:
    """The duplicate-search query is outbound before any consent: it passes the tripwire and a shape check.

    The shape check keeps it to a short run of plain words (a plugin slug, an error class, a model
    or field name); anything with quoting, operators or punctuation is refused as a hit.
    """
    hits = tripwire(query, deny)
    if not _VOCABULARY_QUERY_RE.match(query or ""):
        hits.append(Hit(1, "query shape", "not a short run of plain words from TAP's own vocabulary"))
    return hits


# --------------------------------------------------------------------------------------------
# Consent, bound to the bytes (req-dev-bugreport-consent)
# --------------------------------------------------------------------------------------------


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def consent_phrase(file_digest: str) -> str:
    """The exact words the reporter types: ``yes`` plus the first 12 hex characters of the file's hash."""
    return f"yes {file_digest[:12]}"


def resolve_in_work_dir(path: str, work_dir: Path | None = None) -> Path:
    """A file argument must lie inside the work directory; anything else is refused."""
    base = (work_dir or Path.cwd() / WORK_DIR_NAME).resolve()
    resolved = Path(path).resolve() if Path(path).is_absolute() else (Path.cwd() / path).resolve()
    if base != resolved and base not in resolved.parents:
        raise BugReportError(f"{path} is outside {base.name}/; reports live only there")
    return resolved


def consent_path(report: Path) -> Path:
    return report.with_name(report.name + ".consent")


IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
}
MAX_ATTACHMENTS = 5
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
ATTACHMENT_WARNING = (
    "the tripwire cannot check this image; you must look at it yourself, it will be public and permanent "
    "and may show your instance's values, hostnames, usernames or session labels"
)


@dataclass(frozen=True)
class Attachment:
    """One screenshot, checked for type and size only: its pixels are never read by this code."""

    name: str
    alt: str
    path: Path
    size: int
    sha256: str

    @property
    def host_path(self) -> str:
        return f"{WORK_DIR_NAME}/{self.name}"


def load_attachments(report: Path, data: dict[str, Any]) -> list[Attachment]:
    """Check the report's screenshots: images only, at most five, each a plain file inside the work directory.

    The checks are type (name suffix and the file's first bytes) and size. The image is hashed so
    the reporter's yes can bind to its bytes; it is never decoded, displayed or described.
    """
    items = data.get("screenshots") or []
    if len(items) > MAX_ATTACHMENTS:
        raise BugReportError(f"at most {MAX_ATTACHMENTS} screenshots may be attached")
    found: list[Attachment] = []
    seen: set[str] = set()
    for item in items:
        name = item["file"]
        if name in seen:
            raise BugReportError(f"screenshot {name} is listed twice")
        seen.add(name)
        raw = report.parent / name
        if raw.is_symlink():
            raise BugReportError(f"screenshot {name} is a symbolic link; only plain files are accepted")
        path = resolve_in_work_dir(str(raw))
        if not path.is_file():
            raise BugReportError(f"screenshot {name} is not a file in {WORK_DIR_NAME}/")
        suffix = path.suffix.lower()
        if suffix not in IMAGE_MAGIC:
            raise BugReportError(f"screenshot {name}: only png, jpg and gif images are accepted (no video, nothing else)")
        size = path.stat().st_size
        if not 0 < size <= MAX_ATTACHMENT_BYTES:
            raise BugReportError(f"screenshot {name} is {size} bytes; the limit is {MAX_ATTACHMENT_BYTES}")
        with path.open("rb") as handle:
            head = handle.read(16)
        if not any(head.startswith(magic) for magic in IMAGE_MAGIC[suffix]):
            raise BugReportError(f"screenshot {name} is not a real {suffix[1:]} image")
        found.append(Attachment(name=name, alt=item["description"], path=path, size=size, sha256=digest(path.read_bytes())))
    return found


def bundle_digest(report: Path) -> str:
    """The hash a yes binds to: the report's bytes and every attachment's bytes, in the report's order.

    With no attachments it is the report file's own sha256. Changing or adding an image changes it.
    """
    raw = report.read_bytes()
    attachments = load_attachments(report, extract_report(raw.decode("utf-8")).data)
    if not attachments:
        return digest(raw)
    outer = hashlib.sha256()
    for label, blob in (("report", raw), *((a.name, a.path.read_bytes()) for a in attachments)):
        outer.update(f"{label}\0{len(blob)}\0".encode())
        outer.update(blob)
    return outer.hexdigest()


def record_consent(report: Path, typed: str) -> str:
    """Write a consent record iff ``typed`` is exactly the phrase for the report and its attachments as they are now."""
    current = bundle_digest(report)
    if typed.strip() != consent_phrase(current):
        raise BugReportError(f"consent not recorded: the yes must be exactly {consent_phrase(current)!r} for these bytes")
    consent_path(report).write_text(current + "\n", encoding="utf-8")
    return current


def verify_consent(report: Path) -> str:
    """Return the file's digest iff a consent record exists for exactly these bytes; otherwise refuse.

    TAP-IMPLEMENTS: req-dev-bugreport-consent@4ea4a641c38f/cdbaeef74db7 (enforcement) — the one check that a yes still covers the file about to be sent.
    """
    record = consent_path(report)
    if not record.is_file():
        raise BugReportError("no consent recorded for this file: preview it and take a yes first")
    current = bundle_digest(report)
    if record.read_text(encoding="utf-8").strip() != current:
        raise BugReportError("the report or an attachment changed after consent; preview it again and take a new yes")
    return current


def prepare_send(report: Path, deny: list[tuple[str, str]]) -> dict[str, str]:
    """Everything that must hold before `gh issue create`: valid report, tripwire clean, consent on these bytes, our repository."""
    text = report.read_text(encoding="utf-8")
    extracted = extract_report(text)
    if extracted.stripped.any():
        raise BugReportError(f"the report holds hidden text ({extracted.stripped.describe()}); a report we send has none")
    hits = tripwire(text, deny)
    if hits:
        raise BugReportError(format_hits(hits))
    verify_consent(report)
    repo = require_ours(extracted.data["target_repository"])
    attachments = "\n".join(f"{a.host_path}#{a.alt}" for a in load_attachments(report, extracted.data))
    return {"repository": repo, "title": extracted.data["title"], "attachments": attachments}


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def _login_name() -> str | None:
    """The login name, or None when the process's uid has no name.

    A container or CI runner can run as a uid with no passwd entry and no USER/LOGNAME, where
    getpass.getuser() raises. A missing name only means the deny list has one fewer entry.
    """
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return None


def _local_deny(args: argparse.Namespace) -> list[tuple[str, str]]:
    import os

    record = read_boot_record(os.environ.get("TAP_BOOT_PROFILE", "").strip() or None)
    hostnames = [h for h in (args.host_name or []) if h]
    hostnames.append(socket.gethostname())
    try:
        from django.conf import settings

        hostnames += [h for h in settings.ALLOWED_HOSTS if h and h not in ("*", "localhost", "127.0.0.1")]
    except Exception:  # noqa: BLE001  # nosec B110 - settings are optional here; the deny list just has fewer entries
        pass
    user = args.host_user or _login_name()
    return build_deny_list(record, hostnames=hostnames, local_user=user, home_path=args.host_home)


def _add_deny_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host-user")
    p.add_argument("--host-home")
    p.add_argument("--host-name", action="append")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.bug_report", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema-path")
    p = sub.add_parser("render")
    p.add_argument("answers")
    p.add_argument("out")
    p = sub.add_parser("route")
    p.add_argument("--plugin")
    p = sub.add_parser("facts")
    for flag in ("os", "arch", "docker", "compose"):
        p.add_argument(f"--{flag}", default="unknown")
    p = sub.add_parser("check")
    p.add_argument("file")
    _add_deny_args(p)
    p = sub.add_parser("search-query")
    p.add_argument("query")
    _add_deny_args(p)
    p = sub.add_parser("preview")
    p.add_argument("file")
    _add_deny_args(p)
    p = sub.add_parser("consent")
    p.add_argument("file")
    p.add_argument("typed")
    p = sub.add_parser("verify-send")
    p.add_argument("file")
    p.add_argument("--print", dest="field", choices=("repository", "title", "attachments"), help="print one field of the verified send, for the wrapper")
    _add_deny_args(p)
    sub.add_parser("gate-author")
    p = sub.add_parser("intake")
    p.add_argument("issue")
    p.add_argument("comments")
    p.add_argument("--maintainer-id", action="append", type=int, default=[])
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except BugReportError as exc:
        print(f"bug-report: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:  # noqa: C901, PLR0911, PLR0912 - one flat switch over subcommands
    import os

    cmd = args.cmd
    if cmd == "schema-path":
        print(SCHEMA_PATH)
        return 0
    if cmd == "render":
        answers = json.loads(resolve_in_work_dir(args.answers).read_text(encoding="utf-8"))
        out = resolve_in_work_dir(args.out)
        if not os.path.realpath(out).startswith(os.path.realpath(Path.cwd() / WORK_DIR_NAME) + os.sep):
            raise BugReportError(f"{args.out} is outside {WORK_DIR_NAME}/; reports live only there")
        out.write_text(render_report(fill_descriptions(answers)), encoding="utf-8")
        print(f"wrote {out.name}")
        return 0
    if cmd == "route":
        record = read_boot_record(os.environ.get("TAP_BOOT_PROFILE", "").strip() or None)
        repo, note = route_target(record, args.plugin)
        print(json.dumps({"repository": repo, "note": note, "private_vulnerability_reporting": f"https://github.com/{repo}/security/advisories/new"}))
        return 0
    if cmd == "facts":
        from tap.core_version import core_tap_version

        record = read_boot_record(os.environ.get("TAP_BOOT_PROFILE", "").strip() or None)
        print(
            json.dumps(
                {
                    "tap_version": core_tap_version(),
                    "profile_kind": record.get("profile_kind", "unknown"),
                    "plugins": plugin_facts(record),
                    "third_party_plugins_in_use": third_party_plugins_in_use(record),
                    "os": args.os,
                    "arch": args.arch,
                    "docker_version": args.docker,
                    "compose_version": args.compose,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if cmd == "gate-author":
        payload = json.loads(sys.stdin.read() or "{}")
        ok, reason = author_gate(payload.get("id"), payload.get("type"), str(payload.get("login") or ""))
        print(reason)
        return 0 if ok else 1
    if cmd == "intake":
        issue = json.loads(resolve_in_work_dir(args.issue).read_text(encoding="utf-8"))
        comments = json.loads(resolve_in_work_dir(args.comments).read_text(encoding="utf-8"))
        ok, reason = author_gate((issue.get("user") or {}).get("id"), (issue.get("user") or {}).get("type"), str((issue.get("user") or {}).get("login") or ""))
        if not ok:
            print(reason, file=sys.stderr)
            return 1
        extracted = extract_report(issue.get("body") or "")
        if "pull_request" in issue:
            raise BugReportError("that number is a pull request, not an issue")
        if comments and all(isinstance(c, list) for c in comments):
            comments = [item for page in comments for item in page]
        maintainers = set(_session_identity().load_session_authors()) | set(args.maintainer_id)
        kept, dropped = filter_comments(comments, issue["user"]["id"], maintainers)
        clean_comments = []
        for c in kept:
            text, _ = sanitize(str(c.get("body") or ""))
            clean_comments.append({"author_id": c["user"]["id"], "body": text})
        print(
            json.dumps(
                {
                    "report": extracted.data,
                    "sections": extracted.sections,
                    "stripped": extracted.stripped.describe(),
                    "comments_read": clean_comments,
                    "comments_not_read": dropped,
                    "findings": [{"line": f.line, "rule": f.rule, "excerpt": f.excerpt} for f in extracted.findings],
                    "stop": bool(extracted.findings),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2 if extracted.findings else 0
    if cmd == "consent":
        print(f"consent recorded for sha256 {record_consent(resolve_in_work_dir(args.file), args.typed)}")
        return 0
    # The remaining subcommands build the deny list.
    deny = _local_deny(args)
    if cmd == "search-query":
        hits = check_search_query(args.query, deny)
        print(format_hits(hits))
        return 1 if hits else 0
    report = resolve_in_work_dir(args.file)
    if cmd == "check":
        hits = tripwire(report.read_text(encoding="utf-8"), deny)
        extract_report(report.read_text(encoding="utf-8"))
        print(format_hits(hits))
        return 1 if hits else 0
    if cmd == "preview":
        text = report.read_text(encoding="utf-8")
        extracted = extract_report(text)
        if extracted.stripped.any():
            raise BugReportError(f"the report holds hidden text ({extracted.stripped.describe()}); a report we send has none")
        hits = tripwire(text, deny)
        print(format_hits(hits))
        if hits:
            return 1
        attachments = load_attachments(report, extracted.data)
        file_digest = bundle_digest(report)
        target = extracted.data["target_repository"]
        print(f"File: {report}\nsha256 (the report plus every attachment, in order): {file_digest}\nTarget repository: {target}")
        for number, att in enumerate(attachments, start=1):
            print(f"Attachment {number}: {att.path}  {att.size} bytes  sha256 {att.sha256}\n  {ATTACHMENT_WARNING}")
        print("This issue will be PUBLIC and PERMANENT: GitHub keeps a public edit history, so editing it later does not remove earlier text.")
        print("Version 0 replaced nothing with synthetic values: the report carries no dataset and no instance value.")
        print(f"To send exactly these bytes, type: {consent_phrase(file_digest)}")
        print("----- BEGIN FILE -----")
        print(text, end="")
        print("----- END FILE -----")
        return 0
    if cmd == "verify-send":
        info = prepare_send(report, deny)
        print(info[args.field] if args.field else json.dumps(info))
        return 0
    raise BugReportError(f"unknown subcommand {cmd}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
