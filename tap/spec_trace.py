"""Structured specification model + RID citation scanner.

TAP-IMPLEMENTS: req-docs-rid-integrity@9633efb7b6ee/f14909390c50 (derivation) — the one
    parser of the spec corpus; every RID definition and citation fact derives here.

The **one** parser of TAP's specification corpus (`req-docs-rid-integrity`). Three layers:

- **Definition side** — `load_corpus()` reads every spec into a `Requirement` per `RID:`
  heading, carrying its status, its acceptance-criteria ids (ACIDs), its normalized body,
  a content hash over that body, and its coverage disposition (the `Trace:` marker).
  `tap.guards.base.defined_requirement_rids()` delegates here rather than keeping a second
  regex pair, so "what RIDs exist" is derived once.
- **Reference side** — `collect_citations()` finds every `req-*` token cited in the living
  surfaces (first-party Python comments/docstrings, specs, non-archival docs, agent
  guides, scripts), and `collect_spec_markers()` finds every `@pytest.mark.spec(...)`
  argument. Both are what the integrity guards subtract the definition side from.
- **Ownership and accounting** — `collect_claims()` promotes chosen citations to
  implementation claims and checks both their fingerprints (spec hash and code hash);
  `collect_evidence()` derives per-requirement status from claims and test-cited ACIDs;
  `accounting()` places every requirement in exactly one Definition-of-Done bucket
  (`spec-tap-requirement-traceability.md`).

Design constraints, all inherited from the tree-scanner substrate (`spec-tap-tree-scanner.md`):
stdlib only, **no Django import**, safe to call pre-boot. The repo root arrives as a
parameter rather than a module global — `tap/` already derives that fact in five separate
places (`jsonfiles`, `boot_records`, `core_version`, `preboot`, `guards.base`) and this
module deliberately does not become the sixth.

Grammar note: a RID is `req-` plus kebab segments, optionally carrying a dotted facet
(`req-grid-table-classification.sec` — the security facet of a requirement). An ACID
appends `-<n>` to its parent (`req-grid-table-classification.sec-1`). The dot was absent
from the original resolver's character class, which silently truncated all 30 dotted RIDs
to their undotted stems and made every `.sec` citation look resolvable when it was not.

Illustrative RIDs in this module — and in any prose about the convention — use the
reserved `req-example-*` namespace, so documenting the scanner does not feed it phantom
citations. This file is its own first dogfood.
"""

from __future__ import annotations

import ast
import copy
import re
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tap.source_scan import first_party_source_roots, iter_parsed_sources, semantic_hash

# `req-` + kebab segments, plus zero or more dotted facets each itself kebab.
# Matches a RID (`req-example-a`, `req-example-a.sec`) and an ACID (`req-example-a-1`,
# `req-example-a.sec-1`) identically — the RID/ACID split is structural (see
# `load_corpus`), never lexical.
_RID_BODY = r"req-[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)*"

_RID_HEADING = re.compile(rf"^RID:\s*`?({_RID_BODY})`?", re.MULTILINE)
_TABLE_CELL = re.compile(rf"^\|\s*({_RID_BODY})\s*\|", re.MULTILINE)
_STATUS_LINE = re.compile(r"^Status:\s*`?([A-Za-z ]+?)`?\s*$", re.MULTILINE)
# The coverage-disposition marker (`req-tap-traceability-disposition`): a `Trace:` line
# beside `Status:` naming why a requirement legitimately maps to no code. Excluded from
# the content hash exactly as `Status:` is — metadata on its own lifecycle — and that
# exclusion landed BEFORE any marker did: bulk triage must never churn claim spec-hashes.
_TRACE_LINE = re.compile(r"^Trace:\s*`?([a-z-]+)`?\s*(?:—\s*(.+?))?\s*$", re.MULTILINE)
# Anything that looks like an attempted marker. A near-miss must fail loudly, not be
# skipped — the claim-shape lesson (`req-tap-traceability-disposition-1`). Anchored to
# line start so prose *about* the convention (always mid-line or backtick-prefixed in
# the owning spec) never trips it.
_TRACE_NEAR_MISS = re.compile(r"^\s*Trace[sd]?\s*:", re.IGNORECASE)
# A requirement's section ends at the next heading of level 3 or shallower. Level-4+
# headings (`#### Acceptance Criteria`, `#### Implementation`) are *inside* the
# requirement — stopping at those would cut every ACID table out of its own parent.
_SECTION_BOUNDARY = re.compile(r"^#{1,3}\s", re.MULTILINE)
# Both guards on this pattern exist because prose is hostile to token scanning:
#   * the lookbehind — a bare `\b` also fires after a hyphen, so a filename of the shape
#     `spec-req-<name>.md` would yield a phantom citation for its trailing segment;
#   * the lookahead — prose wraps mid-token, and a citation broken across a line
#     (ending `… is req-example-auth-` and resuming `model …` on the next) would otherwise
#     be captured as its truncated stem. A genuine citation is never immediately followed
#     by a hyphen: the pattern would have consumed that segment if a valid one followed.
_CITATION = re.compile(rf"(?<![\w-])({_RID_BODY})\b(?!-)")

# Reserved namespace for illustrative RIDs in prose, examples and templates. Documentation
# *about* the RID convention has to name RIDs that do not exist; without a reserved prefix
# those become permanent baseline entries that can never be remediated — the stale-exemption
# smell. Authors write `req-example-…` and the scanner skips it.
_PLACEHOLDER_PREFIX = "req-example"

# Archival corpora describe the past; a retired RID cited there is a *record*, not drift
# (`req-docs-rid-integrity-3` — the scope decision, made explicitly rather than by accident).
# `archive` is the home for retired-in-place SPECS (ledger row 3, ruled 2026-08-20): a spec
# retired where it stood scans as permanent dangling debt, so retirement means relocation to
# `specs/archive/` — the location is the fact, and no scanner needs a conditional.
_ARCHIVAL_DIR_PARTS = frozenset({"aar", "postmortems", "handoff", "handoffs", "archive"})

# --- implementation claims (`req-tap-traceability-claim`) ----------------------------

#: The closed role vocabulary (`req-tap-traceability-roles`). A requirement is often
#: realized at several layers, all legitimately; uniqueness is scoped per (rid, role).
CLAIM_ROLES = frozenset({"derivation", "enforcement", "surface"})

# Assembled by concatenation so this module — and anything quoting the grammar — never
# matches its own source. Same idiom as `tap/guards/known_dupes.py`.
_CLAIM_TOKEN = "TAP-" + "IMPLEMENTS"
#: What `implements-tag` mints in the code-hash position before the claim is placed. The
#: code hash can only be computed from the claim's *actual* placement, so minting emits
#: this and `--resync` stamps the real digest once the claim is in its docstring
#: (`req-tap-traceability-code-staleness-3`). A placeholder is well-formed but fails the
#: code-staleness guard, so an unstamped claim cannot be forgotten.
CODE_HASH_PLACEHOLDER = "-" * 12
_CLAIM_RE = re.compile(rf"{_CLAIM_TOKEN}:\s*({_RID_BODY})@([0-9a-f]{{12}})/([0-9a-f]{{12}}|-{{12}})\s*\(([a-z]+)\)")
# Anything that *looks* like an attempt. A near-miss must fail loudly rather than be
# skipped: a misspelled tag otherwise reports "no claim here" and the typo goes unnoticed
# — the documented failure mode of clippy's `SAFTEY:` hole (`req-tap-traceability-claim-3`).
_CLAIM_NEAR_MISS_RE = re.compile(r"TAP[-_ ]?IMPLEMENT(?:S|ED|ATION)?\b", re.IGNORECASE)

# The TEST modules of the convention build claim-shaped fixture strings; excluding them is
# the self-reference dodge `known_dupes.py` and `record_site.py` make. The convention's
# PRODUCTION modules are deliberately NOT excluded — they carry real claims on the
# traceability requirements they implement (the dogfood mandate), which the concatenated
# `_CLAIM_TOKEN` idiom makes safe: their prose never spells the needle.
_CONVENTION_MODULES = frozenset(
    {
        "tap/tests/test_spec_trace.py",
        "tap/tests/test_implements_claims.py",
    }
)


@dataclass(frozen=True)
class Claim:
    """A declaration that this code is the authoritative implementation of a requirement."""

    rid: str
    recorded_hash: str
    #: The code-side fingerprint the claim was stamped with (`@<spec-hash>/<code-hash>`),
    #: or `CODE_HASH_PLACEHOLDER` when minted but not yet resynced.
    recorded_code_hash: str
    role: str
    qualname: str
    path: Path
    lineno: int
    #: The claimed scope's *current* code hash, computed from the tree at collection time.
    code_hash: str

    @property
    def unstamped(self) -> bool:
        """Minted but never resynced — the code-hash position still holds the placeholder."""
        return self.recorded_code_hash == CODE_HASH_PLACEHOLDER

    def where(self, repo_root: Path) -> str:
        rel = self.path.relative_to(repo_root).as_posix()
        return f"{rel}:{self.lineno} ({self.qualname})"

    def key(self, repo_root: Path) -> str:
        """Uniqueness key — module, requirement, role. Never a line number.

        Keyed per *module* rather than per function so that a conditional definition
        (`if sys.version_info >= …:`) does not manufacture a false duplicate.
        """
        return f"{self.path.relative_to(repo_root).as_posix()}::{self.rid}::{self.role}"


@dataclass(frozen=True)
class MalformedClaim:
    """A line that attempted the claim grammar and missed."""

    text: str
    path: Path
    lineno: int

    def where(self, repo_root: Path) -> str:
        return f"{self.path.relative_to(repo_root).as_posix()}:{self.lineno}"


_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """Remove every docstring in the subtree, in place. Callers pass a deep copy."""
    for child in ast.walk(node):
        if not isinstance(child, _DOCSTRING_OWNERS):
            continue
        body = child.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            del body[0]
    return node


def code_hash_of(node: ast.AST) -> str:
    """The code-side fingerprint of a claimed scope.

    TAP-IMPLEMENTS: req-tap-traceability-code-staleness@edce7b8f372e/2c51494e66b3 (derivation) —
        the one derivation of the code hash; the collector, the resync tool and the guard all
        compare against what this computes.

    `semantic_hash` over a positions-stripped `ast.dump` of the scope — the callsite-identity
    recipe, so formatting, comments and pure moves never churn the digest while any semantic
    edit does. Every docstring in the subtree is excluded, not just the claimed scope's own:
    the claim line lives *inside* a docstring, so hashing docstrings would make stamping the
    hash change the hash (a fixpoint), and a nested claim's re-stamp would cascade-churn every
    enclosing claim. The accepted blind spot — a docstring-only edit does not churn — is
    documentation, not behavior.
    """
    stripped = _strip_docstrings(copy.deepcopy(node))
    return semantic_hash(ast.dump(stripped, include_attributes=False))


class _DocstringVisitor(ast.NodeVisitor):
    """Collects (qualname, docstring, lineno, node) for every module, class and function."""

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.found: list[tuple[str, str, int, ast.AST]] = []

    def _record(self, node: ast.AST, qualname: str) -> None:
        doc = ast.get_docstring(node, clean=False)  # type: ignore[arg-type]
        if not doc:
            return
        body = getattr(node, "body", None)
        lineno = getattr(body[0], "lineno", 1) if body else 1
        self.found.append((qualname, doc, lineno, node))

    def visit_Module(self, node: ast.Module) -> None:
        self._record(node, "<module>")
        self.generic_visit(node)

    def _visit_scoped(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self._record(node, ".".join(self.scope))
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_scoped(node, node.name)


def collect_claims(repo_root: Path, source_roots: list[Path]) -> tuple[list[Claim], list[MalformedClaim]]:
    """Every well-formed claim, and every line that tried to be one and failed.

    TAP-IMPLEMENTS: req-tap-traceability-claim@5b3a517c247e/eddeebeecca5 (derivation) — the one
        parser of the claim grammar; every guard and tool reads claims through this.

    Read from source via `ast.get_docstring`, never from `__doc__`: `python -OO` discards
    docstrings, and `functools.wraps` copies them, so a wrapper would silently inherit the
    claim of the function it wraps (`req-tap-traceability-claim-2`).
    """
    claims: list[Claim] = []
    malformed: list[MalformedClaim] = []

    for parsed in iter_parsed_sources(source_roots):
        if parsed.path.relative_to(repo_root).as_posix() in _CONVENTION_MODULES:
            continue
        visitor = _DocstringVisitor()
        visitor.visit(parsed.tree)
        for qualname, doc, doc_lineno, node in visitor.found:
            scope_hash: str | None = None  # computed once per claimed scope, only when claimed
            for offset, line in enumerate(doc.splitlines()):
                lineno = doc_lineno + offset
                match = _CLAIM_RE.search(line)
                if match is not None:
                    if scope_hash is None:
                        scope_hash = code_hash_of(node)
                    claims.append(
                        Claim(
                            rid=match.group(1),
                            recorded_hash=match.group(2),
                            recorded_code_hash=match.group(3),
                            role=match.group(4),
                            qualname=qualname,
                            path=parsed.path,
                            lineno=lineno,
                            code_hash=scope_hash,
                        )
                    )
                elif _CLAIM_NEAR_MISS_RE.search(line):
                    malformed.append(MalformedClaim(text=line.strip(), path=parsed.path, lineno=lineno))
    return claims, malformed


# --- coverage dispositions (`req-tap-traceability-disposition`) ----------------------

#: The closed exclusion vocabulary. Categories whose payload names a thing make it
#: mandatory (LOBSTER's rule: an exclusion whose target cannot be pointed at is an
#: assertion nothing can check). Doctrine, disputed, archival and mapped are DERIVED
#: buckets — a hand-written marker on any of them is a defect, never a fifth category.
DISPOSITION_CATEGORIES = frozenset({"process", "narrative", "non-python", "external"})
#: Categories whose payload is mandatory, mapped to what the payload must be.
_PAYLOAD_REQUIRED = {
    "non-python": "the implementing file's repo-relative path",
    "external": "the repo, plugin slug, or system name",
}


@dataclass(frozen=True)
class Disposition:
    """A requirement's documented reason for mapping to no code."""

    category: str
    payload: str | None


@dataclass(frozen=True)
class Requirement:
    """One requirement, as defined by an `RID:` heading in a spec."""

    rid: str
    spec_path: Path
    status: str | None
    acids: tuple[str, ...]
    body: str
    content_hash: str
    disposition: Disposition | None = None


@dataclass(frozen=True)
class SpecCorpus:
    """Every requirement, ACID, and bare table-row id defined across the specs."""

    requirements: dict[str, Requirement]
    acids: frozenset[str]
    other_ids: frozenset[str]
    #: Disposition defects found while parsing — near-miss lines, unknown categories,
    #: missing mandatory payloads, markers on derived buckets. Formatted `path:line — why`
    #: (or `rid — why` where the line is not the natural anchor); consumed by the
    #: disposition-integrity guard, which fails on any entry.
    trace_problems: tuple[str, ...] = ()

    @property
    def defined(self) -> frozenset[str]:
        """The flat union — what a citation must resolve against."""
        return frozenset(self.requirements) | self.acids | self.other_ids

    def parent_of(self, acid: str) -> str | None:
        """The requirement an ACID belongs to, or None if it is not an ACID."""
        for rid, req in self.requirements.items():
            if acid in req.acids:
                return rid
        return None


@dataclass(frozen=True)
class Citation:
    """One `req-*` token cited somewhere outside a spec's own definition."""

    token: str
    path: Path
    lineno: int

    def where(self, repo_root: Path) -> str:
        return f"{self.path.relative_to(repo_root).as_posix()}:{self.lineno}"


def spec_files(repo_root: Path) -> list[Path]:
    """Every spec Markdown file: top-level `specs/`, each app's, each in-repo plugin's."""
    files = sorted((repo_root / "specs").glob("*.md"))
    files += sorted(repo_root.glob("*/specs/*.md"))
    files += sorted(repo_root.glob("plugins/*/specs/*.md"))
    return files


# A generated block inside a requirement body (`<!-- BEGIN GENERATED … --> … <!-- END
# GENERATED … -->`) is machine-written by a sync command, so hashing it would drift a claim
# on every regeneration — the recurring ceremonial resync ai-guards hit on the Map block
# (2026-08-21). Same exclusion class as `Status:` and `Trace:`.
_GENERATED_BLOCK = re.compile(r"<!-- BEGIN GENERATED .*?<!-- END GENERATED [^>]*-->", re.DOTALL)


def _normalize(body: str) -> str:
    """Whitespace-collapsed requirement text — `Status:`/`Trace:` lines and generated blocks removed.

    All three are excluded deliberately: they are machine-moved metadata on their own
    lifecycles — status is derived from evidence, the disposition marker is applied in bulk
    during triage (`req-tap-traceability-disposition-2`), and a generated block is rewritten
    by its sync command whenever ANY surface changes. Hashing any of them would churn claims
    for changes with no requirement-meaning in them.
    """
    return " ".join(_TRACE_LINE.sub("", _STATUS_LINE.sub("", _GENERATED_BLOCK.sub("", body))).split())


def _parse_disposition(
    body: str, status: str | None, where: str, repo_root: Path, problems: list[str]
) -> Disposition | None:
    """One requirement's `Trace:` disposition, validated fail-closed.

    TAP-IMPLEMENTS: req-tap-traceability-disposition@54d4185ba383/d6ba4a775fc0 (derivation) — the
        one parser of the `Trace:` grammar and its closed vocabulary.

    Every defect lands in ``problems`` rather than raising: the corpus must stay loadable
    with a bad marker in it — the disposition-integrity guard is what turns the list red.
    """
    matches = _TRACE_LINE.findall(body)
    if not matches:
        return None
    if len(matches) > 1:
        problems.append(f"{where} — carries {len(matches)} `Trace:` lines; a requirement has one disposition")
    category, payload = matches[0][0], matches[0][1].strip() or None
    if category not in DISPOSITION_CATEGORIES:
        problems.append(f"{where} — `Trace:` category {category!r} is not one of {sorted(DISPOSITION_CATEGORIES)}")
        return None
    if category in _PAYLOAD_REQUIRED and payload is None:
        problems.append(f"{where} — `Trace: {category}` requires a payload: {_PAYLOAD_REQUIRED[category]}")
        return None
    if category == "non-python" and payload is not None and not (repo_root / payload).exists():
        problems.append(f"{where} — `Trace: non-python` names {payload!r}, which does not exist in the tree")
    # Derived buckets reject hand-written markers — one source per fact
    # (`req-tap-traceability-disposition-4`). Doctrine/Disputed derive from status; the
    # archival check derives from location (vacuously true today: `spec_files` yields no
    # archival paths, and retired-in-place specs use heading-style RIDs that never parse).
    if status in DOCTRINE_STATUSES or status in DISPUTED_STATUSES:
        problems.append(f"{where} — `Trace:` marker on a {status} requirement; that bucket is derived, never marked")
    return Disposition(category=category, payload=payload)


def load_corpus(repo_root: Path) -> SpecCorpus:
    """Parse every spec into the structured requirement model."""
    requirements: dict[str, Requirement] = {}
    all_cells: set[str] = set()
    claimed_acids: set[str] = set()
    trace_problems: list[str] = []

    for path in spec_files(repo_root):
        text = path.read_text(encoding="utf-8")
        all_cells.update(_TABLE_CELL.findall(text))
        rel = path.relative_to(repo_root).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _TRACE_NEAR_MISS.match(line) and not _TRACE_LINE.match(line):
                trace_problems.append(f"{rel}:{lineno} — attempts the `Trace:` grammar and misses: {line.strip()!r}")

        headings = list(_RID_HEADING.finditer(text))
        for index, match in enumerate(headings):
            rid = match.group(1)
            # The requirement's section runs to the next markdown heading, or to the next
            # `RID:` heading if one arrives first (some specs stack requirements densely).
            start = match.end()
            limit = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            next_section = _SECTION_BOUNDARY.search(text, start)
            if next_section is not None:
                limit = min(limit, next_section.start())
            body = text[start:limit]

            status_match = _STATUS_LINE.search(body)
            # An ACID is a table row *inside this requirement's section* whose id extends
            # the RID with `-<n>`. That co-location is what gives the parent/child relation.
            acids = tuple(
                sorted(
                    cell
                    for cell in _TABLE_CELL.findall(body)
                    if cell.startswith(f"{rid}-") and cell[len(rid) + 1 :].isdigit()
                )
            )
            claimed_acids.update(acids)
            status = status_match.group(1).strip() if status_match else None
            requirements[rid] = Requirement(
                rid=rid,
                spec_path=path,
                status=status,
                acids=acids,
                body=body,
                content_hash=semantic_hash(_normalize(body)),
                disposition=_parse_disposition(
                    body, status, f"{path.relative_to(repo_root).as_posix()} ({rid})", repo_root, trace_problems
                ),
            )

    other_ids = all_cells - set(requirements) - claimed_acids
    return SpecCorpus(
        requirements=requirements,
        acids=frozenset(claimed_acids),
        other_ids=frozenset(other_ids),
        trace_problems=tuple(trace_problems),
    )


def _is_archival(path: Path, repo_root: Path) -> bool:
    parts = path.relative_to(repo_root).parts
    return any(part in _ARCHIVAL_DIR_PARTS for part in parts)


def python_scan_roots(repo_root: Path) -> list[Path]:
    """First-party Python roots for citation scanning.

    `first_party_source_roots` returns the *apps* (a directory with `apps.py`), which
    deliberately excludes `tap/` — the project package. `tap/` is where the boot, secrets,
    guard and scanner machinery lives, and therefore where a large share of RID citations
    sit, so this scanner adds it back explicitly rather than silently under-covering.
    """
    roots = list(first_party_source_roots(repo_root))
    project_package = repo_root / "tap"
    if project_package.is_dir():
        roots.append(project_package)
    return roots


def living_markdown(repo_root: Path) -> list[Path]:
    """Docs and agent guides whose citations must resolve — archival corpora excluded."""
    docs_dir = repo_root / "docs"
    files = [p for p in sorted(docs_dir.rglob("*.md")) if not _is_archival(p, repo_root)] if docs_dir.is_dir() else []
    files += [p for p in (repo_root / "CLAUDE.md", repo_root / "AGENTS.md") if p.exists()]
    return files


def _iter_python_citations(repo_root: Path, roots: list[Path]) -> Iterator[Citation]:
    """Citations in first-party Python — docstrings via `ast`, comments via `tokenize`.

    Deliberately *not* every string literal: a RID inside an arbitrary string is data (a
    guard's own `rid` field, an error message, a test fixture), not a cross-reference.
    """
    for parsed in iter_parsed_sources(roots):
        for node in ast.walk(parsed.tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node, clean=False)
            if not doc:
                continue
            doc_start = getattr(node.body[0], "lineno", 1) if node.body else 1
            for offset, line in enumerate(doc.splitlines()):
                for token in _CITATION.findall(line):
                    yield Citation(token=token, path=parsed.path, lineno=doc_start + offset)
        try:
            with parsed.path.open("rb") as handle:
                for tok in tokenize.tokenize(handle.readline):
                    if tok.type != tokenize.COMMENT:
                        continue
                    for token in _CITATION.findall(tok.string):
                        yield Citation(token=token, path=parsed.path, lineno=tok.start[0])
        except tokenize.TokenError, SyntaxError, UnicodeDecodeError, OSError:
            continue


def _iter_text_citations(paths: list[Path]) -> Iterator[Citation]:
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for token in _CITATION.findall(line):
                yield Citation(token=token, path=path, lineno=lineno)


def collect_citations(repo_root: Path, source_roots: list[Path]) -> list[Citation]:
    """Every `req-*` citation across the living surfaces."""
    citations = list(_iter_python_citations(repo_root, source_roots))
    citations += list(_iter_text_citations(spec_files(repo_root)))
    citations += list(_iter_text_citations(living_markdown(repo_root)))
    return citations


def citation_key(citation: Citation, repo_root: Path) -> str:
    """Baseline key for a citation: file + token, deliberately **without** a line number.

    A dangling citation is remediated per (file, token) — you fix every occurrence in the
    file together — and a line-keyed baseline would churn on every unrelated edit above it
    (`spec-tap-callsite-identity.md`: the location is navigation, never the key).
    """
    return f"{citation.path.relative_to(repo_root).as_posix()}::{citation.token}"


def dangling_citations(repo_root: Path) -> list[Citation]:
    """Every citation whose `req-*` token resolves to no defined requirement or ACID."""
    corpus = load_corpus(repo_root)
    citations = collect_citations(repo_root, python_scan_roots(repo_root))
    return [c for c in citations if c.token not in corpus.defined and not c.token.startswith(_PLACEHOLDER_PREFIX)]


def malformed_claims(repo_root: Path) -> list[MalformedClaim]:
    """Lines that attempted the claim grammar and missed (`req-tap-traceability-claim-3`)."""
    return collect_claims(repo_root, python_scan_roots(repo_root))[1]


def invalid_claims(repo_root: Path) -> list[tuple[Claim, str]]:
    """Claims naming a requirement that does not exist, or a role outside the vocabulary."""
    corpus = load_corpus(repo_root)
    claims, _ = collect_claims(repo_root, python_scan_roots(repo_root))
    problems: list[tuple[Claim, str]] = []
    for claim in claims:
        requirement = corpus.requirements.get(claim.rid)
        if claim.rid not in corpus.defined:
            problems.append((claim, "names a requirement that does not exist"))
        elif claim.role not in CLAIM_ROLES:
            problems.append((claim, f"role {claim.role!r} is not one of {sorted(CLAIM_ROLES)}"))
        elif requirement is not None and requirement.status in DOCTRINE_STATUSES:
            # `Unwanted` coverage: the requirement never asked to be implemented.
            problems.append(
                (
                    claim,
                    "is standing doctrine (In Force) — doctrine is conformed to, not implemented. "
                    "Either the requirement is mis-labelled, or the checkable part of it should be "
                    "split out as its own requirement and claimed there",
                )
            )
    return problems


def stale_claims(repo_root: Path) -> list[tuple[Claim, str]]:
    """Claims whose recorded hash no longer matches their requirement (`Outdated`).

    TAP-IMPLEMENTS: req-tap-traceability-staleness@1f23dca53252/ba798e2267c4 (derivation) — the
        one comparison of a claim's recorded spec hash against the requirement's current one.

    Returns `(claim, expected_hash)`. A claim on a requirement that does not resolve is
    *not* reported here — that is `invalid_claims`' finding, and reporting it twice would
    make one defect look like two.
    """
    corpus = load_corpus(repo_root)
    claims, _ = collect_claims(repo_root, python_scan_roots(repo_root))
    stale: list[tuple[Claim, str]] = []
    for claim in claims:
        requirement = corpus.requirements.get(claim.rid)
        if requirement is None:
            continue
        if claim.recorded_hash != requirement.content_hash:
            stale.append((claim, requirement.content_hash))
    return stale


def drifted_claims(repo_root: Path) -> list[Claim]:
    """Claims whose recorded code hash no longer matches the claimed scope (`Drifted`).

    The inverse direction of `stale_claims`: there the *requirement* moved under the claim;
    here the *code* did, and the claim asserts verification of a scope that no longer exists
    as verified. Includes unstamped claims (the mint placeholder never matches a real digest)
    — consumers split the two via `Claim.unstamped`, because the operator message differs.

    Deliberately independent of the spec corpus: a claim whose requirement fails to resolve
    is `invalid_claims`' finding, but its code can drift too, and those are different defects
    on different ends of the link.
    """
    claims, _ = collect_claims(repo_root, python_scan_roots(repo_root))
    return [c for c in claims if c.recorded_code_hash != c.code_hash]


def duplicate_claim_groups(repo_root: Path) -> dict[tuple[str, str], list[Claim]]:
    """`(rid, role)` -> claims, for every pair claimed by more than one module.

    TAP-IMPLEMENTS: req-tap-traceability-uniqueness@d2f65eaa2072/82c65736b53e (derivation) — the
        one derivation of "which claims collide"; the uniqueness guard only formats what
        this returns.

    Within-module repeats collapse first: a conditional definition legitimately declares
    the same claim twice in one file (`req-tap-traceability-uniqueness-3`).
    """
    claims, _ = collect_claims(repo_root, python_scan_roots(repo_root))
    by_pair: dict[tuple[str, str], dict[str, Claim]] = {}
    for claim in claims:
        module = claim.path.relative_to(repo_root).as_posix()
        by_pair.setdefault((claim.rid, claim.role), {}).setdefault(module, claim)
    return {pair: list(mods.values()) for pair, mods in by_pair.items() if len(mods) > 1}


# --- evidence and derived status (`req-tap-traceability-status`) ----------------------

#: Declared statuses that assert the requirement is built. A claim of `Verified` is the
#: only one this module gates on, because it is the only one that asserts *verification*.
_BUILT_STATUSES = frozenset({"Implemented", "Verified"})
#: Statuses that assert the requirement is NOT settled — future or in-flight work whose
#: mapping falls due when it lands as `Implemented`. All template-canonical except
#: `Backlog` (corpus-established). `Refactoring` belongs here: "in the process of being
#: re-worked" is in-flight by its own words, and its evidence (which may exist mid-rework)
#: is reported, never failed.
_UNBUILT_STATUSES = frozenset({"Proposed", "Backlog", "In Development", "Approved for Development", "Refactoring"})
#: Statuses that assert the requirement has been WITHDRAWN — no mapping is ever expected,
#: and its history is the record. (A withdrawal the implementation appears to contradict
#: is a `Disputed` case, not a retired one — see the sphinx capability-blocks dispute.)
RETIRED_STATUSES = frozenset({"Deprecated", "Deprecating", "Retired"})
#: Standing doctrine — in effect now, never "completed", and expecting *conformance* from
#: other work rather than an implementation of its own. The convention is Python's, whose
#: PEP 1 gives Informational and Process PEPs a status of `Active` precisely because they
#: "are never meant to be completed"; Ethereum calls the same state `Living`, and IETF's
#: BCP series has no maturity ladder at all because doctrine is in force or it is not.
#:
#: A doctrine requirement is neither built nor unbuilt, so it belongs in **neither**
#: coverage bucket. Counting it as built-without-evidence was the miscount that made the
#: unevidenced number unreadable.
DOCTRINE_STATUSES = frozenset({"In Force"})
#: Contested — the spec's statement and the implementation disagree, and a human has not
#: yet ruled which is right (`req-tap-traceability-disputed`). A fourth bucket, disjoint
#: from all three above, because every existing bucket's behavior is wrong for a dispute:
#: `built` would blend it into awaiting-evidence debt (or count a claim as satisfaction),
#: `unbuilt` treats evidence as an anomaly when a dispute *should* carry a pointer to the
#: contested code, and `doctrine` rejects claims outright — erasing that pointer. Claims
#: on a disputed requirement are pointers, never resolution; the only exits are a human
#: ruling that edits the spec (hash changes, claims report `Outdated`, re-verify) or the
#: code (re-stamp after review). Both exits force the re-read. The count trends to zero.
DISPUTED_STATUSES = frozenset({"Disputed"})


@dataclass(frozen=True)
class Evidence:
    """What the tree can actually show about a requirement."""

    rid: str
    declared: str | None
    implemented_by: tuple[Claim, ...]
    verified_acids: tuple[str, ...]

    @property
    def classes(self) -> int:
        """How many *independent* evidence classes exist — implementation, verification.

        Two is the bar for `Verified`. A requirement evidenced only by its own
        implementation is not verified: the implementation asserting it works is the claim
        under test, not a check on it. SQLite renders a requirement green only at 2+
        independent evidence classes for exactly this reason.
        """
        return bool(self.implemented_by) + bool(self.verified_acids)

    @property
    def derived(self) -> str:
        """The status the evidence supports, independent of what the spec declares."""
        if self.implemented_by and self.verified_acids:
            return "Verified"
        if self.implemented_by:
            return "Implemented"
        if self.verified_acids:
            return "Tested"
        return "Unevidenced"


def collect_evidence(repo_root: Path) -> dict[str, Evidence]:
    """Per-requirement evidence: implementation claims and verified acceptance criteria.

    TAP-IMPLEMENTS: req-tap-traceability-status@c380067ae093/9ddc8365896e (derivation) — the one
        derivation of "what the tree can show about a requirement"; derived status, the
        gate and both reports read from this.
    """
    corpus = load_corpus(repo_root)
    roots = python_scan_roots(repo_root)
    claims, _ = collect_claims(repo_root, roots)
    marked = {m.token for m in collect_spec_markers(roots)}

    by_rid: dict[str, list[Claim]] = {}
    for claim in claims:
        by_rid.setdefault(claim.rid, []).append(claim)

    evidence: dict[str, Evidence] = {}
    for rid, requirement in corpus.requirements.items():
        evidence[rid] = Evidence(
            rid=rid,
            declared=requirement.status,
            implemented_by=tuple(by_rid.get(rid, ())),
            verified_acids=tuple(sorted(acid for acid in requirement.acids if acid in marked)),
        )
    return evidence


def _evidence_or_scan(repo_root: Path, evidence: dict[str, Evidence] | None) -> dict[str, Evidence]:
    """Reuse a caller's scan when it has one — each `collect_evidence` walks the whole tree."""
    return collect_evidence(repo_root) if evidence is None else evidence


def unearned_verified(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Requirements declaring `Verified` without two independent evidence classes.

    The one hard gate in the status work. It deliberately does **not** fault a requirement
    for lacking a claim — claims are opt-in and scarce by design
    (`req-tap-traceability-scope-1`), so faulting their absence would contradict the
    convention. What it faults is the strongest possible assertion — "this is verified" —
    made without the evidence that would justify it.
    """
    return [e for e in _evidence_or_scan(repo_root, evidence).values() if e.declared == "Verified" and e.classes < 2]


def under_declared(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Requirements carrying evidence while still declared unbuilt.

    Reported, never failed: a requirement can legitimately be `Proposed` while part of it
    is built, and a doctrine requirement is cited as guidance rather than implemented.
    """
    return [e for e in _evidence_or_scan(repo_root, evidence).values() if e.declared in _UNBUILT_STATUSES and e.classes]


def doctrine(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Requirements in force as standing doctrine — outside the coverage question entirely."""
    return [e for e in _evidence_or_scan(repo_root, evidence).values() if e.declared in DOCTRINE_STATUSES]


def disputed(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Requirements whose spec text and implementation disagree, awaiting a human ruling.

    TAP-IMPLEMENTS: req-tap-traceability-disputed@1f95cfa95af4/041c0d3d59c5 (derivation) — the
        one derivation of the disputed bucket; the report section and the accounting read it.

    Listed with whatever evidence they carry — a dispute *should* name the contested code
    via a claim — but evidence never resolves a dispute, so nothing here feeds the
    built/unbuilt coverage counts (`req-tap-traceability-disputed`).
    """
    return [e for e in _evidence_or_scan(repo_root, evidence).values() if e.declared in DISPUTED_STATUSES]


def claimed_doctrine(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Doctrine requirements carrying an implementation claim — `Unwanted` coverage.

    The inverse check, and the thing that keeps the doctrine label from decaying into
    decoration. OpenFastTrace fires `Unwanted` when an item covers something that *did not
    ask* for coverage; Doorstop warns when a non-normative item has links; NIST's published
    catalogue has zero of 3,707 assessment objectives pointing at a guidance part. The
    lesson those three share: **a flag that only ever removes a check is a flag nobody
    maintains.** Marking a requirement as doctrine has to cost something, and what it costs
    is the ability to claim it.

    A doctrine requirement is conformed to, not implemented. If something genuinely *is*
    the one derivation of a doctrine requirement's fact, that is a signal the requirement
    was mis-labelled — or that a checkable part of it should be split out as its own
    requirement, which is what PCI does with Applicability Notes and NIST with ODPs.
    """
    return [e for e in doctrine(repo_root, evidence) if e.implemented_by]


def unevidenced_built(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Requirements declared built with no evidence at all.

    The honest headline number, and deliberately **not** a failure: with claims opt-in,
    this measures how much of the corpus has been *targeted*, not how much is wrong.
    """
    return [
        e for e in _evidence_or_scan(repo_root, evidence).values() if e.declared in _BUILT_STATUSES and not e.classes
    ]


# --- full-corpus accounting (`req-tap-traceability-accounting`) ----------------------

#: The disjoint, total bucket vocabulary. Every requirement lands in exactly one.
#: `unbuilt` and `retired` are derived from status: a requirement declaring itself future
#: work (or withdrawn) has, by its own account, nothing to map — that is a disposition the
#: status already documents, never a gap. The load-bearing consequence: flipping a
#: requirement to `Implemented` without evidence or a `Trace:` exclusion moves it INTO
#: Unaccounted, where the ratchet fails it as a new entry — the Definition of Done is
#: enforced at the moment a requirement claims to be done.
ACCOUNTING_BUCKETS = ("mapped", "excluded", "doctrine", "disputed", "unbuilt", "retired", "unaccounted")


def contradicted_dispositions(repo_root: Path, evidence: dict[str, Evidence] | None = None) -> list[Evidence]:
    """Excluded requirements that carry evidence anyway (`req-tap-traceability-disposition-3`).

    Marking a requirement excluded costs the ability to claim it — the `claimed_doctrine`
    lesson: a flag that only ever removes a check is a flag nobody maintains. Resolving the
    contradiction means removing whichever side is wrong, and both edits are review-visible.
    """
    corpus = load_corpus(repo_root)
    return [
        e
        for e in _evidence_or_scan(repo_root, evidence).values()
        if e.classes and (req := corpus.requirements.get(e.rid)) is not None and req.disposition is not None
    ]


def bucket_of(requirement: Requirement, evidence: Evidence) -> str:
    """The one accounting bucket this requirement lands in — disjoint and total.

    TAP-IMPLEMENTS: req-tap-traceability-accounting@aa39264f56c6/87dd8028e43c (derivation) — the
        one derivation of the bucket; the ratchet's measure and the report both call this.

    A derivation, never a judgment call: doctrine and disputed derive from status, mapped
    from evidence, excluded from the disposition marker, and what remains is Unaccounted.
    (Evidence outranks a disposition only for bucketing determinism — carrying both is a
    contradiction the disposition-integrity guard fails independently.)
    """
    if requirement.status in DOCTRINE_STATUSES:
        return "doctrine"
    if requirement.status in DISPUTED_STATUSES:
        return "disputed"
    if evidence.classes:
        return "mapped"
    if requirement.disposition is not None:
        return "excluded"
    if requirement.status in _UNBUILT_STATUSES:
        return "unbuilt"
    if requirement.status in RETIRED_STATUSES:
        return "retired"
    # A status outside every vocabulary (drift: "Partial", "Open", a missing Status line)
    # lands here deliberately — normalizing it is triage work the count must surface.
    return "unaccounted"


def accounting(repo_root: Path) -> dict[str, str]:
    """Every corpus requirement's bucket, rid -> bucket (`req-tap-traceability-accounting-1`)."""
    corpus = load_corpus(repo_root)
    evidence = collect_evidence(repo_root)
    return {rid: bucket_of(req, evidence[rid]) for rid, req in corpus.requirements.items()}


def unaccounted_rids(repo_root: Path) -> set[str]:
    """The Unaccounted set — the ratchet's measure, keyed by RID alone (location is navigation)."""
    return {rid for rid, bucket in accounting(repo_root).items() if bucket == "unaccounted"}


ACCOUNTING_BEGIN = "<!-- BEGIN GENERATED ACCOUNTING — manage.py guards --sync-accounting -->"
ACCOUNTING_END = "<!-- END GENERATED ACCOUNTING -->"


def render_accounting_markdown(repo_root: Path) -> str:
    """The full-corpus accounting — every requirement in one bucket, with a denominator.

    TAP-IMPLEMENTS: req-tap-traceability-accounting@aa39264f56c6/439d52dc82ee (surface) — the
        committed, drift-tested progress bar the Definition of Done is read from.

    The complement of the evidence report: that one is read for contradictions, this one
    for progress. The headline is the Unaccounted count — the Definition of Done's
    progress bar — and the per-spec sub-counts drive triage batching.
    """
    corpus = load_corpus(repo_root)
    evidence = collect_evidence(repo_root)
    buckets = {rid: bucket_of(req, evidence[rid]) for rid, req in corpus.requirements.items()}

    by_spec: dict[str, dict[str, int]] = {}
    for rid, bucket in buckets.items():
        spec = corpus.requirements[rid].spec_path.relative_to(repo_root).as_posix()
        row = by_spec.setdefault(spec, dict.fromkeys(ACCOUNTING_BUCKETS, 0))
        row[bucket] += 1

    totals = dict.fromkeys(ACCOUNTING_BUCKETS, 0)
    for row in by_spec.values():
        for bucket, count in row.items():
            totals[bucket] += count

    excluded_by_category: dict[str, int] = {}
    for req in corpus.requirements.values():
        if buckets[req.rid] == "excluded" and req.disposition is not None:
            excluded_by_category[req.disposition.category] = excluded_by_category.get(req.disposition.category, 0) + 1
    category_note = (
        " (" + ", ".join(f"{c} {n}" for c, n in sorted(excluded_by_category.items())) + ")"
        if excluded_by_category
        else ""
    )

    lines = [
        ACCOUNTING_BEGIN,
        "",
        f"**{len(buckets)}** requirements · **{totals['mapped']}** mapped · "
        f"**{totals['excluded']}** excluded{category_note} · "
        f"**{totals['doctrine']}** doctrine · **{totals['disputed']}** disputed · "
        f"**{totals['unbuilt']}** unbuilt · **{totals['retired']}** retired · "
        f"**{totals['unaccounted']} Unaccounted**.",
        "",
        "The Unaccounted count is the Definition of Done's progress bar: it only moves down "
        "(the committed baseline grandfathers existing debt; a new requirement without a "
        "disposition fails immediately). A grandfathered entry is debt, not license — every "
        "Unaccounted requirement still needs a mapping or a documented exclusion. **Unbuilt** "
        "and **retired** derive from status — a requirement declaring itself future work or "
        "withdrawn has, by its own account, nothing to map; the moment one flips to "
        "`Implemented` without evidence or an exclusion it becomes a NEW Unaccounted entry "
        "and the ratchet fails, so claiming done is where the Definition of Done is enforced.",
        "",
        "| Spec | Reqs | Mapped | Excluded | Doctrine | Disputed | Unbuilt | Retired | Unaccounted |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for spec in sorted(by_spec, key=lambda s: (-by_spec[s]["unaccounted"], s)):
        row = by_spec[spec]
        lines.append(
            f"| `{spec}` | {sum(row.values())} | {row['mapped']} | {row['excluded']} | "
            f"{row['doctrine']} | {row['disputed']} | {row['unbuilt']} | {row['retired']} | "
            f"{row['unaccounted']} |"
        )
    lines += ["", ACCOUNTING_END]
    return "\n".join(lines)


EVIDENCE_BEGIN = "<!-- BEGIN GENERATED EVIDENCE — manage.py guards --sync-evidence -->"
EVIDENCE_END = "<!-- END GENERATED EVIDENCE -->"


def render_evidence_markdown(repo_root: Path) -> str:
    """The generated evidence report — declared status against what the tree can show.

    TAP-IMPLEMENTS: req-tap-traceability-status@c380067ae093/1b1e9ca6ad5e (surface) — the
        committed, drift-tested report is the convention's visible consumer.

    Deliberately compact: it lists only requirements that *have* evidence, plus the
    contradictions, rather than all ~1,100 rows. A report nobody can read is a report
    nobody reads, and the tag's whole value depends on this being looked at.
    """
    evidence = collect_evidence(repo_root)  # one tree walk; every helper below reuses it
    evidenced = sorted((e for e in evidence.values() if e.classes), key=lambda e: e.rid)
    built_without = unevidenced_built(repo_root, evidence)
    under = sorted(under_declared(repo_root, evidence), key=lambda e: e.rid)
    unearned = sorted(unearned_verified(repo_root, evidence), key=lambda e: e.rid)

    doctrinal = doctrine(repo_root, evidence)
    contested = sorted(disputed(repo_root, evidence), key=lambda e: e.rid)
    lines = [
        EVIDENCE_BEGIN,
        "",
        f"**{len(evidence)}** requirements · **{len(doctrinal)}** standing doctrine · "
        f"**{len(contested)}** disputed · "
        f"**{len(evidenced)}** carry evidence · "
        f"**{sum(1 for e in evidenced if e.classes == 2)}** carry both classes · "
        f"**{len(built_without)}** declared built with none.",
        "",
        "Separate facts, deliberately not blended into one percentage. **Doctrine** is "
        'outside the coverage question — in force now, never "completed", expecting '
        "conformance rather than an implementation. **Disputed** marks a spec-versus-"
        "implementation disagreement awaiting a human ruling — its claims are pointers to "
        "the contested code, never resolution, and the count should trend to zero. "
        "**Declared built with none** is context, "
        "not a defect list: claims are opt-in and scarce by design "
        "(`req-tap-traceability-scope`), so it measures how much of the corpus has been "
        "deliberately targeted, not how much is wrong. Collapsing these into a single "
        "coverage score is what makes such a score meaningless.",
        "",
        "| Requirement | Declared | Derived | Implementation | Verified by |",
        "| --- | --- | --- | --- | --- |",
    ]
    for e in evidenced:
        impl = ", ".join(f"`{c.qualname}`" for c in e.implemented_by) or "—"
        acids = ", ".join(f"`{a}`" for a in e.verified_acids) or "—"
        lines.append(f"| `{e.rid}` | {e.declared or '—'} | {e.derived} | {impl} | {acids} |")

    lines += [
        "",
        "**Disputed** — the spec and the implementation disagree; each entry pairs with a "
        "row in the requirement-review ledger and a section in its owning spec "
        "(`req-tap-traceability-disputed`):",
    ]
    if contested:
        lines += ["", "| Requirement | Contested code (claims) | Verified by |", "| --- | --- | --- |"]
        for e in contested:
            impl = ", ".join(f"`{c.qualname}`" for c in e.implemented_by) or "—"
            acids = ", ".join(f"`{a}`" for a in e.verified_acids) or "—"
            lines.append(f"| `{e.rid}` | {impl} | {acids} |")
    else:
        lines += ["", "None."]

    lines += [
        "",
        "**Declared unbuilt, but evidence exists** — reported, never failed; a "
        "requirement can be partly built, and a doctrine requirement is cited as guidance:",
    ]
    if under:
        lines += ["", "| Requirement | Declared | Derived |", "| --- | --- | --- |"]
        lines += [f"| `{e.rid}` | {e.declared} | {e.derived} |" for e in under]
    else:
        lines += ["", "None."]

    lines += [
        "",
        "**Declared `Verified` without two evidence classes** — this one fails " "(`req-tap-traceability-status`):",
    ]
    lines += ["", "None." if not unearned else ""]
    lines += [f"- `{e.rid}` (evidence classes: {e.classes})" for e in unearned]
    lines += ["", EVIDENCE_END]
    return "\n".join(lines)


def unresolvable_markers(repo_root: Path) -> list[Citation]:
    """Every `@pytest.mark.spec(...)` argument that resolves to nothing defined."""
    corpus = load_corpus(repo_root)
    markers = collect_spec_markers(python_scan_roots(repo_root))
    return [m for m in markers if m.token not in corpus.defined]


def collect_spec_markers(source_roots: list[Path]) -> list[Citation]:
    """Every `@pytest.mark.spec("<acid>")` argument, read from the AST.

    Test modules are parsed, never imported — the scanner runs pre-boot and must not
    trigger Django setup or fixture collection as a side effect.
    """
    markers: list[Citation] = []
    for parsed in iter_parsed_sources(source_roots):
        for node in ast.walk(parsed.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "spec":
                continue
            owner = func.value
            if not (isinstance(owner, ast.Attribute) and owner.attr == "mark"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    markers.append(Citation(token=arg.value, path=parsed.path, lineno=node.lineno))
    return markers
