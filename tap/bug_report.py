"""The mechanics behind the `submit-a-bug` and `submit-a-fix` skills (specs/spec-dev-bug-reporting.md).

Two skills, one module. `submit-a-bug` runs in a reporter's install: the agent investigates the
failure with everything it has locally and writes a report. `submit-a-fix` reads one. Everything
that has to be exact lives here so it can be tested rather than trusted to a prompt: the report
schema both skills share (`tap/skills/bug-report.schema.json`), the renderer and the reader that
round-trip through it, the checks the renderer makes (one component's version, a security answer of
no, a root cause or theories, sample data in reserved ranges), the tripwire with its deny list, the
observed-values file, the consent binding, the author gate, and the sanitising intake.

Version 1 (George, 2026-11-11): the agent reads everything locally and changes nothing; the report
carries shapes, reasoning and invented data plus the one buggy component's version, and no value
from the instance. The protection moved from "never read it" to "guard what leaves".

Stdlib plus `jsonschema` (already a core dependency). Run it in the container:
`scripts/bug-report <subcommand>` wraps `python -m tap.bug_report`.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import importlib.util
import ipaddress
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
#: Where a report, its consent record, the observed-values file and a fetched issue live, relative
#: to the directory the command runs in (the wrapper runs it at the repository root). Gitignored;
#: every file argument of the CLI must resolve inside it, so a prompt cannot point a subcommand at
#: an arbitrary file.
WORK_DIR_NAME = ".bug-reports"
#: The values the agent read from the instance while investigating, one per line. Every one is a
#: deny-list entry; the file never leaves the session (req-dev-bugreport-investigate-4, -tripwire-5, -6).
OBSERVED_FILE_NAME = "observed.txt"

OUR_ORG = "unified-systems-com"
CORE_REPOSITORY = f"{OUR_ORG}/tap"
CORE_SLUG = "tap"

#: The headings of every report, in order. Rendered from the data block, so a human reads what the fixer parses.
HEADINGS = (
    "What happened",
    "Component",
    "Security",
    "Findings",
    "Conclusion",
    "Scenario",
    "Not observed",
    "Related issues",
    "Suggested fix",
    "Build facts carried as evidence",
    "Screenshots",
)
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
    return sorted(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in validator.iter_errors(data)
    )


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
        child_type = child.get("type")
        is_object = child_type == "object" or (isinstance(child_type, list) and "object" in child_type)
        if isinstance(value, dict) and is_object and "properties" in child:
            out[key] = fill_descriptions(value, child)
    return out


# --------------------------------------------------------------------------------------------
# What the renderer checks before a report exists (req-dev-bugreport-route-1, -conclude-1,
# -scenario-2, -disclosure-1)
# --------------------------------------------------------------------------------------------


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return []


def private_reporting_url(repo: str) -> str:
    return f"https://github.com/{repo}/security/advisories/new"


def check_security_answer(data: dict[str, Any]) -> None:
    """A report is rendered only on a security answer of `no` (req-dev-bugreport-route-1)."""
    answer = data["security"]["answer"]
    if answer != "no":
        raise BugReportError(
            f"the security answer is {answer!r}: no public issue is drafted. Report it through private "
            f"vulnerability reporting instead: {private_reporting_url(data['target_repository'])} (see SECURITY.md)."
        )


def check_conclusion(data: dict[str, Any]) -> None:
    """Exactly one of a root cause or two-plus ranked theories (req-dev-bugreport-conclude-1)."""
    conclusion = data["conclusion"]
    kind, root, theories = conclusion["kind"], conclusion["root_cause"], conclusion["theories"]
    n_findings = len(data["findings"])
    if kind == "root_cause":
        if root is None or theories:
            raise BugReportError("conclusion kind is root_cause: root_cause must be set and theories must be empty")
        refs = list(root["evidence"])
    else:
        if root is not None or len(theories) < 2:
            raise BugReportError(
                "conclusion kind is theories: root_cause must be null and at least two theories must be ranked"
            )
        ranks = sorted(t["rank"] for t in theories)
        if ranks != list(range(1, len(theories) + 1)):
            raise BugReportError("theories must be ranked 1..n with no gaps or ties")
        refs = [i for t in theories for i in (*t["evidence_for"], *t["evidence_against"])]
    bad = [i for i in refs if i >= n_findings]
    if bad:
        raise BugReportError(f"evidence index out of range: {bad} (there are {n_findings} findings)")


#: Documentation-reserved ranges (req-dev-bugreport-scenario-2): RFC 5737 IPv4, RFC 3849 IPv6,
#: RFC 2606 / RFC 6761 names, and AWS's documentation account ID.
RESERVED_IPV4 = tuple(ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))
RESERVED_IPV6 = (ipaddress.ip_network("2001:db8::/32"),)
RESERVED_DOMAIN_SUFFIXES = ("example.com", "example.org", "example.net", ".example", ".test", ".invalid", ".localhost")
RESERVED_AWS_ACCOUNT = "123456789012"

_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.])")
_IPV6_RE = re.compile(r"(?<![\w:])([0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,7})(?![\w:])", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_AWS_ACCOUNT_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")
_DOMAIN_RE = re.compile(r"(?<![\w/@.-])((?:[a-z0-9-]+\.)+[a-z]{2,})(?![\w/-])", re.I)
_URL_HOST_RE = re.compile(r"[a-z][a-z0-9+.-]*://(?:[^/\s@]*@)?([a-z0-9.-]+)", re.I)
_CODE_SUFFIXES = (
    ".py",
    ".json",
    ".md",
    ".js",
    ".html",
    ".toml",
    ".yml",
    ".yaml",
    ".txt",
    ".css",
    ".sh",
    ".csv",
    ".sql",
    ".ts",
    ".svg",
    ".png",
    ".jpg",
    ".gif",
)


def _reserved_domain(name: str) -> bool:
    lowered = name.lower()
    return any(lowered == s.lstrip(".") or lowered.endswith(s) for s in RESERVED_DOMAIN_SUFFIXES)


def unreserved_values(text: str, *, domains: bool) -> list[tuple[str, str]]:
    """Every IP, email, AWS account ID and (when ``domains``) domain in ``text`` outside the reserved ranges."""
    bad: list[tuple[str, str]] = []
    for m in _IPV4_RE.finditer(text):
        try:
            addr = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if not any(addr in n for n in RESERVED_IPV4):
            bad.append(("ipv4 address", m.group(1)))
    for m in _IPV6_RE.finditer(text):
        try:
            addr6 = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if not any(addr6 in n for n in RESERVED_IPV6):
            bad.append(("ipv6 address", m.group(1)))
    for m in _EMAIL_RE.finditer(text):
        if not _reserved_domain(m.group(1)):
            bad.append(("email address", m.group(0)))
    for m in _AWS_ACCOUNT_RE.finditer(text):
        if m.group(1) != RESERVED_AWS_ACCOUNT:
            bad.append(("aws account id", m.group(1)))
    if domains:
        for m in _DOMAIN_RE.finditer(text):
            name = m.group(1)
            if name.lower().endswith(_CODE_SUFFIXES) or _reserved_domain(name):
                continue
            bad.append(("domain", name))
        for m in _URL_HOST_RE.finditer(text):
            host = m.group(1)
            if host.replace(".", "").isdigit() or _reserved_domain(host):
                continue
            bad.append(("url host", host))
    return bad


def check_sample_data(data: dict[str, Any]) -> None:
    """Sample data and steps use documentation-reserved ranges only (req-dev-bugreport-scenario-2)."""
    scenario = data["scenario"]
    sample = scenario["sample_data"]
    if sample["kind"] == "none":
        if sample["content"] is not None or not sample["none_because"]:
            raise BugReportError("sample_data kind is none: content must be null and none_because must say why")
    elif sample["content"] in (None, "", {}) or sample["none_because"] is not None:
        raise BugReportError("sample_data must carry content, and none_because must be null, unless kind is none")
    if scenario["tried"] == "untried" and scenario["outcome"] is not None:
        raise BugReportError("an untried scenario has no outcome: set outcome to null, or mark it tried")
    if scenario["tried"] == "tried" and not scenario["outcome"]:
        raise BugReportError("a tried scenario states its outcome")
    sample_text = (
        json.dumps(sample["content"], ensure_ascii=True)
        if isinstance(sample["content"], dict)
        else str(sample["content"] or "")
    )
    bad = unreserved_values(sample_text, domains=True) + unreserved_values("\n".join(scenario["steps"]), domains=False)
    if bad:
        lines = "\n  ".join(f"{kind}: {value}" for kind, value in bad)
        raise BugReportError(
            "the scenario holds values outside the documentation-reserved ranges; invent them from "
            "RFC 5737 / RFC 3849 addresses, RFC 2606 names and the AWS account 123456789012:\n  " + lines
        )


def validate_block(data: dict[str, Any]) -> None:
    """Every check a data block must pass, at render time and again at check, preview and send time.

    The schema; no value holding a code fence, which could end a block early and let a report
    carry two data blocks; a security answer of no; a conclusion that is exactly one of its two
    states; sample data in the reserved ranges. Re-run before a send so a block edited by hand
    after rendering cannot carry what render would have refused.
    """
    errors = schema_errors(data)
    if errors:
        raise BugReportError("report data does not match the schema:\n  " + "\n  ".join(errors))
    for text in _all_strings(data):
        if _FENCE in text:
            raise BugReportError("a report value contains a code fence (three backticks); reword it")
    check_security_answer(data)
    check_conclusion(data)
    check_sample_data(data)


def render_report(data: dict[str, Any]) -> str:
    """Render the Markdown report from a validated data block (the template of `submit-a-bug`).

    Fixed headings rendered from the block, one fenced JSON block, and the disclosure line last.
    Refuses everything `validate_block` refuses.
    """
    validate_block(data)
    component = data["component"]
    conclusion = data["conclusion"]
    scenario = data["scenario"]
    findings = (
        "\n".join(f"{i}. `{f['method']}` {f['location']}: {f['shows']}" for i, f in enumerate(data["findings"]))
        or "None recorded."
    )
    if conclusion["kind"] == "root_cause":
        root = conclusion["root_cause"]
        where = f"`{root['path']}`" + (f" line {root['line']}" if root["line"] else "")
        conclusion_text = f"Root cause at {where}.\n\nDoes: {root['does']}\n\nShould: {root['should']}\n\nEvidence: findings {', '.join(str(i) for i in root['evidence'])}."
    else:
        rows = []
        for t in sorted(conclusion["theories"], key=lambda t: t["rank"]):
            rows.append(
                f"{t['rank']}. {t['cause']}\n   For: findings {', '.join(str(i) for i in t['evidence_for']) or 'none'}. "
                f"Against: findings {', '.join(str(i) for i in t['evidence_against']) or 'none'}. Would settle it: {t['would_settle']}"
            )
        conclusion_text = "No single root cause established. Theories, ranked:\n\n" + "\n".join(rows)
    sample = scenario["sample_data"]
    if sample["kind"] == "none":
        sample_text = f"No sample data: {sample['none_because']}"
    elif isinstance(sample["content"], dict):
        sample_text = f"Sample data ({sample['kind']}):\n\n```text\n{json.dumps(sample['content'], indent=2, sort_keys=True, ensure_ascii=True)}\n```"
    else:
        sample_text = f"Sample data ({sample['kind']}):\n\n```text\n{sample['content']}\n```"
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(scenario["steps"], start=1))
    tried = (
        f"Tried: {scenario['outcome']}"
        if scenario["tried"] == "tried"
        else "Not tried: the scenario is the agent's proposal, not a reproduction."
    )
    sections = {
        "What happened": data["reporter_description"],
        "Component": f"{component['kind']} `{component['slug']}` at {component['version']}"
        + (f" (commit {component['commit']})" if component.get("commit") else ""),
        "Security": f"Answer: {data['security']['answer']}. {data['security']['reasoning']}",
        "Findings": findings,
        "Conclusion": conclusion_text,
        "Scenario": f"{steps}\n\n{sample_text}\n\n{tried}",
        "Not observed": "\n".join(f"- {n}" for n in data["not_observed"])
        or "Nothing the agent wanted to see was out of reach.",
        "Related issues": "\n".join(f"- #{r['number']}: {r['why']}" for r in data["related_issues"]) or "None found.",
        "Suggested fix": (
            f"`{data['suggested_fix']['path']}`: {data['suggested_fix']['note']}"
            if data["suggested_fix"]
            else "No view yet."
        ),
        "Build facts carried as evidence": "\n".join(
            f"- {b['fact']}: {b['reason']}" for b in data["evidence_build_facts"]
        )
        or "None.",
        "Screenshots": "\n".join(
            f"![{shot['description']}](./{shot['file']})" for shot in data.get("screenshots") or []
        )
        or "None attached.",
    }
    parts = [f"## {name}\n\n{sections[name]}" for name in HEADINGS]
    block = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    parts.append(f"## {DATA_HEADING}\n\n{_JSON_FENCE}\n{block}\n{_FENCE}")
    parts.append(
        f"{DISCLOSURE_PREFIX} drafted by an AI agent (Claude Code, submit-a-bug) from its own investigation of the "
        f"reporter's install; scenario tried: {'yes' if scenario['tried'] == 'tried' else 'no'}; "
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
    (
        "override",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|instructions?|rules?)\b",
            re.I,
        ),
    ),
    (
        "directive",
        re.compile(
            r"\b(also|then|now|please|next|first)\s+(run|execute|update|push|install|fetch|download|delete|commit|open|post|send|apply|merge|curl|wget)\b",
            re.I,
        ),
    ),
    (
        "command",
        re.compile(
            r"\b(curl|wget|git\s+push|git\s+remote|gh\s+(pr|issue|api|auth)|pip\s+install|npm\s+install|uv\s+add|rm\s+-rf|sudo|chmod|base64\s+-d)\b",
            re.I,
        ),
    ),
    ("url", re.compile(r"https?://", re.I)),
    (
        "addressing the agent",
        re.compile(
            r"\b(you must|you should|as an? (ai|assistant|agent|llm)|system prompt|new instructions?|assistant:)\b",
            re.I,
        ),
    ),
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


#: What the intake prints in place of text it will not hand over (req-dev-bugreport-investigate-3).
WITHHELD = "withheld: {n} instruction-shaped line(s); the findings carry the excerpts and the human decides"


def read_as_data(text: str) -> tuple[str, Stripped, list[Finding]]:
    """An existing issue read during investigation: sanitised, with its instruction-shaped lines flagged.

    TAP-IMPLEMENTS: req-dev-bugreport-investigate@bf6e683be7fd/b5805aa4411b (enforcement) — the one intake every issue body read by submit-a-bug passes.
    """
    clean, stripped = sanitize(text)
    return clean, stripped, instruction_findings(clean)


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

    TAP-IMPLEMENTS: req-dev-bugfix-untrusted-intake@1703dc8e0d68/8ca9e5ae9f91 (derivation) — the one reader: sanitise, extract the block, flag instruction-shaped text.

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
    return Extracted(
        data=data,
        sections=sections,
        disclosure=tail,
        stripped=stripped,
        findings=instruction_findings(human + "\n" + json.dumps(data, indent=1)),
    )


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


def author_gate(
    author_id: Any, author_type: Any, login: str = "", *, authors_path: Path | None = None
) -> tuple[bool, str]:
    """May ``submit-a-fix`` read this issue's body? True only for a maintainer session account.

    TAP-IMPLEMENTS: req-dev-bugfix-ownreports@9a46954b5131/966cd224714e (enforcement) — the one author check; it asks scripts/pr_session_identity.py.

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
        f"author check failed ({verdict}): {reason}. Until the sandbox exists, submit-a-fix reads only issues written by a "
        "maintainer session account (req-dev-bugfix-ownreports); bugs from other accounts wait for it. "
        "The issue body was not read."
    )


def filter_comments(
    comments: list[dict[str, Any]], issue_author_id: int, maintainer_ids: set[int]
) -> tuple[list[dict[str, Any]], int]:
    """Keep only comments written by the issue's author or a maintainer; return them and the count dropped.

    Identity is the numeric account id from GitHub's response. The text of a comment is not
    consulted, so a comment that claims to be from a maintainer is still an outsider's.
    """
    keep_ids = {issue_author_id, *maintainer_ids}
    kept = [c for c in comments if isinstance(c.get("user"), dict) and c["user"].get("id") in keep_ids]
    return kept, len(comments) - len(kept)


# --------------------------------------------------------------------------------------------
# Routing and the one component (req-dev-bugreport-route, -disclosure)
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


def _plugins(record: dict[str, Any]) -> list[dict[str, Any]]:
    return list((record.get("install") or {}).get("plugins", []))


def route_target(record: dict[str, Any], plugin_slug: str | None) -> tuple[str, str]:
    """Where a bug goes: ``(repository, note)``. A plugin's repository is read from the boot record, never inferred.

    Core or an unattributed failure goes to `unified-systems-com/tap`. A source outside
    unified-systems-com is third-party: the caller is told, and no repository of ours is returned
    (req-dev-bugreport-route-2, -3).
    """
    if not plugin_slug or plugin_slug == CORE_SLUG:
        return CORE_REPOSITORY, "core or unattributed failure"
    for plugin in _plugins(record):
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


def component_facts(
    record: dict[str, Any], plugin_slug: str | None, core_version: str, core_commit: str | None = None
) -> dict[str, Any]:
    """The one component's version block (req-dev-bugreport-disclosure-1): core, or one plugin of ours from the boot record."""
    if not plugin_slug or plugin_slug == CORE_SLUG:
        return {"kind": "core", "slug": CORE_SLUG, "version": core_version, "commit": core_commit}
    route_target(record, plugin_slug)  # refuses an unknown or third-party plugin
    plugin = next(p for p in _plugins(record) if p.get("slug") == plugin_slug)
    source = plugin.get("source") or {}
    return {
        "kind": "plugin",
        "slug": plugin_slug,
        "version": source.get("rev") or "unknown",
        "commit": source.get("commit"),
    }


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
    except_slug: str | None = None,
    observed: list[str] | None = None,
    build_facts: list[str] | None = None,
    profile_names: list[str] | None = None,
) -> list[tuple[str, str]]:
    """The reporter's own identifiers, as ``(kind, value)``. Held in memory; never written anywhere.

    From the spec: the instance's hostnames; the local username and home path; every installed
    plugin's rev and commit except the one component the report names (``except_slug``), and for
    plugins sourced outside unified-systems-com also every owner, repository name and slug; the
    boot profile's names; the host's build facts; and every observed value the agent recorded.
    Values shorter than ``MIN_DENY_LENGTH`` are dropped: they match ordinary words.
    """
    entries: list[tuple[str, str]] = []
    entries += [("instance hostname", h) for h in (hostnames or [])]
    for plugin in _plugins(record):
        source = plugin.get("source") or {}
        parsed = _owner_name(source.get("url", ""))
        slug = plugin.get("slug")
        if slug != except_slug:
            entries += [
                ("other component version", source.get("rev") or ""),
                ("other component commit", source.get("commit") or ""),
            ]
        if parsed is not None and parsed[0] == OUR_ORG:
            continue
        if parsed is not None:
            entries += [("third-party plugin owner", parsed[0]), ("third-party plugin repository", parsed[1])]
        if source.get("url"):
            entries.append(("third-party plugin source", source["url"]))
        if slug:
            entries.append(("third-party plugin slug", slug))
    entries += [("boot profile", p) for p in (profile_names or [])]
    if local_user:
        entries.append(("local username", local_user))
    if home_path:
        entries.append(("local home path", home_path))
    entries += [("build fact", b) for b in (build_facts or [])]
    entries += [("observed value", o) for o in (observed or [])]
    seen: set[tuple[str, str]] = set()
    out = []
    for kind, value in entries:
        value = (value or "").strip()
        if len(value) >= MIN_DENY_LENGTH and (kind, value) not in seen:
            seen.add((kind, value))
            out.append((kind, value))
    return out


def exempt_build_facts(deny: list[tuple[str, str]], data: dict[str, Any]) -> list[tuple[str, str]]:
    """A build fact the block carries beside its reason is not a hit (req-dev-bugreport-disclosure-2)."""
    carried = {b["fact"].strip().lower() for b in data.get("evidence_build_facts") or []}
    return [(k, v) for k, v in deny if not (k == "build fact" and v.lower() in carried)]


def tripwire(text: str, deny: list[tuple[str, str]]) -> list[Hit]:
    """Check outgoing text against the deny list and `CREDENTIAL_PATTERNS`; every hit blocks the send.

    TAP-IMPLEMENTS: req-dev-bugreport-tripwire@d0e7859d61c0/14d3c66dc3c6 (enforcement) — the one scan every outgoing report and search query passes.

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
    """The issue-search query is outbound before any consent: it passes the tripwire and a shape check.

    The shape check keeps it to a short run of plain words (a plugin slug, an error class, a model
    or field name); anything with quoting, operators or punctuation is refused as a hit.
    """
    hits = tripwire(query, deny)
    if not _VOCABULARY_QUERY_RE.match(query or ""):
        hits.append(Hit(1, "query shape", "not a short run of plain words from TAP's own vocabulary"))
    return hits


# --------------------------------------------------------------------------------------------
# The observed-values file (req-dev-bugreport-investigate-4, -tripwire-5, -6)
# --------------------------------------------------------------------------------------------


def observed_path(work_dir: Path | None = None) -> Path:
    return (work_dir or Path.cwd() / WORK_DIR_NAME) / OBSERVED_FILE_NAME


def record_observed(values: list[str], work_dir: Path | None = None) -> tuple[int, list[str]]:
    """Append values the agent read from the instance; return how many were kept and which were too short."""
    path = observed_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set(read_observed(work_dir))
    kept, short = [], []
    for raw in values:
        value = raw.strip()
        if not value:
            continue
        if len(value) < MIN_DENY_LENGTH:
            short.append(value)
        elif value not in existing:
            kept.append(value)
            existing.add(value)
    if kept:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("".join(f"{v}\n" for v in kept))
    return len(kept), short


def read_observed(work_dir: Path | None = None) -> list[str]:
    path = observed_path(work_dir)
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def finish(work_dir: Path | None = None) -> list[str]:
    """Remove the observed-values file and every consent record: nothing local outlives the skill (tripwire-6)."""
    base = work_dir or Path.cwd() / WORK_DIR_NAME
    removed = []
    if base.is_dir():
        for path in (observed_path(base), *base.glob("*.consent")):
            if path.is_file():
                path.unlink()
                removed.append(path.name)
    return removed


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
            raise BugReportError(
                f"screenshot {name}: only png, jpg and gif images are accepted (no video, nothing else)"
            )
        size = path.stat().st_size
        if not 0 < size <= MAX_ATTACHMENT_BYTES:
            raise BugReportError(f"screenshot {name} is {size} bytes; the limit is {MAX_ATTACHMENT_BYTES}")
        with path.open("rb") as handle:
            head = handle.read(16)
        if not any(head.startswith(magic) for magic in IMAGE_MAGIC[suffix]):
            raise BugReportError(f"screenshot {name} is not a real {suffix[1:]} image")
        found.append(
            Attachment(name=name, alt=item["description"], path=path, size=size, sha256=digest(path.read_bytes()))
        )
    return found


def bundle_digest(report: Path) -> str:
    """The hash a yes binds to: the report's bytes and every attachment's bytes, in the report's order.

    TAP-IMPLEMENTS: req-dev-bugreport-consent@ad3520a7dcfb/d7410ce1431f (derivation) — the one digest the typed yes names and the send re-derives; the record itself is kept by the host wrapper.

    With no attachments it is the report file's own sha256. Changing or adding an image changes it.
    The consent record is written by `scripts/bug-report consent` on the host, from a terminal, to a
    directory outside the worktree: neither the container nor an agent's granted tools can write it.
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


def send_manifest(report: Path) -> dict[str, Any]:
    """What the host snapshots before `gh` reads anything: each file's bytes named by sha256, and the digest the yes names.

    One read per file: the digest is derived from the same bytes the per-file hashes name, so the
    host can copy the files outside the worktree, re-hash the copies, and know the copies are the
    bytes that were verified and consented to.
    """
    raw = report.read_bytes()
    attachments = load_attachments(report, extract_report(raw.decode("utf-8")).data)
    blobs = [("report", report.name, raw, ""), *((a.name, a.name, a.path.read_bytes(), a.alt) for a in attachments)]
    if attachments:
        outer = hashlib.sha256()
        for label, _, blob, _ in blobs:
            outer.update(f"{label}\0{len(blob)}\0".encode())
            outer.update(blob)
        file_digest = outer.hexdigest()
    else:
        file_digest = digest(raw)
    return {
        "digest": file_digest,
        "files": [
            {"path": f"{WORK_DIR_NAME}/{name}", "sha256": digest(blob), "alt": alt} for _, name, blob, alt in blobs
        ],
    }


def report_deny(deny: list[tuple[str, str]], data: dict[str, Any]) -> list[tuple[str, str]]:
    """The deny list for one report: the one component's own version is not a hit, and carried build facts are exempt."""
    own = {data["component"]["version"], data["component"].get("commit") or ""}
    kept = [(k, v) for k, v in deny if not (k.startswith("other component") and v in own)]
    return exempt_build_facts(kept, data)


def prepare_send(report: Path, deny: list[tuple[str, str]]) -> dict[str, Any]:
    """Everything the container checks before `gh issue create`: a block render would accept, no hidden text, tripwire clean, our repository.

    The host wrapper adds the consent check (a record for exactly this digest, typed at a terminal).
    """
    text = report.read_text(encoding="utf-8")
    extracted = extract_report(text)
    validate_block(extracted.data)
    if extracted.stripped.any():
        raise BugReportError(
            f"the report holds hidden text ({extracted.stripped.describe()}); a report we send has none"
        )
    hits = tripwire(text, report_deny(deny, extracted.data))
    if hits:
        raise BugReportError(format_hits(hits))
    repo = require_ours(extracted.data["target_repository"])
    load_attachments(report, extracted.data)
    manifest = send_manifest(report)
    return {
        "repository": repo,
        "title": extracted.data["title"],
        "files": manifest["files"],
        "digest": manifest["digest"],
    }


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
    except OSError, KeyError:
        return None


def _profile_id() -> str | None:
    import os

    return os.environ.get("TAP_BOOT_PROFILE", "").strip() or None


def _local_deny(args: argparse.Namespace) -> list[tuple[str, str]]:
    profile = _profile_id()
    record = read_boot_record(profile)
    hostnames = [h for h in (args.host_name or []) if h]
    hostnames.append(socket.gethostname())
    try:
        from django.conf import settings

        hostnames += [h for h in settings.ALLOWED_HOSTS if h and h not in ("*", "localhost", "127.0.0.1")]
    except Exception:  # noqa: BLE001  # nosec B110 - settings are optional here; the deny list just has fewer entries
        pass
    user = args.host_user or _login_name()
    profiles = [p for p in (profile, record.get("profile_kind")) if p]
    return build_deny_list(
        record,
        hostnames=hostnames,
        local_user=user,
        home_path=args.host_home,
        except_slug=getattr(args, "component", None),
        observed=read_observed(),
        build_facts=[b for b in (args.host_fact or []) if b],
        profile_names=profiles,
    )


def _add_deny_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--host-user")
    p.add_argument("--host-home")
    p.add_argument("--host-name", action="append")
    p.add_argument(
        "--host-fact",
        action="append",
        help="a build fact of the host (OS, architecture, Docker version): denied unless the report carries it as evidence",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.bug_report", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema-path")
    p = sub.add_parser("render")
    p.add_argument("answers")
    _add_deny_args(p)
    p = sub.add_parser("route")
    p.add_argument("--plugin")
    p = sub.add_parser("component")
    p.add_argument("--plugin")
    p = sub.add_parser("observe")
    p.add_argument("values", nargs="*")
    sub.add_parser("finish")
    p = sub.add_parser("check")
    p.add_argument("file")
    _add_deny_args(p)
    p = sub.add_parser("search-query")
    p.add_argument("query")
    _add_deny_args(p)
    p = sub.add_parser("read-issue")
    p.add_argument(
        "file",
        help="a JSON issue under .bug-reports/, or - for stdin (the wrapper pipes gh api so nothing unsanitised touches disk)",
    )
    p = sub.add_parser("preview")
    p.add_argument("file")
    _add_deny_args(p)
    p = sub.add_parser("digest")
    p.add_argument("file")
    p = sub.add_parser("verify-send")
    p.add_argument("file")
    p.add_argument(
        "--print",
        dest="field",
        choices=("repository", "title", "digest"),
        help="print one field of the verified send, for the wrapper; without it the whole manifest as JSON",
    )
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


def _dispatch(args: argparse.Namespace) -> int:  # noqa: C901, PLR0911, PLR0912, PLR0915 - one flat switch over subcommands
    cmd = args.cmd
    if cmd == "schema-path":
        print(SCHEMA_PATH)
        return 0
    if cmd == "route":
        record = read_boot_record(_profile_id())
        repo, note = route_target(record, args.plugin)
        print(
            json.dumps(
                {"repository": repo, "note": note, "private_vulnerability_reporting": private_reporting_url(repo)}
            )
        )
        return 0
    if cmd == "component":
        from tap.core_version import core_tap_version

        record = read_boot_record(_profile_id())
        print(json.dumps(component_facts(record, args.plugin, core_tap_version()), indent=2, sort_keys=True))
        return 0
    if cmd == "observe":
        values = list(args.values) or list(sys.stdin.read().splitlines())
        n_kept, short = record_observed(values)
        print(
            f"recorded {n_kept} observed value(s) in {WORK_DIR_NAME}/{OBSERVED_FILE_NAME}; the file never leaves this session"
        )
        if short:
            print(
                f"not recorded (shorter than {MIN_DENY_LENGTH} characters, would match ordinary words): {', '.join(short)}"
            )
        return 0
    if cmd == "finish":
        removed = finish()
        print("removed: " + (", ".join(removed) or "nothing to remove"))
        return 0
    if cmd == "read-issue":
        raw = sys.stdin.read() if args.file == "-" else resolve_in_work_dir(args.file).read_text(encoding="utf-8")
        issue = json.loads(raw)
        prefix = "(pull request) " if "pull_request" in issue else ""
        clean, stripped, findings = read_as_data(f"{prefix}{issue.get('title') or ''}\n\n{issue.get('body') or ''}")
        print(
            json.dumps(
                {
                    "number": issue.get("number"),
                    "state": issue.get("state"),
                    "text": None if findings else clean,
                    "withheld": WITHHELD.format(n=len(findings)) if findings else None,
                    "stripped": stripped.describe(),
                    "findings": [{"line": f.line, "rule": f.rule, "excerpt": f.excerpt} for f in findings],
                    "stop": bool(findings),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2 if findings else 0
    if cmd == "gate-author":
        payload = json.loads(sys.stdin.read() or "{}")
        ok, reason = author_gate(payload.get("id"), payload.get("type"), str(payload.get("login") or ""))
        print(reason)
        return 0 if ok else 1
    if cmd == "intake":
        issue = json.loads(resolve_in_work_dir(args.issue).read_text(encoding="utf-8"))
        comments = json.loads(resolve_in_work_dir(args.comments).read_text(encoding="utf-8"))
        ok, reason = author_gate(
            (issue.get("user") or {}).get("id"),
            (issue.get("user") or {}).get("type"),
            str((issue.get("user") or {}).get("login") or ""),
        )
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
        findings = list(extracted.findings)
        for c in kept:
            text, _, comment_findings = read_as_data(str(c.get("body") or ""))
            clean_comments.append({"author_id": c["user"]["id"], "body": text})
            findings += [
                Finding(f.line, f"comment by {c['user']['id']}: {f.rule}", f.excerpt) for f in comment_findings
            ]
        print(
            json.dumps(
                {
                    "report": None if findings else extracted.data,
                    "sections": None if findings else extracted.sections,
                    "withheld": WITHHELD.format(n=len(findings)) if findings else None,
                    "stripped": extracted.stripped.describe(),
                    "comments_read": [] if findings else clean_comments,
                    "comments_not_read": dropped,
                    "findings": [{"line": f.line, "rule": f.rule, "excerpt": f.excerpt} for f in findings],
                    "stop": bool(findings),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2 if findings else 0
    if cmd == "render":
        answers = fill_descriptions(json.loads(resolve_in_work_dir(args.answers).read_text(encoding="utf-8")))
        text = render_report(answers)
        args.component = answers["component"]["slug"]
        hits = tripwire(text, report_deny(_local_deny(args), answers))
        if hits:
            raise BugReportError("not written: " + format_hits(hits))
        print(text, end="")
        return 0
    # The remaining subcommands build the deny list.
    if cmd == "search-query":
        hits = check_search_query(args.query, _local_deny(args))
        print(format_hits(hits))
        return 1 if hits else 0
    report = resolve_in_work_dir(args.file)
    text = report.read_text(encoding="utf-8")
    extracted = extract_report(text)
    validate_block(extracted.data)
    if cmd == "digest":
        file_digest = bundle_digest(report)
        print(json.dumps({"digest": file_digest, "phrase": consent_phrase(file_digest)}))
        return 0
    args.component = extracted.data["component"]["slug"]
    deny = report_deny(_local_deny(args), extracted.data)
    if cmd == "check":
        hits = tripwire(text, deny)
        print(format_hits(hits))
        return 1 if hits else 0
    if cmd == "preview":
        if extracted.stripped.any():
            raise BugReportError(
                f"the report holds hidden text ({extracted.stripped.describe()}); a report we send has none"
            )
        hits = tripwire(text, deny)
        print(format_hits(hits))
        if hits:
            return 1
        attachments = load_attachments(report, extracted.data)
        file_digest = bundle_digest(report)
        data = extracted.data
        target = data["target_repository"]
        print(
            f"File: {report}\nsha256 (the report plus every attachment, in order): {file_digest}\nTarget repository: {target}"
        )
        print(
            f"Discloses: {data['component']['kind']} {data['component']['slug']} at {data['component']['version']}, and nothing else about your build."
        )
        for carried in data["evidence_build_facts"]:
            print(f"Build fact carried as evidence: {carried['fact']} ({carried['reason']})")
        for number, att in enumerate(attachments, start=1):
            print(f"Attachment {number}: {att.path}  {att.size} bytes  sha256 {att.sha256}\n  {ATTACHMENT_WARNING}")
        print(
            "This issue will be PUBLIC and PERMANENT: GitHub keeps a public edit history, so editing it later does not remove earlier text."
        )
        print(
            "The agent wrote this report from its own investigation; you are the one who knows what in it would identify you. Read it all."
        )
        print(
            f"To send exactly these bytes, the reporter runs `scripts/bug-report consent {WORK_DIR_NAME}/{report.name}` in their own terminal and types: {consent_phrase(file_digest)}"
        )
        print("An agent cannot record that yes: the consent command refuses input that is not typed at a terminal.")
        print("----- BEGIN FILE -----")
        print(text, end="")
        print("----- END FILE -----")
        return 0
    if cmd == "verify-send":
        info = prepare_send(report, _local_deny(args))
        print(info[args.field] if args.field else json.dumps(info))
        return 0
    raise BugReportError(f"unknown subcommand {cmd}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
