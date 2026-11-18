"""File store backend reach guard — `req-tap-files-gateway-5`.

The resource-specific half of `req-service-boundary-inviolability` ("going around #2"), which the
convention leaves to the resource's owner. The backend is `tap_files.store`: whoever imports it holds
every operation on stored bytes with no capability check and no log record. So outside the store
itself, only the gateway (`tap_files/services/`) and boot's initialisation and recovery
(`tap_files/boot.py`) import it, and the operator's check command will join them (tap#1211). A
download route, a collector or a plugin calls the gateway. Where the store lives is in
`tap_files.config`, which hands out no backend. Importing anything from the gateway other than its
gated operations and its contract module is refused too, since the gateway's own handle on the
backend would otherwise be one import away. Tests are exempt: they exercise the backend directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import first_party_source_roots, iter_parsed_sources

_BACKEND = "tap_files.store"
_GATEWAY = "tap_files.services"
_GATEWAY_INIT = "tap_files/services/__init__.py"
_ALLOWED_DIRS = ("tap_files/store", "tap_files/services")
_ALLOWED_FILES = frozenset({"tap_files/boot.py"})


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
    """Names taken from the gateway module that are not its gated operations or its contract.

    Whatever else the module binds, such as its handle on the backend or its below-gate helpers,
    is an implementation detail; importing one would carry a caller around the capability check.
    """
    if not isinstance(node, ast.ImportFrom) or node.level or node.module != _GATEWAY:
        return []
    return [f"{_GATEWAY}.{a.name}" for a in node.names if a.name not in exports]


def _allowed(rel: Path) -> bool:
    posix = rel.as_posix()
    return "tests" in rel.parts or posix in _ALLOWED_FILES or any(posix.startswith(d + "/") for d in _ALLOWED_DIRS)


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
            if _allowed(rel):
                continue
            for node in ast.walk(parsed.tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    offenders.extend(f"{rel}:{node.lineno} imports {t}" for t in _targets(node) if _reaches(t))
                    offenders.extend(f"{rel}:{node.lineno} imports {t}" for t in _off_gateway(node, exports))
        assert not offenders, (  # nosec B101
            f"File store backend imported outside its gateway ({len(offenders)}):\n  "
            + "\n  ".join(sorted(set(offenders)))
            + "\n\nCall the gateway's operations, tap_files.services.__all__, instead (req-tap-files-gateway-5)."
        )
