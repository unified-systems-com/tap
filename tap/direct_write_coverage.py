"""Static direct-write scanner — req-tap-auth-policy-9 Rule B (write half).

The build-time complement to the runtime write backstop (`tap_grid.write_guard`).
The runtime guard fails a node/edge write closed at execution time when it does
not route through the service layer; this scanner surfaces the same class at
authoring time so a direct write is caught before it runs — "detect by default,
permit by exception".

It flags *statically resolvable* direct ORM writes on TAP-managed model classes
(the class-level shapes), which carry no false positives because they name a known
graph model:

  <Model>.objects.<MANAGER_WRITES>(...)                  (incl. *_or_create + async variants)
  <Model>.objects.filter(...)....delete() / .update()   (terminal queryset write)
  <Model>(...).save(...)                                 (construct-then-save)

where <Model> is a TAP-managed model (a `BaseModel` subclass — incl. `Edge` — or
`Entity`), enumerated at test time from the model registry (a purely syntactic
tool cannot know which models are graph-managed; this is why Rule B is in-house,
not Semgrep — see `req-tap-auth-policy-9`).

The write-shape grammar itself (`MANAGER_WRITES` / `TERMINAL_WRITES` / the chain
walk) is the shared `tap.source_scan.orm_write_target` — one vocabulary for this
scanner and the credential-bind scanner, so a method added there is recognized by
both at once; this module owns only the managed-model resolution.

Instance writes through a variable (`obj.save()`, `obj.delete()`) are NOT resolved
here — their type is not knowable statically — and are left to the runtime guard.
The two compose: the lint catches class-level direct writes at authoring time; the
guard catches everything, including instance writes, at runtime.

Sanctioned write modules (the service layer itself and the model base that
implements save/delete), migrations, and tests are out of scope. A reviewed
exception is a `# TAP-WRITE-COV: <reason>` comment anywhere on the write's physical
span (so a black-wrapped call may carry it on a continuation line), or, as a last
resort, a line in `tap/guards/baselines/direct_write.txt` (ratchets to zero).
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from tap.source_scan import (
    CallSite,
    ImportBindings,
    ScopeStackVisitor,
    build_import_bindings,
    iter_parsed_sources,
    orm_write_target,
    semantic_hash,
)

# Modules that legitimately write TAP-managed rows directly — the service layer is
# the sanctioned path, and models.py implements the guarded save/delete themselves.
# The service layer is a package (tap_grid/services/): every module in it is the
# sanctioned direct-write path, covered by the package check in _is_out_of_scope.
_SANCTIONED_SUFFIXES: tuple[str, ...] = (
    "tap_grid/models.py",
    "tap_grid/batch.py",
    "tap_grid/grift/importer.py",  # the grift_import service implementation (bulk write pipeline)
)

_EXEMPT_TOKEN = "TAP-WRITE-COV"


def _under(origin: str, root: str) -> bool:
    """True if dotted ``origin`` is the app ``root`` itself or lives beneath it."""
    return origin == root or origin.startswith(root + ".")


@dataclass(frozen=True)
class CollisionResolution:
    """For a class name borne by BOTH a graph-managed and a non-managed model, the
    app/package roots (`Model._meta.app_config.name`) that tell the two apart."""

    managed_roots: frozenset[str]
    nonmanaged_roots: frozenset[str]


@dataclass(frozen=True)
class ManagedModelIndex:
    """What the scanner needs to answer "does this write target a graph-managed model?".

    ``names`` is the fast candidate set — every graph-managed class name (`BaseModel`
    subclasses + ``Entity``), enumerated by the caller from the model registry (a
    purely-syntactic tool cannot know which models are graph-managed). A bare-name
    match against it *finds* a candidate write.

    ``collisions`` carries the rare name (``User`` today) that a NON-managed model
    *also* bears, with the app-root prefixes that resolve the ambiguity through the
    file's imports (`req-tap-auth-policy-9-name-resolution`). Before this, matching by
    bare name flagged every ``User.objects.*`` write on the *non-managed* `tap_auth`
    ``User`` as if it were the graph model — a false positive whose only "coverage" of
    the flagged line was the name collision itself. A name absent from ``collisions``
    is unambiguous: the bare-name match is correct by construction and no resolution
    runs (zero behaviour change on the ~99% non-colliding path).
    """

    names: frozenset[str]
    collisions: dict[str, CollisionResolution]

    def is_managed(self, name: str, ref: ast.expr, bindings: ImportBindings) -> bool:
        """Does a write on ``name`` (referenced by node ``ref``) target a graph model?

        Unambiguous name → ``True`` (it named a managed model, by construction). A
        collision name is resolved through the file's imports: the *only* case that
        returns ``False`` is an origin that resolves cleanly under a non-managed owner
        and not under a managed one. An origin under a managed owner, or one that
        cannot be resolved at all (star/relative import, locally shadowed, dotted via
        an unimported root), returns ``True`` — the scanner fails *toward* flagging, so
        a genuine graph write is never dropped by a resolution gap
        (`req-tap-auth-policy-9-name-resolution`).
        """
        res = self.collisions.get(name)
        if res is None:
            return True
        origin = bindings.resolve(ref)
        if origin is None:
            return True  # unresolved → fail-closed (keep the conservative bare-name match)
        if any(_under(origin, r) for r in res.nonmanaged_roots) and not any(
            _under(origin, r) for r in res.managed_roots
        ):
            return False
        return True


@dataclass(frozen=True)
class DirectWriteSite:
    """One class-level direct-write call site on a TAP-managed model.

    Keyed stably by enclosing scope + ``Model.op`` — never the line number —
    mirroring authz's `SinkSite`, so a flagged write does not drift in the baseline
    when unrelated edits move it (the `path:lineno` churn this replaces,
    `req-tap-callsite-identity-anchor`). ``lineno`` is retained for navigation and
    messages only. ``node_dump`` is the positions-stripped AST serialization that
    discriminates two writes sharing an anchor (`req-tap-callsite-identity-discriminator`).
    """

    path: Path
    lineno: int
    #: Last physical line of the call — navigation only, and the span the exemption
    #: comment must sit within. NEVER part of the anchor or discriminator (keys stay
    #: drift-proof).
    end_lineno: int
    qualname: str
    model: str
    op: str
    node_dump: str

    def anchor(self, repo_root: Path) -> str:
        """The drift-proof anchor `path::qualname::Model.op` (no line number)."""
        return f"{self.path.relative_to(repo_root).as_posix()}::{self.qualname}::{self.model}.{self.op}"

    def discriminator(self, repo_root: Path) -> str:
        """Semantic hash over location-free canonical material — tells apart two
        distinct writes at the same anchor. Byte-identical writes collide here and
        fall back to an ordinal in `tap.guards.callsite.disambiguate`."""
        return semantic_hash(
            self.path.relative_to(repo_root).as_posix(),
            self.qualname,
            "direct-write",
            f"{self.model}.{self.op}",
            self.node_dump,
        )


@dataclass
class DirectWriteScanResult:
    """Direct-write call sites on TAP-managed models found by the scan."""

    direct_writes: list[DirectWriteSite] = field(default_factory=list)
    exempt_skipped: list[DirectWriteSite] = field(default_factory=list)
    #: `# TAP-WRITE-COV` comment sites that suppress no flagged write (stale excuses):
    #: the write they once covered was rerouted, resolved out of scope, or moved off
    #: their span. Surfaced so they rot loudly, like mypy `warn_unused_ignores`
    #: (`req-tap-auth-policy-9-unused-exemption`).
    unused_exemptions: list[CallSite] = field(default_factory=list)


def _model_ref_node(node: ast.expr, names: frozenset[str]) -> ast.expr | None:
    """The reference node (`Name` `Model` or `Attribute` `pkg.Model`) if it names a
    candidate managed model, else ``None``. Returns the *node* — not just its name — so
    the caller can resolve which same-named class it is through the file's imports."""
    if isinstance(node, ast.Name) and node.id in names:
        return node
    if isinstance(node, ast.Attribute) and node.attr in names:
        return node
    return None


def _ref_name(node: ast.expr) -> str:
    """The bare class name a ref node carries — ``Name.id`` or ``Attribute.attr``."""
    return node.attr if isinstance(node, ast.Attribute) else node.id  # type: ignore[attr-defined]


class _DirectWriteVisitor(ScopeStackVisitor):
    """Flag class-level direct writes to TAP-managed models, carrying the enclosing
    `qualname` from the shared `ScopeStackVisitor` (`req-tap-callsite-identity-anchor`)."""

    def __init__(self, path: Path, source_lines: list[str], index: ManagedModelIndex, bindings: ImportBindings) -> None:
        super().__init__()
        self.path = path
        self.source_lines = source_lines
        self.index = index
        self.bindings = bindings
        self.result = DirectWriteScanResult()

    def visit_Call(self, node: ast.Call) -> None:
        # Shared write-shape grammar (`tap.source_scan.orm_write_target`); this scanner
        # supplies only the model-resolution — a ref NODE, so `is_managed` can resolve
        # same-named classes through the file's imports.
        target = orm_write_target(node, is_target=lambda n: _model_ref_node(n, self.index.names))
        if target is not None:
            ref_node, op = target
            model = _ref_name(ref_node)
            # Resolve which same-named class this is (only a collision name pays the
            # cost); a non-managed `User` write resolves away here instead of being
            # flagged by name collision (`req-tap-auth-policy-9-name-resolution`).
            if self.index.is_managed(model, ref_node, self.bindings):
                lineno = node.lineno
                end = node.end_lineno or lineno
                site = DirectWriteSite(
                    self.path,
                    lineno,
                    end,
                    self.current_qualname(),
                    model,
                    op,
                    # Positions-stripped structural dump: the drift-proof discriminator
                    # material (`req-tap-callsite-identity-discriminator-4`).
                    ast.dump(node, include_attributes=False),
                )
                # Scan the call's full physical span for the exemption token, not just
                # its start line — black may wrap a chained write across several lines,
                # landing the trailing `# TAP-WRITE-COV:` comment below `node.lineno`.
                span = self.source_lines[lineno - 1 : end]
                if any(_EXEMPT_TOKEN in line for line in span):
                    self.result.exempt_skipped.append(site)
                else:
                    self.result.direct_writes.append(site)
        self.generic_visit(node)


def _is_out_of_scope(path: Path) -> bool:
    """Sanctioned service modules, migrations, and tests are out of scope."""
    posix = path.as_posix()
    if "tap_grid/services/" in posix:  # the whole service-layer package is sanctioned
        return True
    if any(posix.endswith(suffix) for suffix in _SANCTIONED_SUFFIXES):
        return True
    if "migrations" in path.parts:
        return True
    return "tests" in path.parts or path.name.startswith("test_") or path.name == "conftest.py"


def _exempt_comment_lines(source: str) -> set[int]:
    """Line numbers of ``# …TAP-WRITE-COV…`` **comment** tokens in `source`.

    Tokenize-precise on purpose: the marker inside a *string literal* — this rule's own
    ``new_hint``, a docstring naming it, the ``_EXEMPT_TOKEN`` assignment — is NOT a live
    exemption and must never be mistaken for one, or the freshness check would false-fire
    on prose. That precision is exactly what an inline-comment escape hatch needs to earn
    an unused-suppression check (`req-tap-auth-policy-9-unused-exemption`). Tolerant of a
    tokenizer error the same way :func:`~tap.source_scan.parse_file` tolerates a syntax error.
    """
    lines: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT and _EXEMPT_TOKEN in tok.string:
                lines.add(tok.start[0])
    except tokenize.TokenError, IndentationError, SyntaxError, ValueError:
        pass
    return lines


def scan_direct_writes(roots: list[Path], index: ManagedModelIndex) -> DirectWriteScanResult:
    """Flag class-level direct writes to TAP-managed models across `roots`.

    `index` names the graph-managed model classes (enumerated by the caller from the
    model registry — a purely-syntactic tool cannot know which models are
    graph-managed) plus the collision-resolution data that tells a same-named
    non-managed class apart via each file's imports. Files that fail to parse are
    skipped (real syntax errors surface elsewhere).

    Also reports **unused exemptions**: a `# TAP-WRITE-COV` comment that does not sit
    on the physical span of any flagged write suppresses nothing (the write it once
    covered was rerouted, resolved out of scope, or moved) and is surfaced so it rots
    loudly (`req-tap-auth-policy-9-unused-exemption`).
    """
    result = DirectWriteScanResult()
    for parsed in iter_parsed_sources(roots, skip=_is_out_of_scope):
        bindings = build_import_bindings(parsed.tree)
        visitor = _DirectWriteVisitor(parsed.path, parsed.lines, index, bindings)
        visitor.visit(parsed.tree)
        result.direct_writes.extend(visitor.result.direct_writes)
        result.exempt_skipped.extend(visitor.result.exempt_skipped)

        # An exemption comment is "used" iff it lies on the span of a write that was
        # actually flagged-then-skipped. Any other TAP-WRITE-COV comment is orphaned.
        exempt_comments = _exempt_comment_lines(parsed.source)
        if exempt_comments:
            consumed = {
                line
                for site in visitor.result.exempt_skipped
                for line in exempt_comments
                if site.lineno <= line <= site.end_lineno
            }
            result.unused_exemptions.extend(CallSite(parsed.path, line) for line in sorted(exempt_comments - consumed))
    return result
