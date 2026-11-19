"""File store backend reach guard — `req-tap-files-gateway-5`.

The resource-specific half of `req-service-boundary-inviolability` ("going around #2"), which the
convention leaves to the resource's owner. The backend is `tap_files.store`: whoever holds it holds
every operation on stored bytes with no capability check and no log record. The rule is structural,
one named holder per role, so that a module added later is refused until someone names it here:

- **The backend handle.** Outside the store itself, only `tap_files/services/_backend.py` (the
  gateway's one handle), `tap_files/boot.py` (initialisation and recovery), `tap_files/check.py`
  (the operator's check command) and `tap_files/health.py` (the health probe, which reads the
  root's markers and no object) import `tap_files.store`.
- **Types, not the backend.** Any other module of the gateway package may take the store's errors,
  result records and naming helpers (`errors`, `protocol`, `layout`), which hold no backend.
- **The handle stays inside.** Only the gateway's `__init__.py` imports `_backend`, so no public
  submodule can pass it on.
- **Outside callers** take the gated operations in the gateway's `__all__` and its `contract` module,
  and nothing else from the package. Importing the gateway module whole is how its operations are
  called, so that is allowed; reading an `_` name off it (`services._backend`) is refused like
  importing that name, in every module but the gateway's own `__init__`: its contract and
  submodules included, since they could otherwise pass the handle on.

Relative imports are resolved before any of this is checked. Where the store lives is in
`tap_files.config`, which hands out no backend. Tests are exempt: they exercise the backend directly.
This is an AST scan, so it is a tripwire, not a wall: a module bound by plain assignment, `getattr`
or `importlib` can still go around it, and the capability gate on each operation is the check that
counts.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots, iter_parsed_sources

_BACKEND = "tap_files.store"
_GATEWAY = "tap_files.services"
_HANDLE = f"{_GATEWAY}._backend"
_GATEWAY_INIT = "tap_files/services/__init__.py"
_HOLDERS = frozenset(
    {"tap_files/services/_backend.py", "tap_files/boot.py", "tap_files/check.py", "tap_files/health.py"}
)
# The store's modules a gateway module may take: errors, result records and naming, never a backend.
_TYPE_MODULES = frozenset({f"{_BACKEND}.errors", f"{_BACKEND}.protocol", f"{_BACKEND}.layout"})


def _package(rel: Path) -> list[str]:
    parts = list(rel.with_suffix("").parts)
    return parts[:-1]


def _from_module(node: ast.ImportFrom, rel: Path) -> str | None:
    """The absolute module a ``from … import`` names, relative imports resolved against *rel*."""
    if not node.level:
        return node.module
    package = _package(rel)
    if node.level - 1 > len(package):
        return None
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])]) or None


def _targets(node: ast.Import | ast.ImportFrom, rel: Path) -> list[tuple[str | None, str]]:
    """``(from-module, target)`` for each name an import pulls in.

    ``from tap_files import store`` reaches the backend by naming it as an attribute, so a
    ``from`` import yields the module and each module-plus-name.
    """
    if isinstance(node, ast.Import):
        return [(None, alias.name) for alias in node.names]
    module = _from_module(node, rel)
    if module is None:
        return []
    return [(module, module), *((module, f"{module}.{alias.name}") for alias in node.names)]


def _under(target: str, root: str) -> bool:
    return target == root or target.startswith(root + ".")


def _gateway_exports(root: Path) -> frozenset[str]:
    """The gateway's ``__all__`` plus its contract module, read by AST so nothing is imported."""
    tree = ast.parse((root / _GATEWAY_INIT).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return frozenset({*ast.literal_eval(node.value), "contract"})
    return frozenset({"contract"})


def _import_offences(node: ast.Import | ast.ImportFrom, rel: Path, exports: frozenset[str]) -> list[str]:
    posix = rel.as_posix()
    in_store, in_gateway = posix.startswith("tap_files/store/"), posix.startswith("tap_files/services/")
    found: list[str] = []
    for module, target in _targets(node, rel):
        if _under(target, _BACKEND) and not in_store and posix not in _HOLDERS:
            if not (in_gateway and module in _TYPE_MODULES):
                found.append(target)
        if _under(target, _HANDLE) and posix != _GATEWAY_INIT and posix not in _HOLDERS:
            found.append(target)
        if not in_gateway and not in_store and _under(target, _GATEWAY) and target != _GATEWAY:
            # From outside: the gated operations and the contract module, nothing else.
            name = target[len(_GATEWAY) + 1 :].split(".")[0]
            if module == _GATEWAY and name in exports:
                continue
            if name == "contract":
                continue
            found.append(target)
    return found


def _gateway_aliases(tree: ast.AST, rel: Path) -> set[str]:
    """Dotted names a file binds to the gateway module itself: ``services``, ``tap_files.services``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _GATEWAY:
                    names.add(alias.asname or _GATEWAY)
        elif isinstance(node, ast.ImportFrom) and _from_module(node, rel) == "tap_files":
            names.update(a.asname or a.name for a in node.names if a.name == "services")
    return names


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _private_reads(tree: ast.AST, rel: Path) -> list[tuple[int, str]]:
    """``services._backend`` and the like: a below-gate name read through the gateway module."""
    aliases = _gateway_aliases(tree, rel)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_") and _dotted(node.value) in aliases:
            found.append((node.lineno, f"{_GATEWAY}.{node.attr}"))
    return found


class FilesBackendReachGuard(Guard):
    slug = "files-backend-reach"
    map_row = "File store backend reached only through its gateway"
    rid = "req-tap-files-gateway"
    description = (
        "Importing tap_files.store hands over every operation on stored bytes with no capability check and "
        "no log record. Only the gateway's handle (tap_files/services/_backend.py), boot's initialisation and "
        "recovery (tap_files/boot.py), the check command (tap_files/check.py), the health probe "
        "(tap_files/health.py) and tests may import it; everything else, the download route included, "
        "calls the gateway."
    )

    def check(self) -> None:
        offenders: list[str] = []
        exports = _gateway_exports(REPO_ROOT)
        for parsed in iter_parsed_sources(first_party_source_roots(REPO_ROOT)):
            rel = parsed.path.relative_to(REPO_ROOT)
            if "tests" in rel.parts:
                continue
            for node in ast.walk(parsed.tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    offenders.extend(f"{rel}:{node.lineno} imports {t}" for t in _import_offences(node, rel, exports))
            # Every module but the gateway's own `__init__`, its contract and submodules included.
            if rel.as_posix() != _GATEWAY_INIT:
                offenders.extend(f"{rel}:{line} reads {name}" for line, name in _private_reads(parsed.tree, rel))
        assert not offenders, (  # nosec B101
            f"File store backend imported outside its gateway ({len(offenders)}):\n  "
            + "\n  ".join(sorted(set(offenders)))
            + "\n\nCall the gateway's operations, tap_files.services.__all__, instead (req-tap-files-gateway-5)."
        )
