"""Shared source-scanning primitives for TAP's static, tree-walking checks.

TAP-IMPLEMENTS: req-tap-tree-scanner-substrate@8b611e0366de/1f2595e8d933 (derivation) — the one home of
the parse-driver / decorator / call-name / scope-stack mechanics every tree scanner shares;
a scanner hand-rolling any of the four is the duplication this module exists to end.

Several checks walk the first-party source tree and report findings by file+line:
the log-site token scanner (`tap.logging`), the authz-coverage scanner
(`tap.authz_coverage`), the direct-write scanner, the plugin-dependency scanner
(`tap.plugin_deps`), and — soon — guard discovery. They all need the same two
things: *which roots count as first-party TAP source*, and *a way to name a source
location*. Those primitives lived in `tap.logging` because the log-site scanner was
the first caller; they are not logging-specific and now live here.

Deliberately Django-free: `first_party_source_roots` inspects the filesystem, not
Django's app registry, so a caller can run **before** `django.setup()` — at pytest
collection time, inside a pre-boot gate, or from a bare script.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Callable, Collection, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CallSite:
    """A source-code location: a file path and a 1-indexed line number.

    The shared currency of the tree-scanners — a finding is "this thing, here".
    Scanners layer their own richer result types on top (e.g. the log-site
    scanner's `WellFormedSite` adds the hex token).

    In the callsite-identity model (`spec-tap-callsite-identity`) this is the
    **location** role — the navigable, freely-drifting part of a finding. It is
    never part of the drift-proof anchor or either derived key.
    """

    path: Path
    lineno: int


@dataclass(frozen=True)
class CallsiteIdentity:
    """A tree-scanner finding's three-role identity (`spec-tap-callsite-identity`).

    Separates the drift-proof structural **anchor** (`path::qualname::construct`,
    never a line number) from the physical **location** (navigation only, drifts)
    and an optional occurrence **discriminator** (present only when an anchor can
    cover more than one physical offense). Two keys compose from these:

    - ``occurrence_key`` — ``anchor`` (+ ``#<discriminator>``): exactly one physical
      offense; the SARIF fingerprint. Computed here.
    - the *baseline key* — the ratchet's entry identity, at remediation-unit
      granularity (anchor for per-function scanners, occurrence_key for per-call
      ones). NOT computed here: it is the ratchet's choice, so it lives on
      ``CallsiteRatchet`` (`req-tap-callsite-identity-remediation-unit`), not on the
      identity.

    The anchor is the single drift-proof *root* both keys derive from; it is not
    itself either key.
    """

    location: CallSite
    anchor: str
    discriminator: str | None = None

    @property
    def occurrence_key(self) -> str:
        """The anchor, plus ``#<discriminator>`` when one is present — one per offense."""
        if self.discriminator is None:
            return self.anchor
        return f"{self.anchor}#{self.discriminator}"


def semantic_hash(*parts: str) -> str:
    """A short, stable digest over **location-free** canonical material.

    The shared discriminator recipe (`req-tap-callsite-identity-discriminator`), so
    the tree-scanners do not each invent their own hash. Callers pass their
    scanner-owned canonical parts — the repo-relative POSIX path, the enclosing
    qualname, the construct kind, `Model.op`, and a positions-stripped
    ``ast.dump(node, include_attributes=False)`` — and **never** a raw line or
    column, which is what keeps the digest drift-proof. Byte-identical constructs
    collide by design; the caller applies an ordinal fallback (see
    `tap.guards.callsite.disambiguate`).
    """
    joined = "\x1f".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def first_party_source_roots(project_root: Path) -> list[Path]:
    """The first-party TAP source roots every tree-scanner walks.

    Returns the `tap_*` app roots (a directory with `apps.py`) plus the in-repo
    plugin roots (a `tap-plugin.toml`-bearing directory under `plugins/<slug>`),
    discovered by **filesystem inspection**.

    Two in-repo plugin layouts are recognized so package-mode migration does not
    silently drop a plugin from a scanner:
      - build-baked / legacy:  `plugins/<slug>/tap-plugin.toml`               → root `plugins/<slug>`
      - package-mode namespace: `plugins/<slug>/tap_plugin/<slug>/tap-plugin.toml` → root that package dir
    (A fully extracted package-mode plugin installed from site-packages is out of the
    in-repo scanners' scope by construction; its scanning moves with its own repo.)

    Independent of Django's runtime app registry — a hard guarantee, not an
    incidental one: callers run this at pytest collection time and inside the
    pre-boot gate, before settings/apps are loaded.
    """
    roots: list[Path] = []
    for child in sorted(project_root.iterdir()):
        if child.is_dir() and child.name.startswith("tap_") and (child / "apps.py").exists():
            roots.append(child)
    plugins_dir = project_root / "plugins"
    if plugins_dir.is_dir():
        for child in sorted(plugins_dir.iterdir()):
            if not child.is_dir():
                continue
            if (child / "tap-plugin.toml").exists():
                roots.append(child)  # legacy flat layout
                continue
            # Package-mode: manifest sits inside the PEP 420 namespace at
            # plugins/<slug>/tap_plugin/<pkg>/tap-plugin.toml (req-tap-plugin-arch-identity-3).
            namespace_dir = child / "tap_plugin"
            if namespace_dir.is_dir():
                roots.extend(sorted(m.parent for m in namespace_dir.glob("*/tap-plugin.toml")))
    return roots


# =============================================================================
# Tree-scanner parse substrate — spec-tap-tree-scanner.md
# =============================================================================
# The low-level `ast` mechanics every tree-scanner used to hand-roll: one parse
# driver (was five copy-pasted "for each .py, parse it" loops), one decorator
# resolver (was written twice), one call-name resolver, and one enclosing-scope
# walk (was copy-pasted between scanners). Written once here so a fix to any of
# them is inherited by every scanner (`req-tap-tree-scanner-substrate`). Stdlib
# `ast` only, Django-free, so it runs pre-boot alongside the rest of this module
# (`req-tap-tree-scanner-preboot`).


@dataclass(frozen=True)
class ParsedSource:
    """One first-party source file, read and parsed once by the shared driver.

    ``lines`` is the source split on line boundaries — the 1-indexed material a
    scanner needs to look for an exemption comment on a finding's physical span.
    """

    path: Path
    tree: ast.Module
    source: str

    @property
    def lines(self) -> list[str]:
        return self.source.splitlines()


def parse_file(path: Path) -> ParsedSource | None:
    """Read + parse one `.py` file, tolerantly. ``None`` when unreadable/unparseable.

    Skips the file (rather than raising) on an OS/decoding error or a syntax
    error — the shared, permissive stance every scanner already took by hand
    (real syntax errors surface at pytest collection / import time elsewhere).
    ``ValueError`` (e.g. source containing a NUL byte) is treated the same as a
    ``SyntaxError`` — the union of what the individual scanners tolerated.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError, ValueError:
        return None
    return ParsedSource(path, tree, source)


def iter_parsed_sources(
    roots: Iterable[Path],
    *,
    skip: Callable[[Path], bool] | None = None,
) -> Iterator[ParsedSource]:
    """Walk `roots`, parse each `.py` once, yield the ones that read+parse.

    The single parse driver that replaces the five per-scanner loops. Recurses
    each root (`rglob`), always skips `__pycache__`, and applies the optional
    `skip(path) -> bool` a scanner uses to drop its own out-of-scope files (test
    files for authz, sanctioned modules for direct-write). Files that fail to read
    or parse are silently dropped via :func:`parse_file`.
    """
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if skip is not None and skip(path):
                continue
            parsed = parse_file(path)
            if parsed is not None:
                yield parsed


def decorator_name(node: ast.expr) -> str | None:
    """Resolve a decorator node to its callable name; ``None`` if not a name.

    Handles ``@x`` (``Name``), ``@x(...)`` (``Call``), and ``@a.b.c`` /
    ``@a.b.c(...)`` (``Attribute``) — returning the final attribute/name in each.
    The single resolver that replaces the two former ``_decorator_name`` copies
    (which returned ``str | None`` and ``str``); ``None`` collapses to "no gate"
    for both call sites just as the empty string did (`req-tap-tree-scanner-substrate`).
    """
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return None


def has_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    names: Collection[str],
) -> bool:
    """True if any of `node`'s decorators resolves to a name in `names`."""
    return any(decorator_name(d) in names for d in node.decorator_list)


def call_name(node: ast.Call) -> str | None:
    """The called function's name — ``foo`` from ``foo(...)`` or ``x.foo(...)``."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


@dataclass(frozen=True)
class ImportBindings:
    """A file's local-name → dotted-origin map, built from its own ``import`` statements.

    Models pyflakes' per-file ``ImportationFrom`` binding — the recognized cheap
    disambiguation layer for a syntactic scanner. Ruff and Semgrep build exactly this
    file-local binder and *deliberately stop short* of cross-module type inference;
    astroid/CodeQL's global inference is unnecessary when a name's origin is stated in
    the file's own ``import`` line (`req-tap-auth-policy-9-name-resolution`).

    Two deliberate limits, both in the safe direction for a fail-closed caller:

    - **Parse, never import.** It reads the AST, so it runs pre-boot like the rest of
      this module and never executes the target code.
    - **One hop.** It resolves the origin *as this file names it* — ``from a.b import
      C`` → ``a.b.C`` — not the ultimate definition site, so a re-export is followed no
      further. A caller that must survive re-exports matches on an app/package
      *prefix*, not an exact dotted path.

    Names it cannot resolve — star imports, relative imports, names bound by a
    same-module ``class``/``def``, dynamically constructed names — are simply
    **absent**; :meth:`resolve` returns ``None`` and the caller owns the fallback.
    """

    #: local name → dotted origin of the *symbol* (``from a.b import C as D`` → ``{"D": "a.b.C"}``).
    symbols: dict[str, str]
    #: local alias → dotted *module* (``import a.b.c as x`` → ``{"x": "a.b.c"}``; plain ``import a.b`` → ``{"a": "a"}``).
    modules: dict[str, str]

    def resolve(self, node: ast.expr) -> str | None:
        """The dotted origin a ``Name``/``Attribute`` refers to via this file's imports, or ``None``."""
        if isinstance(node, ast.Name):
            return self.symbols.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self._resolve_module(node.value)
            if base is not None:
                return f"{base}.{node.attr}"
        return None

    def _resolve_module(self, node: ast.expr) -> str | None:
        """Walk a dotted ``a.b.c`` module reference back to its imported root, or ``None``."""
        if isinstance(node, ast.Name):
            return self.modules.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self._resolve_module(node.value)
            if base is not None:
                return f"{base}.{node.attr}"
        return None


def build_import_bindings(tree: ast.Module) -> ImportBindings:
    """Build a file's :class:`ImportBindings` from every ``import`` in its tree.

    Walks the whole module (not just the top level) so a function-local or
    ``TYPE_CHECKING``-guarded import is seen too. Absolute imports only: a relative
    import (``level > 0``) is skipped, because resolving it needs the file's package
    path, which this Django-free, parse-only binder deliberately does not take — the
    unresolved name falls through to the caller's fallback.
    """
    symbols: dict[str, str] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level != 0 or node.module is None:
                continue  # relative import — left absent (caller falls back)
            for alias in node.names:
                if alias.name == "*":
                    continue  # star import — origin unknown, left absent
                symbols[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name  # import a.b.c as x → x → a.b.c
                else:
                    # `import a.b.c` binds the top name `a`; `a.b.c.X` then resolves by
                    # walking attributes from that root, so bind the top package to itself.
                    modules.setdefault(alias.name.split(".", 1)[0], alias.name.split(".", 1)[0])
    return ImportBindings(symbols, modules)


class ScopeStackVisitor(ast.NodeVisitor):
    """`NodeVisitor` base that tracks the enclosing `def`/`class` qualname.

    The single enclosing-scope walk that replaces the copy-pasted per-scanner
    versions (`req-tap-tree-scanner-substrate`). A subclass overrides `visit_Call`
    (or another node) and reads :meth:`current_qualname` for the drift-proof
    ``qualname`` half of a finding's anchor (`spec-tap-callsite-identity`). A
    subclass that needs extra per-scope bookkeeping (e.g. authz's gated-depth)
    overrides the relevant ``visit_*`` and calls ``super().visit_*`` so the stack
    push/pop still happens around its own logic.
    """

    def __init__(self) -> None:
        self.scope_stack: list[str] = []

    def current_qualname(self) -> str:
        return ".".join(self.scope_stack) if self.scope_stack else "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()
