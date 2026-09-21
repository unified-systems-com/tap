"""Public-surface ceiling ratchet for the un-gateable Family-B layers.

`spec-service-layer-boundary.md` splits TAP into two families. Family A — gate-able
runtime boundaries — adopt the gateway convention (an `__all__` of *gated* operations,
enforced by `service_boundary.py`). Family B — the **un-gateable** layers (pre-boot and
boot) — run before the capability system exists, so "public at all" is the risk, not
"public but ungated." There is no gate to check; the only defense is a **small,
explicit public surface**.

This guard is the mechanical lock on that surface. For each declared sealed module it
reads the module's `__all__` (the authored public API) and, by AST, every **public**
(non-`_`) top-level `def` / `class`. Anything public but NOT in `__all__` is *leaked
surface* — an implementation helper that a `_` prefix (or a considered `__all__` entry)
should hide. The set of leaked names is frozen in a baseline that ratchets to zero:
a NEW leaked def fails the guard, and sealing one (removing it from the baseline) is the
only allowed motion. This is the "shrink first, then freeze" George asked for — the
baseline starts at the known residual and can only shrink.

Deliberately AST-only (no import): these modules run pre-Django, and the guard must be
readable without standing anything up — the same substrate as the other tree-scanners.

Spec: `spec-service-layer-boundary.md` (`req-service-boundary-family-b-surface`).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import ClassVar

from tap.guards.base import REPO_ROOT, CeilingRatchet
from tap.source_scan import parse_file

# The un-gateable Family-B modules whose public surface is frozen and ratcheted down.
# Repo-relative. Each MUST exist and declare `__all__` — a sealed module the guard
# cannot read is a fail, never a silent pass.
_SEALED_MODULES: tuple[str, ...] = (
    "tap/preboot.py",
    "tap_boot/orchestrator.py",
    "tap_boot/profile.py",
)

_ALL_VAR = "__all__"


def _read_all(tree: ast.Module) -> set[str] | None:
    """Return the module's declared `__all__` as a set, or None if none is declared.

    Must be a static list/tuple literal so it is readable without importing the module
    (these run pre-Django). A non-literal `__all__` is treated as absent → fail-closed:
    the caller then counts every public def as leaked.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == _ALL_VAR for t in node.targets):
            continue
        try:
            value: object = ast.literal_eval(node.value)
        except ValueError, SyntaxError, TypeError:
            return None
        if isinstance(value, (list, tuple)):
            return {str(item) for item in value}
        return None
    return None


def _public_defs(tree: ast.Module) -> set[str]:
    """Every **public** (non-`_`) top-level `def` / `class` name.

    Constants (bare assignments like `NAMESPACE_PACKAGE`) are intentionally NOT counted:
    the surface at issue is callable/behavioural API. A public config constant a caller
    imports is declared in `__all__` for documentation but is not leaked *behaviour*.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            names.add(node.name)
    return names


class PublicSurfaceCeilingGuard(CeilingRatchet):
    """Family-B (pre-boot / boot) public surface may only shrink, never grow."""

    slug = "family-b-public-surface"
    map_row = "Family-B public surface (pre-boot/boot)"
    rid = "req-service-boundary-family-b-surface"
    baseline_path: ClassVar[Path] = REPO_ROOT / "tap" / "guards" / "baselines" / "public_surface.txt"
    description = (
        "pre-boot and boot are un-gateable layers (they run before the capability system exists), so "
        "their only defense is a small, explicit public surface. This freezes every public (non-_) "
        "top-level def/class not in the module's __all__ as leaked surface and ratchets it to zero — a "
        "NEW public helper on these layers fails; sealing one with a _ prefix is the only allowed motion."
    )
    new_hint = (
        "A new public def/class appeared on a sealed Family-B module (pre-boot/boot). These layers must "
        "keep a minimal surface: either add it to the module's __all__ (only if it is genuinely public "
        "API an external module imports) or, far more likely, `_`-prefix it so it is a sealed internal "
        "(spec-service-layer-boundary req-service-boundary-family-b-surface)."
    )

    def measure(self) -> set[str]:
        leaked: set[str] = set()
        for rel in _SEALED_MODULES:
            path = REPO_ROOT / rel
            parsed = parse_file(path)
            assert parsed is not None, f"sealed Family-B module failed to read/parse: {path}"
            declared = _read_all(parsed.tree)
            public = _public_defs(parsed.tree)
            # No/malformed __all__ → nothing is declared public, so every public def is leaked
            # (fail-closed: a sealed module that drops its __all__ must not silently pass green).
            exported = declared if declared is not None else set()
            leaked.update(f"{rel}:{name}" for name in sorted(public - exported))
        return leaked
