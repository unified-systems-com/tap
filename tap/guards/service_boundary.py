"""Service-layer boundary guard — every guarded `services/` package is a real trust boundary.

TAP-IMPLEMENTS: req-service-boundary-guard@72d8a242e17d/cd1480ea876a (enforcement) — the single reusable
guard the requirement calls for; a second per-app boundary checker is the pattern this
retired (`tap_grid.guards.service_gateway`).

The single reusable guard the boundary convention calls for (`spec-service-layer-boundary.md`
`req-service-boundary-guard`): one guard, parameterized by **discovery**, that every guarded
service package declares itself into simply by *existing* as a `services/` package under a
first-party source root. This generalizes — and retires — the grid-specific
`tap_grid.guards.service_gateway` guard, which was hardcoded to `tap_grid/services/`.

Discovery is **fail-closed** (`req-service-boundary-discovery`): a new `services/` package is a
protected boundary by default; opting one *out* of being a guarded boundary is an explicit,
reviewed marker (`__tap_not_a_boundary__ = True`) in its `__init__.py`. There is no opt-*in*
list to forget.

Two mechanical checks per boundary, enforced by **location/export**, never by a "does this look
privileged?" heuristic (that heuristic is exactly what let the Entity-spine reads ship ungated):

  (a) every name in the gateway's ``__all__`` resolves to a **gated operation** — a `def`
      carrying ``@requires_capability(...)`` or ``@gates_per_operation``. A non-operation in
      ``__all__`` (a type/exception/constant) has no gate, so it fails, and the fix is to move it
      to the contract module.
  (b) **no ungated public** (non-`_`) function is defined in a gateway module, in or out of
      ``__all__``. ``__all__`` advertises the surface; it can never *shrink* what is enforced —
      the union invariant (`req-service-boundary-export`).

Zones are resolved by AST/convention **without importing** the package (`req-service-boundary-
discovery-3`), so the guard runs pre-boot on the shared tree-scanner substrate
(`tap/source_scan.py`): the package `__init__.py` (plus non-`_`, non-contract submodules) is the
**gateway**; `_`-prefixed modules are **below-gate** (skipped); modules named in
``__tap_contract_modules__`` are the **contract** zone (skipped). Hard lint — no baseline, no
allowlist: a new ungated operation entry point fails immediately.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots, has_decorator, parse_file

_GATE_DECORATORS = frozenset({"requires_capability", "gates_per_operation"})

# Zone-declaration markers read from a boundary's __init__.py **by AST**, never imported
# (so the guard runs pre-boot). See req-service-boundary-discovery-3.
_ALL_VAR = "__all__"
_CONTRACT_MODULES_VAR = "__tap_contract_modules__"
_OPT_OUT_VAR = "__tap_not_a_boundary__"


@dataclass(frozen=True)
class _Boundary:
    """One discovered `services/` package and its resolved zones."""

    label: str  # repo-relative path, for messages
    gateway_modules: list[Path]
    declared_all: list[str] | None  # None = no __all__ declared


def _literal(node: ast.expr) -> object | None:
    """`ast.literal_eval` a value node; ``None`` if it isn't a literal.

    The zone markers must be static literals so the guard can read them without
    importing the module. A non-literal marker is treated as *absent* here and caught
    as a malformed boundary by the caller (fail-closed), not silently trusted.
    """
    try:
        value: object = ast.literal_eval(node)
    except ValueError, SyntaxError, TypeError:
        return None
    return value


def _read_zone_markers(init_path: Path) -> tuple[list[str] | None, tuple[str, ...], bool]:
    """Read ``__all__`` / ``__tap_contract_modules__`` / ``__tap_not_a_boundary__`` by AST.

    Returns ``(declared_all, contract_modules, opt_out)``. Fails **loud** if the gateway
    ``__init__.py`` cannot be parsed — a boundary the guard cannot read must not pass green
    (`req-service-boundary-discovery-2`).
    """
    parsed = parse_file(init_path)
    assert parsed is not None, f"service boundary __init__ failed to read/parse: {init_path}"

    declared_all: list[str] | None = None
    contract: tuple[str, ...] = ()
    opt_out = False

    for node in parsed.tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if _ALL_VAR in targets:
            value = _literal(node.value)
            assert isinstance(value, (list, tuple)), (
                f"{init_path}: {_ALL_VAR} must be a static list/tuple literal so the boundary "
                f"guard can read it without importing the package"
            )
            declared_all = [str(item) for item in value]
        if _CONTRACT_MODULES_VAR in targets:
            value = _literal(node.value)
            assert isinstance(
                value, (list, tuple)
            ), f"{init_path}: {_CONTRACT_MODULES_VAR} must be a static list/tuple literal"
            contract = tuple(str(item) for item in value)
        if _OPT_OUT_VAR in targets:
            opt_out = _literal(node.value) is True

    return declared_all, contract, opt_out


def _gateway_modules(package: Path, contract: tuple[str, ...]) -> list[Path]:
    """The gateway zone: ``__init__.py`` + non-`_`, non-contract top-level ``.py`` modules."""
    modules = [package / "__init__.py"]
    for path in sorted(package.glob("*.py")):
        name = path.stem
        if name == "__init__" or name.startswith("_") or name in contract:
            continue  # below-gate (`_`) or contract zone — not scanned
        modules.append(path)
    return modules


def _classify_public_defs(path: Path) -> tuple[set[str], set[str]]:
    """``(gated, ungated)`` names among **public** (non-`_`) top-level function defs.

    Nested defs are below the gate by construction; `_`-prefixed defs (including the grid
    layer's gated internal-write cluster and its test seams) are out of the public export
    inventory and skipped (`req-service-boundary-below-gate`).
    """
    parsed = parse_file(path)
    assert parsed is not None, f"gateway module failed to read/parse: {path}"
    gated: set[str] = set()
    ungated: set[str] = set()
    for node in parsed.tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            continue
        (gated if has_decorator(node, _GATE_DECORATORS) else ungated).add(node.name)
    return gated, ungated


def _boundary_violations(boundary: _Boundary) -> list[str]:
    """The `req-service-boundary-guard-3` pair of checks, as human-readable offenders."""
    gated: set[str] = set()
    ungated: set[str] = set()
    for module in boundary.gateway_modules:
        module_gated, module_ungated = _classify_public_defs(module)
        gated |= module_gated
        ungated |= module_ungated

    problems: list[str] = []
    # (b) union invariant: no ungated public function anywhere in the gateway zone.
    for name in sorted(ungated):
        problems.append(
            f"{boundary.label}: ungated public gateway function `{name}` — add "
            f"@requires_capability(...)/@gates_per_operation, or if it is not an operation move "
            f"it to a contract module ({_CONTRACT_MODULES_VAR}) / below the gate (`_`-module)"
        )
    # (a) every __all__ entry is a gated operation. Names already in `ungated` are covered by
    # (b); a name that is neither gated nor an ungated def is a non-operation smuggled into
    # __all__ (a type/exception/constant) and belongs in the contract module.
    if boundary.declared_all is not None:
        for name in boundary.declared_all:
            if name in gated or name in ungated:
                continue
            problems.append(
                f"{boundary.label}: `{name}` is in {_ALL_VAR} but is not a gated operation "
                f"defined in a gateway module — move non-operations (types, exceptions, "
                f"constants, schemas) to a contract module ({_CONTRACT_MODULES_VAR})"
            )
    return problems


def _discover_boundaries() -> list[tuple[Path, bool]]:
    """Every `services/` **package** under a first-party root, paired with its opt-out flag.

    A `services/` directory without an `__init__.py` is not a Python package and cannot be a
    service *layer* in the import sense, so it is not a boundary. Any package that *is*
    discovered is protected by default (fail-closed); the boolean is its reviewed opt-out.
    """
    boundaries: list[tuple[Path, bool]] = []
    for root in first_party_source_roots(REPO_ROOT):
        for path in sorted(root.rglob("services")):
            if "__pycache__" in path.parts:
                continue
            if path.is_dir() and (path / "__init__.py").exists():
                _, _, opt_out = _read_zone_markers(path / "__init__.py")
                boundaries.append((path, opt_out))
    return boundaries


def discovered_boundary_packages() -> list[Path]:
    """The `services/` boundary package dirs actively protected (reviewed opt-outs excluded).

    The single discovery surface both boundary guards share — the coverage guard here and
    the import-encapsulation guard (`service_boundary_imports`) — so the set of protected
    boundaries is computed once and cannot drift between the two.
    """
    return [package for package, opt_out in _discover_boundaries() if not opt_out]


def protected_boundaries() -> list[str]:
    """Repo-relative labels of the `services/` boundaries this guard actively protects.

    The visible "what do I protect" surface (`req-service-boundary-discovery-4`): an
    opted-out or undiscovered boundary is legible here, not hidden behind green.
    """
    return [str(package.relative_to(REPO_ROOT)) for package in discovered_boundary_packages()]


class ServiceBoundaryGuard(Guard):
    slug = "service-boundary-coverage"
    map_row = "Service-layer boundary coverage"
    rid = "req-service-boundary-guard"
    description = (
        "A guarded `services/` package is a trust boundary only if every operation it exports is "
        "gated and nothing public escapes ungated. This one reusable guard discovers every "
        "`services/` package under a first-party root (fail-closed) and enforces, by "
        "location/export not heuristic: every __all__ entry is a gated operation, and no ungated "
        "public function exists in a gateway module. So a new service layer cannot ship a "
        "forgotten gate, and the boundary cannot erode one export at a time."
    )

    def check(self) -> None:
        discovered = _discover_boundaries()
        assert discovered, (
            "no `services/` boundary packages discovered under any first-party source root — the "
            "boundary guard has nothing to protect, which almost certainly means discovery broke"
        )
        problems: list[str] = []
        for package, opt_out in discovered:
            if opt_out:
                continue  # reviewed opt-out (req-service-boundary-discovery-2)
            declared_all, contract, _ = _read_zone_markers(package / "__init__.py")
            boundary = _Boundary(
                label=str(package.relative_to(REPO_ROOT)),
                gateway_modules=_gateway_modules(package, contract),
                declared_all=declared_all,
            )
            problems.extend(_boundary_violations(boundary))

        assert not problems, (
            "Service-layer boundary violation(s). Every guarded `services/` package is a trust "
            "boundary: every __all__ entry must be a gated operation, and no ungated public "
            "function may exist in a gateway module (spec-service-layer-boundary.md). Fix by "
            "gating the operation, or moving a non-operation to the contract module.\n  - " + "\n  - ".join(problems)
        )
