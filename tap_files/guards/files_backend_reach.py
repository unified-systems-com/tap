"""File store backend reach guard — `req-tap-files-gateway-5`.

The resource-specific half of `req-service-boundary-inviolability` ("going around #2"), which the
convention leaves to the resource's owner. The backend is `tap_files.store`: whoever imports it holds
every operation on stored bytes with no capability check and no log record. So outside the store
itself, only the gateway (`tap_files/services/`) and boot's initialisation and recovery
(`tap_files/boot.py`) import it, and the operator's check command will join them (tap#1211). A
download route, a collector or a plugin calls the gateway. Where the store lives is in
`tap_files.config`, which hands out no backend. Importing anything from the gateway other than its
gated operations and its contract module is refused too, since the gateway's own handle on the
backend would otherwise be one import away; and inside the gateway package only `__init__.py` and
its `_` modules hold the backend, so a public submodule added later cannot re-export it. The
contract module may take the store's error and result types and nothing else. Tests are exempt: they exercise the backend directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots, iter_parsed_sources

_BACKEND = "tap_files.store"
_GATEWAY = "tap_files.services"
_GATEWAY_INIT = "tap_files/services/__init__.py"
_CONTRACT = "tap_files/services/contract.py"
# The store's types a contract may re-export: errors and result records, never a backend.
_CONTRACT_SOURCES = frozenset({"tap_files.store.errors", "tap_files.store.protocol"})


def _targets(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level or node.module is None:
        return []
    # `from tap_files import store` reaches the backend by naming it as an attribute.
    return [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]


def _reaches(target: str) -> bool:
    return target == _BACKEND or target.startswith(_BACKEND + ".")


def _gateway_exports(root: Path) -> frozenset[str]:
    """The gateway's ``__all__`` plus its contract module, read by AST so nothing is imported."""
    tree = ast.parse((root / _GATEWAY_INIT).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return frozenset({*ast.literal_eval(node.value), "contract"})
    return frozenset({"contract"})


def _off_gateway(node: ast.Import | ast.ImportFrom, exports: frozenset[str]) -> list[str]:
    """What an outside caller takes from the gateway package beyond its operations and contract.

    Whatever else the package binds, such as its handle on the backend, its below-gate helpers or
    a submodule added later, is an implementation detail; importing one would carry a caller
    around the capability check.
    """
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
        return [n for n in names if n.startswith(_GATEWAY + ".") and n != f"{_GATEWAY}.contract"]
    if node.level or node.module is None:
        return []
    if node.module == _GATEWAY:
        return [f"{_GATEWAY}.{a.name}" for a in node.names if a.name not in exports]
    if node.module.startswith(_GATEWAY + ".") and node.module != f"{_GATEWAY}.contract":
        return [node.module]
    return []


def _may_import_backend(rel: Path) -> bool:
    """The store itself, boot, the gateway's ``__init__`` and its below-gate ``_`` modules."""
    posix = rel.as_posix()
    if posix.startswith("tap_files/store/") or posix == "tap_files/boot.py":
        return True
    return posix.startswith("tap_files/services/") and (rel.name == "__init__.py" or rel.name.startswith("_"))


def _inside_gateway(rel: Path) -> bool:
    return rel.as_posix().startswith(("tap_files/services/", "tap_files/store/"))


class FilesBackendReachGuard(Guard):
    slug = "files-backend-reach"
    map_row = "File store backend reached only through its gateway"
    rid = "req-tap-files-gateway"
    description = (
        "Importing tap_files.store hands over every operation on stored bytes with no capability check and "
        "no log record. Only the gateway (tap_files/services), boot's initialisation and recovery "
        "(tap_files/boot.py) and tests may import it; everything else, the download route included, calls "
        "the gateway."
    )

    def check(self) -> None:
        offenders: list[str] = []
        exports = _gateway_exports(REPO_ROOT)
        for parsed in iter_parsed_sources(first_party_source_roots(REPO_ROOT)):
            rel = parsed.path.relative_to(REPO_ROOT)
            if "tests" in rel.parts:
                continue
            for node in ast.walk(parsed.tree):
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if not _may_import_backend(rel):
                    allowed = _CONTRACT_SOURCES if rel.as_posix() == _CONTRACT else frozenset()
                    reached = [t for t in _targets(node) if _reaches(t)]
                    module = node.module if isinstance(node, ast.ImportFrom) else None
                    if not (reached and module in allowed):
                        offenders.extend(f"{rel}:{node.lineno} imports {t}" for t in reached)
                if not _inside_gateway(rel):
                    offenders.extend(f"{rel}:{node.lineno} imports {t}" for t in _off_gateway(node, exports))
        assert not offenders, (  # nosec B101
            f"File store backend imported outside its gateway ({len(offenders)}):\n  "
            + "\n  ".join(sorted(set(offenders)))
            + "\n\nCall the gateway's operations, tap_files.services.__all__, instead (req-tap-files-gateway-5)."
        )
