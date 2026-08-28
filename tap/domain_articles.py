"""Scanner for **domain articles** — the per-concept background layer beside the models.

TAP's documentation has three layers and this module owns the third. Specs say what
TAP *requires* of a concept; docs say how to *operate* it; neither says what the
concept **is in the world**. That gap cost real time: `bypass_actors` needs WRITE
access to read, PAT grants are App-only, a GitHub Actions *job* is an execution and
not a declaration — each was rediscovered by executing a call, and none of them had
anywhere to live. A domain article is that home: one markdown file per node type and
per edge type, recording what the concept is, why it is modelled this way, what its
identity is, what it deliberately excludes, and — the expensive part — what credential
and permission actually populate it.

Articles are **markdown beside the models** (`<plugin>/domain/<stem>.md`), not HTML and
not `specs/`. They are reference material read next to code by three audiences —
future maintainers, outside contributors, and Player 3 (`spec-ai-integration.md`), the
AI assistants that must reason about the domain without GitHub's API reference in
context. Machine-first: greppable, diffable, and guard-checkable. Rendering them
prettily inside TAP is a later, separate concern.

This module is the measurement half; `tap.guards.domain_articles` is the ratcheting
enforcement half. It is deliberately **Django-free and plugin-agnostic**
(`req-tap-plugin-validation-distribution-principle`): it discovers subjects by parsing
source with `ast` and reading `*.edge.json`, so it runs at pytest-collection time,
inside a pre-boot gate, or from a plugin's own suite in its own repo — and it names no
plugin slug anywhere.

The load-bearing check is field coverage. Every key in a model's `FIELD_CRUD_SCHEMA`
must be explained in its article, so the article cannot silently drift from the model
it describes — the derive-a-fact-once discipline (CLAUDE.md) applied to documentation.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from tap.source_scan import first_party_source_roots

#: Article directory inside an owner package.
ARTICLE_DIR = "domain"
#: Dimension articles live one level down, so a dotted dimension key can never
#: collide with a node or edge stem in the same namespace.
DIMENSION_DIR = "dimensions"

#: Sections every article must carry, in the order an article should present them.
#: The first five are the authored core (what it is, why, and every field); the rest
#: each earn their place from a rediscovery that cost time. `Identity` because a natural
#: key is load-bearing and can never change, and is exactly what gets forgotten.
#: `Boundaries` because recording that a question was asked stops it being re-litigated.
#: `Neutrality` because forge-neutral-vs-vendor-specific is a modelling decision with
#: consequences. `Observability` because what a credential can actually see is the single
#: most expensive fact to rediscover, and documentation is not a reliable source for it.
COMMON_SECTIONS: tuple[str, ...] = (
    "Blurb",
    "Purpose",
    "Goals",
    "Identity",
    "Boundaries",
    "Neutrality",
    "Observability",
    "Authoritative Source",
    "Prior Art",
)

#: Node articles close with the per-field explanation; edge articles with their
#: endpoints; dimension articles with the closed set of values they admit.
NODE_SECTIONS: tuple[str, ...] = (*COMMON_SECTIONS, "Fields")
EDGE_SECTIONS: tuple[str, ...] = (*COMMON_SECTIONS, "Endpoints")
DIMENSION_SECTIONS: tuple[str, ...] = (*COMMON_SECTIONS, "Values")

#: Keys the Authoritative Source section must state, one per `- **Key:** value` line.
#: Pinned **per model**, not in a global source register, so the update question is
#: answerable with one grep: "this standard revised — which of our models does it
#: touch?" That seam is what a future scheduled research pass hangs off, and it only
#: works if the pin lives on the model.
SOURCE_KEYS: tuple[str, ...] = ("Source", "Version", "Retrieved")

_SOURCE_KEY_RE = re.compile(r"^\s*[-*]\s*\*\*(?P<key>[A-Za-z ]+?)\*\*\s*:|^\s*[-*]\s*\*\*(?P<key2>[A-Za-z ]+?):\*\*")
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
_URL_RE = re.compile(r"https?://")
#: A Prior Art entry is a change-tracking record, so a bare URL is not enough: it must
#: carry the version or date it describes. Accepts an ISO date, a year, or a dotted version.
_PINNED_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\b(?:19|20)\d{2}\b|\bv?\d+\.\d+")

KIND_NODE = "node"
KIND_EDGE = "edge"
#: A dimension key declared by a model's `DEFAULT_DIMENSIONS` or an edge's
#: `default_dimensions`. A dimension is a *vocabulary*, and an unexplained
#: vocabulary is a problem wherever it is declared — so unlike node and edge
#: articles, dimension articles are owed by `tap_*` apps too.
KIND_DIMENSION = "dimension"
#: An article with no registered type behind it (see `_orphan_findings`).
KIND_ORPHAN = "orphan"

#: What an article must account for, per kind — used in finding ids and messages.
_TERM_NAME = {KIND_NODE: "field", KIND_EDGE: "dimension", KIND_DIMENSION: "value"}


@dataclass(frozen=True)
class DomainSubject:
    """A concept that owes an article: one node type or one edge type.

    `stem` is the article's filename stem — the owner-local half of the slug, so an
    article is named for the concept (`github_workflow.md`) rather than repeating its
    plugin prefix in every path.
    """

    kind: str
    slug: str
    stem: str
    #: The terms the article must explain: a node's `FIELD_CRUD_SCHEMA` keys, or a
    #: dimension's admitted values. `None` means the declaration exists but could not
    #: be resolved statically — reported as a finding, never silently read as empty,
    #: because an empty set would pass the coverage check while proving nothing.
    fields: frozenset[str] | None
    declared_in: Path


@dataclass(frozen=True)
class Finding:
    """One unmet obligation on one subject.

    `problem` is the drift-proof identity: a section name, a field name, a source key —
    never a line number (`spec-tap-callsite-identity.md`: location is navigation, never
    the key). `detail` is the human remediation text and is not part of any key.
    """

    subject: DomainSubject
    article: Path
    problem: str
    detail: str = ""


def plugin_roots(project_root: Path) -> list[Path]:
    """Every in-repo plugin source root — the owners that owe domain articles.

    Scoped to plugins deliberately. Plugins model concepts that exist in the world
    independent of TAP (a workflow run, a ruleset, an OIDC issuer) and that is what a
    domain article explains. The `tap_*` apps model TAP's own furniture — pages, panels,
    arrangements, batches — which their specs already define and about which there is no
    outside world to research. Widening this scope would create a baseline that could
    never honestly drain.
    """
    return [root for root in first_party_source_roots(project_root) if (root / "tap-plugin.toml").exists()]


def _dict_keys(node: ast.expr) -> frozenset[str] | None:
    """String keys of a dict literal, or None if `node` is not one."""
    if not isinstance(node, ast.Dict):
        return None
    return frozenset(k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))


def _str_pairs(node: ast.expr) -> dict[str, str] | None:
    """String key/value pairs of a dict literal, or None if `node` is not one.

    Dimensions need the values, not just the keys — the whole point of a dimension
    article is the closed set of values it admits.
    """
    if not isinstance(node, ast.Dict):
        return None
    return {
        k.value: v.value
        for k, v in zip(node.keys, node.values, strict=False)
        if isinstance(k, ast.Constant)
        and isinstance(k.value, str)
        and isinstance(v, ast.Constant)
        and isinstance(v.value, str)
    }


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level `NAME = <expr>` bindings, by name."""
    found: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = stmt.value
    return found


def _imported_module(tree: ast.Module, name: str) -> str | None:
    """The dotted module `name` was imported from, if it was."""
    for stmt in tree.body:
        if isinstance(stmt, ast.ImportFrom) and stmt.module:
            if any(alias.asname == name or (alias.asname is None and alias.name == name) for alias in stmt.names):
                return stmt.module
    return None


def _resolve_constant(root: Path, tree: ast.Module, name: str) -> ast.expr | None:
    """Resolve `name` to its bound expression: module-level first, then one import hop.

    A model may legitimately hoist its schema or its dimensions to a shared constant
    and import it (`tap_web`'s `WEB_DIMENSIONS` lives in `tap_web/dimensions.py`).
    Without following that one hop the scanner reads zero terms and the article passes
    while explaining nothing — a false green, which for a coverage guard is worse than
    a failure. One hop, within the owner's own tree, is enough for every case in the
    repository; anything further is reported as unresolvable rather than guessed at.
    """
    local = _module_constants(tree).get(name)
    if local is not None:
        return local
    module = _imported_module(tree, name)
    if module is None:
        return None
    # `tap_web.dimensions` -> tap_web/dimensions.py, relative to the owner root's parent.
    tail = module.split(".")
    for base in (root, root.parent):
        candidate = base.joinpath(*tail[1:] if tail[:1] == [root.name] else tail).with_suffix(".py")
        if candidate.is_file():
            try:
                return _module_constants(ast.parse(candidate.read_text(encoding="utf-8"))).get(name)
            except SyntaxError, OSError:
                return None
    return None


def _module_dicts(tree: ast.Module) -> dict[str, frozenset[str]]:
    """Module-level `NAME = {...}` bindings, so a schema assigned by reference resolves.

    Models legitimately hoist their schema to a module constant (the `validation_sample`
    fixture does). Without this the scanner would read zero fields there and pass an
    article that documents nothing — a false green, the worst outcome for a coverage guard.
    """
    found: dict[str, frozenset[str]] = {}
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
            continue
        keys = _dict_keys(stmt.value)
        if keys is None:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name):
                found[target.id] = keys
    return found


def _class_assignments(cls: ast.ClassDef) -> dict[str, ast.expr]:
    """Every `NAME = value` / `NAME: T = value` in a class body, by name."""
    found: dict[str, ast.expr] = {}
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            found[stmt.target.id] = stmt.value
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = stmt.value
    return found


def _model_files(root: Path) -> list[Path]:
    """Source files that may declare node types: `models.py` or the `models/` package."""
    files = [root / "models.py"] if (root / "models.py").is_file() else []
    models_pkg = root / "models"
    if models_pkg.is_dir():
        files.extend(sorted(p for p in models_pkg.rglob("*.py") if p.name != "__init__.py"))
    return files


def _local_stem(slug: str, owner: str, *, kind: str) -> str:
    """The owner-local half of a slug: `github_core__github_workflow` -> `github_workflow`.

    Node types are prefixed with the owner slug, edge slugs are suffixed with it. A slug
    that carries neither affix is used whole rather than guessed at.
    """
    if kind == KIND_NODE:
        return slug.removeprefix(f"{owner}__")
    return slug.removesuffix(f"__{owner}")


def _declared_classes(root: Path) -> Iterator[tuple[Path, ast.Module, str, dict[str, ast.expr]]]:
    """Every node-type class under `root`: its file, module, `ENTITY_TYPE` and class body.

    Yields the slug already narrowed to `str`, so callers never re-derive (or re-cast) it.
    """
    for path in _model_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for cls in (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)):
            body = _class_assignments(cls)
            entity_type = body.get("ENTITY_TYPE")
            if isinstance(entity_type, ast.Constant) and isinstance(entity_type.value, str):
                yield path, tree, entity_type.value, body


def node_subjects(root: Path) -> list[DomainSubject]:
    """Node types declared under `root`, with the field set each article must explain."""
    owner = root.name
    subjects: list[DomainSubject] = []
    for path, tree, slug, body in _declared_classes(root):
        schema = body.get("FIELD_CRUD_SCHEMA")
        fields: frozenset[str] | None = frozenset()
        if schema is not None:
            resolved = _dict_keys(schema)
            if resolved is None and isinstance(schema, ast.Name):
                bound = _resolve_constant(root, tree, schema.id)
                resolved = _dict_keys(bound) if bound is not None else None
            fields = resolved  # None => declared but unresolvable; reported, never assumed empty.
        subjects.append(
            DomainSubject(
                kind=KIND_NODE,
                slug=slug,
                stem=_local_stem(slug, owner, kind=KIND_NODE),
                fields=fields,
                declared_in=path,
            )
        )
    return subjects


def dimension_subjects(root: Path) -> list[DomainSubject]:
    """Dimension keys declared under `root`, each with the values it is given.

    Dimensions are the third declared vocabulary, alongside node types and edge types,
    and until now the only one nothing explained. `github.observation` encodes the
    declaration/execution split the vocabulary corpus calls its largest finding, and
    landed across every model and edge with no record anywhere of what its two values
    mean — the drift this discovery exists to make impossible.
    """
    values: dict[str, set[str]] = {}
    unresolved: dict[str, Path] = {}
    declared_in: dict[str, Path] = {}

    for path, tree, _slug, body in _declared_classes(root):
        dims = body.get("DEFAULT_DIMENSIONS")
        if dims is None:
            continue
        pairs = _str_pairs(dims)
        if pairs is None and isinstance(dims, ast.Name):
            bound = _resolve_constant(root, tree, dims.id)
            pairs = _str_pairs(bound) if bound is not None else None
        if pairs is None:
            unresolved.setdefault(dims.id if isinstance(dims, ast.Name) else "DEFAULT_DIMENSIONS", path)
            continue
        for key, value in pairs.items():
            values.setdefault(key, set()).add(value)
            declared_in.setdefault(key, path)

    for path in sorted((root / "edges").glob("*.edge.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for key, value in (payload.get("default_dimensions") or {}).items():
            if isinstance(key, str) and isinstance(value, str):
                values.setdefault(key, set()).add(value)
                declared_in.setdefault(key, path)

    subjects = [
        DomainSubject(
            kind=KIND_DIMENSION,
            slug=key,
            stem=key,
            fields=frozenset(vals),
            declared_in=declared_in[key],
        )
        for key, vals in sorted(values.items())
    ]
    subjects.extend(
        DomainSubject(kind=KIND_DIMENSION, slug=name, stem=name, fields=None, declared_in=path)
        for name, path in sorted(unresolved.items())
    )
    return subjects


def edge_subjects(root: Path) -> list[DomainSubject]:
    """Edge types declared under `root/edges/*.edge.json`."""
    owner = root.name
    subjects: list[DomainSubject] = []
    for path in sorted((root / "edges").glob("*.edge.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        slug = payload.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        # An edge's "terms" are the dimension keys it stamps. Requiring the Endpoints
        # section to name each one is what stops an article asserting the opposite of
        # its manifest — which is exactly what happened when `github.observation` was
        # added across the vocabulary and six articles silently went stale.
        dimension_keys = frozenset(key for key in (payload.get("default_dimensions") or {}) if isinstance(key, str))
        subjects.append(
            DomainSubject(
                kind=KIND_EDGE,
                slug=slug,
                stem=_local_stem(slug, owner, kind=KIND_EDGE),
                fields=dimension_keys,
                declared_in=path,
            )
        )
    return subjects


def subjects_for_root(root: Path, *, types: bool = True) -> list[DomainSubject]:
    """Everything under `root` that owes an article.

    `types` is False for a `tap_*` app: its node types model TAP's own furniture, which
    its specs already define. Its *dimensions* are still owed an article — a dimension
    is a vocabulary, and an unexplained vocabulary is a problem wherever declared.
    """
    subjects = list(dimension_subjects(root))
    if types:
        subjects = [*node_subjects(root), *edge_subjects(root), *subjects]
    return subjects


def article_path(root: Path, subject: DomainSubject) -> Path:
    """Where `subject`'s article must live.

    Dimensions sit in a `dimensions/` subdirectory: a dimension key is a dotted
    namespace (`github.observation`) rather than a type slug, and keeping the two in
    separate directories means neither can ever shadow the other.

    TAP-IMPLEMENTS: req-domain-articles-layer@f0102a1b163e/428512514f92 (derivation) — the one
        derivation of an article's location; every writer, reader and guard asks here.
    """
    if subject.kind == KIND_DIMENSION:
        return root / ARTICLE_DIR / DIMENSION_DIR / f"{subject.stem}.md"
    return root / ARTICLE_DIR / f"{subject.stem}.md"


def _sections(text: str) -> dict[str, str]:
    """Article body keyed by normalized `##`-level section title.

    Deeper headings stay inside their parent section's body, so an article is free to
    subdivide (a Fields section with a subheading per field group) without the section
    itself disappearing from the scan.
    """
    found: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match and len(match.group("hashes")) == 2:
            if current is not None:
                found[current] = "\n".join(lines)
            current = match.group("title").strip().casefold()
            lines = []
            continue
        lines.append(line)
    if current is not None:
        found[current] = "\n".join(lines)
    return found


def _stated_source_keys(body: str) -> set[str]:
    """Keys stated as `- **Key:** value` lines in the Authoritative Source section."""
    stated: set[str] = set()
    for line in body.splitlines():
        match = _SOURCE_KEY_RE.match(line)
        if match:
            key = (match.group("key") or match.group("key2") or "").strip()
            if key:
                stated.add(key.casefold())
    return stated


def _article_findings(subject: DomainSubject, article: Path) -> list[Finding]:
    """Every obligation `article` fails to meet for `subject`.

    TAP-IMPLEMENTS: req-domain-articles-sections@28377810773f/ce8ac10c979b (derivation) — the one
        derivation of article shape: required sections, the pinned authoritative source, and
        Prior Art entries that carry the version they describe.
    """
    text = article.read_text(encoding="utf-8")
    sections = _sections(text)
    required = {
        KIND_NODE: NODE_SECTIONS,
        KIND_EDGE: EDGE_SECTIONS,
        KIND_DIMENSION: DIMENSION_SECTIONS,
    }[subject.kind]
    findings: list[Finding] = []

    for name in required:
        if name.casefold() not in sections:
            findings.append(Finding(subject, article, f"missing-section:{name}", f"add a `## {name}` section"))

    source_body = sections.get("authoritative source", "")
    stated = _stated_source_keys(source_body)
    for key in SOURCE_KEYS:
        if key.casefold() not in stated:
            findings.append(
                Finding(
                    subject,
                    article,
                    f"authoritative-source-missing:{key}",
                    f"state `- **{key}:** …` under `## Authoritative Source`",
                )
            )

    prior_art = sections.get("prior art", "")
    unpinned = [line.strip() for line in prior_art.splitlines() if _URL_RE.search(line) and not _PINNED_RE.search(line)]
    if unpinned:
        findings.append(
            Finding(
                subject,
                article,
                "prior-art-unpinned",
                "Prior Art tracks change, so each link carries the version or date it describes: "
                + "; ".join(unpinned[:3]),
            )
        )

    if subject.fields is None:
        findings.append(
            Finding(
                subject,
                article,
                "unresolvable-declaration",
                f"`{subject.slug}` declares its terms by a name this scanner cannot resolve — "
                "define the constant in the model's own module or import it from one file inside "
                "the owner, so coverage is measured rather than assumed",
            )
        )
        return findings

    term_section, term_heading = {
        KIND_DIMENSION: ("values", "Values"),
        KIND_EDGE: ("endpoints", "Endpoints"),
    }.get(subject.kind, ("fields", "Fields"))
    tokens = set(re.findall(r"`([^`\n]+)`", sections.get(term_section, "")))
    # An article may name a term alone (`github.surface`) or with the value it takes
    # (`github.surface: actions`); both account for it, and the second reads better in
    # prose. Only the part before the colon is the term.
    documented = tokens | {token.split(":", 1)[0].strip() for token in tokens}
    for term in sorted(subject.fields - documented):
        findings.append(
            Finding(
                subject,
                article,
                f"undocumented-{_TERM_NAME[subject.kind]}:{term}",
                f"explain `{term}` under `## {term_heading}` — what it means, and why the set admits it",
            )
        )
    return findings


def _orphan_findings(root: Path, subjects: list[DomainSubject]) -> list[Finding]:
    """Articles under `root/domain/` with no registered type behind them.

    The coverage check runs type→article; without this it would never run the other
    way, and an article left behind by a removed or renamed type would sit there
    reading as current documentation of something that no longer exists. That is the
    failure this whole layer argues is worse than absence, so the guard owes the
    symmetric check.
    """
    expected_types = {s.stem for s in subjects if s.kind != KIND_DIMENSION}
    expected_dimensions = {s.stem for s in subjects if s.kind == KIND_DIMENSION}
    findings: list[Finding] = []
    for directory, expected, what in (
        (root / ARTICLE_DIR, expected_types, "node or edge type"),
        (root / ARTICLE_DIR / DIMENSION_DIR, expected_dimensions, "dimension key"),
    ):
        for article in sorted(directory.glob("*.md")):
            if article.stem in expected:
                continue
            orphan = DomainSubject(
                kind=KIND_ORPHAN, slug=article.stem, stem=article.stem, fields=frozenset(), declared_in=article
            )
            findings.append(
                Finding(
                    orphan,
                    article,
                    "orphan-article",
                    f"no registered {what} resolves to `{article.stem}` — it was renamed or "
                    "removed; rename the article to follow it, or delete it",
                )
            )
    return findings


def findings_for_root(root: Path, *, types: bool = True) -> list[Finding]:
    """Every domain-article obligation unmet under one owner root."""
    subjects = subjects_for_root(root, types=types)
    findings: list[Finding] = []
    for subject in subjects:
        article = article_path(root, subject)
        if not article.is_file():
            findings.append(Finding(subject, article, "missing-article", f"write {article.name} for `{subject.slug}`"))
            continue
        findings.extend(_article_findings(subject, article))
    findings.extend(_orphan_findings(root, subjects))
    return findings


def finding_key(finding: Finding, project_root: Path) -> str:
    """Baseline identity: `<article path>::<kind>:<slug>::<problem>`.

    Path-first so a reader can navigate straight to the file, and so the baseline's
    out-of-repo tripwire (`tap.ratchet`) judges a real repo-relative path.
    """
    rel = finding.article.resolve().relative_to(project_root.resolve()).as_posix()
    return f"{rel}::{finding.subject.kind}:{finding.subject.slug}::{finding.problem}"


def baseline_path_for(root: Path) -> Path:
    """An owner's committed baseline of known-missing article work.

    Per-owner, inside the owner's own package, so a plugin carries its documentation
    debt into its wheel and takes it away on eviction — never a central file naming a
    plugin (`req-tap-plugin-validation-distribution-principle`).
    """
    return root / "guards" / "baselines" / "domain_articles.txt"
