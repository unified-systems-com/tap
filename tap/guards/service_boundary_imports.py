"""Service-boundary import-encapsulation guard — nobody reaches *past* the gate.

The outward dual of the coverage guard (`service_boundary`). That guard locks the front
door: the gateway's own operations are gated. This one shuts the windows
(`spec-service-layer-boundary.md` `req-service-boundary-inviolability`, "Going around #1:
importing past the gate"): **no module outside a boundary's package may import that
boundary's below-gate (`_`-prefixed) submodules.** Outside code gets the gateway's public
exports and nothing else; it can never import `tap_grid.services._impl` and call the pure
write pipeline directly, skipping the capability check the gateway asserts.

This is the mirror image of the internal one-way-import rule (`req-service-boundary-model`):
that keeps the *inside* from reaching up to the gateway; this keeps the *outside* from
reaching down past it. For an un-gateable layer (boot/pre-boot) an equivalent
import-encapsulation check is the *primary* defense, because there is no gate behind the
door at all — but that layer is sealed by its own guard; here the scope is the discovered
`services/` boundaries.

Scope is deliberately **module-level**, not name-level. A `_`-prefixed *submodule*
(`_impl.py`) is below-gate code and importing it externally is a bypass. A `_`-prefixed
*name* re-exported from the gateway (`_create_node_internal`) is still a **gated** function
— the reviewed narrow exception (`req-service-boundary-below-gate-2`), not a bypass — so an
external import of that name is not flagged. The discriminator is concrete: a forbidden
target is a dotted module that corresponds to an actual `_<name>.py` file in the boundary
package.

DIY AST, stdlib-only, pre-boot — same shape as the other tree-scanners. Hard lint: no
baseline. External code has never legitimately reached a boundary's `_`-module, so there is
no debt to grandfather.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.guards.service_boundary import discovered_boundary_packages
from tap.source_scan import first_party_source_roots, iter_parsed_sources


def _root_dotted(root: Path) -> str:
    """Dotted import name for a first-party source root (mirrors guard discovery).

    `tap_*` app roots import by directory name; package-mode plugin roots at
    `plugins/<slug>/tap_plugin/<slug>` import as the PEP 420 namespace `tap_plugin.<slug>`.
    """
    parts = root.relative_to(REPO_ROOT).parts
    if "tap_plugin" in parts:
        return ".".join(parts[parts.index("tap_plugin") :])
    return parts[-1]


def _boundary_dotted(package: Path) -> str:
    """The importable dotted path of a boundary package, e.g. ``tap_grid.services``."""
    for root in first_party_source_roots(REPO_ROOT):
        if package == root or package.is_relative_to(root):
            rel = package.relative_to(root).parts
            return ".".join([_root_dotted(root), *rel])
    # A boundary always lives under a first-party root (that is how it was discovered).
    raise AssertionError(f"boundary package outside every first-party root: {package}")


def _forbidden_modules() -> dict[str, Path]:
    """Map every below-gate submodule's dotted path → its boundary package.

    e.g. ``{"tap_grid.services._impl": Path(".../tap_grid/services")}``. These are the
    dotted module targets no *external* module may import.
    """
    forbidden: dict[str, Path] = {}
    for package in discovered_boundary_packages():
        dotted = _boundary_dotted(package)
        for submodule in sorted(package.glob("_*.py")):
            if submodule.stem == "__init__":
                continue  # the gateway itself, not a below-gate module
            forbidden[f"{dotted}.{submodule.stem}"] = package
    return forbidden


def _imported_module_targets(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Dotted module paths an import statement pulls in (absolute imports only).

    - ``import a.b.c``            → ``["a.b.c"]``
    - ``from a.b.c import x, y``  → ``["a.b.c"]`` (the module; names resolved separately)
    - ``from a.b import _impl``   → ``["a.b", "a.b._impl"]`` — the second catches importing a
      submodule *by name*, which is how ``from tap_grid.services import _impl`` reaches the
      below-gate module.

    Relative imports (`from ._impl import x`, `level > 0`) are omitted: they only occur
    *inside* the package, which is exactly the allowed internal case.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level:  # relative import — internal by construction
        return []
    if node.module is None:
        return []
    targets = [node.module]
    targets.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return targets


class ServiceBoundaryImportGuard(Guard):
    slug = "service-boundary-import-encapsulation"
    map_row = "Service-layer boundary import encapsulation"
    rid = "req-service-boundary-inviolability"
    description = (
        "A boundary whose front door is gated but whose below-gate modules are importable is not "
        "a boundary — a window is open. This guard fails the build if any module outside a "
        "`services/` boundary package imports that boundary's `_`-prefixed submodules (e.g. "
        "tap_grid.services._impl), which would let a caller run the pure write pipeline directly "
        "and skip the capability gate the gateway asserts. Gated `_`-named helpers re-exported "
        "from the gateway are the reviewed narrow exception and are not flagged."
    )

    def check(self) -> None:
        forbidden = _forbidden_modules()
        if not forbidden:
            return  # no boundaries expose below-gate submodules — nothing to encapsulate

        boundary_dirs = set(forbidden.values())
        roots = first_party_source_roots(REPO_ROOT)
        offenders: list[str] = []

        for parsed in iter_parsed_sources(roots):
            # A file *inside* the boundary package it imports from is the allowed internal
            # case (the gateway importing its own `_impl`). Skip files under any boundary dir
            # whose own below-gate modules they might reference.
            inside = {d for d in boundary_dirs if parsed.path.is_relative_to(d)}
            rel = parsed.path.relative_to(REPO_ROOT)
            for node in ast.walk(parsed.tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                for target in _imported_module_targets(node):
                    owner = forbidden.get(target)
                    if owner is None or owner in inside:
                        continue
                    offenders.append(
                        f"{rel}:{node.lineno} imports below-gate module `{target}` from outside "
                        f"its boundary ({owner.relative_to(REPO_ROOT)})"
                    )

        assert not offenders, (
            "Service-boundary import-encapsulation violation(s): external code imports a "
            "boundary's below-gate (`_`) module, reaching past the gateway's capability gate "
            "(spec-service-layer-boundary.md req-service-boundary-inviolability). Import the "
            "gateway's public operations instead.\n  - " + "\n  - ".join(sorted(offenders))
        )
