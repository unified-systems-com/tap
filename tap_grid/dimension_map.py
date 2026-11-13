"""Writing an entity's dimensions map (req-grid-dimension-reference, req-grid-dimension-reference-3).

Stored shape (unified-systems-com/tap#711): ``{<dimension node uuid>: {"v": <string>, "src": <how>}}``
where ``src`` is ``declared`` (a caller passed it), ``default`` (a type's ``DEFAULT_DIMENSIONS`` or an
edge type's ``default_dimensions``) or ``derived`` (a trusted collector run computed it).

Every writer goes through :func:`stamp`, which is the whole provenance rule (#712, George 2026-11-12):

- a declaration or caller map may key by dimension name or node uuid; both resolve through the
  static vocabulary (never minted, aws-build Q48a);
- defaults are stamped ``src: default``, a caller's values ``src: declared``, and a caller value beats
  a default, including an empty one (#712);
- ``src: default`` is never accepted from a caller (Q48d); ``src: derived`` only when the writer is a
  trusted collector run (Q48e, Q54 D3), otherwise it is reset to ``declared``;
- a value outside a bounded dimension's ``values`` is refused (Q47), and so is an empty value unless
  the dimension declares ``empty_is_meaningful`` (Q46a, Q59 D5);
- null is never stored (Q46a).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tap_grid.dimension_names import declared

SRC_DECLARED = "declared"
SRC_DEFAULT = "default"
SRC_DERIVED = "derived"
SOURCES = frozenset({SRC_DECLARED, SRC_DEFAULT, SRC_DERIVED})


class DimensionWriteError(ValueError):
    """A dimension value a writer may not store."""


class StampedDimensions(dict[str, dict[str, str]]):
    """A map already in stored shape, with provenance settled by :func:`supplied`.

    Writers below the entry points (the model save, the service pipeline) take this as is, so a
    trust decision made at the entry point (the importer, under a collector run) is not re-made, and
    an untrusted raw map is never mistaken for a settled one.
    """


def _refuse_meaningless_empty(found: Any, value: str, where: str) -> None:
    """An empty value is observed-empty only where the dimension declares it means something
    (``empty_is_meaningful``, aws-build Q46a / Q59 D5); everywhere else it is refused."""
    if value == "" and not getattr(found, "empty_is_meaningful", False):
        raise DimensionWriteError(
            f"{where}: an empty value for {found.name!r} is refused: the dimension does not declare empty as meaningful"
        )


def _entry(name_or_id: str, value: Any, *, trusted: bool, where: str) -> tuple[str, dict[str, str]]:
    found = declared(name_or_id)
    src = SRC_DECLARED
    if isinstance(value, Mapping):
        if set(value) - {"v", "src"}:
            raise DimensionWriteError(f"{where}: a dimension value object holds only 'v' and 'src'")
        src = value.get("src", SRC_DECLARED)
        value = value.get("v")
        if src not in SOURCES:
            raise DimensionWriteError(f"{where}: src must be one of {sorted(SOURCES)}, got {src!r}")
        if src == SRC_DEFAULT:
            raise DimensionWriteError(
                f"{where}: src 'default' is stamped by the grid from a type's declared defaults, never accepted from a writer"
            )
        if src == SRC_DERIVED and not trusted:
            src = SRC_DECLARED
    if not isinstance(value, str):
        raise DimensionWriteError(f"{where}: dimension {found.name!r} needs a string value, got {type(value).__name__}")
    _refuse_meaningless_empty(found, value, where)
    if not found.accepts(value):
        raise DimensionWriteError(
            f"{where}: {value!r} is not an allowed value of the bounded dimension {found.name!r} ({list(found.values or ())})"
        )
    return found.id, {"v": value, "src": src}


def supplied(raw: Mapping[str, Any] | None, *, trusted: bool = False, where: str = "dimensions") -> StampedDimensions:
    """A writer's map in stored shape, with its provenance settled.

    Keys are names or uuids. A value is a string or ``{"v": …, "src": …}``. A null value is not a
    value: it is dropped here, and only :func:`patch` reads it as a removal (Q46b).
    """
    if isinstance(raw, StampedDimensions):
        return raw
    out = StampedDimensions()
    for key, value in (raw or {}).items():
        if value is None:
            continue
        if not isinstance(key, str):
            raise DimensionWriteError(f"{where}: dimension keys are names or node ids, got {key!r}")
        dim_id, entry = _entry(key, value, trusted=trusted, where=where)
        out[dim_id] = entry
    return out


def defaults(declared_defaults: Mapping[str, str] | None) -> StampedDimensions:
    """A type's declared defaults in stored shape, each ``src: default``."""
    out = StampedDimensions()
    for key, value in (declared_defaults or {}).items():
        found = declared(key)
        _refuse_meaningless_empty(found, value, "default dimensions")
        if not found.accepts(value):
            raise DimensionWriteError(
                f"default dimensions: {value!r} is not an allowed value of the bounded dimension {found.name!r}"
            )
        out[found.id] = {"v": value, "src": SRC_DEFAULT}
    return out


def stamp(
    declared_defaults: Mapping[str, str] | None,
    caller: Mapping[str, Any] | None,
    *,
    trusted: bool = False,
    where: str = "dimensions",
) -> StampedDimensions:
    """The stored map for a create or a replace: the type's defaults, then the caller's values over
    them. The caller wins on a conflict, even with an empty value (#712)."""
    out = defaults(declared_defaults)
    out.update(supplied(caller, trusted=trusted, where=where))
    return out


def patch(stored: Mapping[str, Any] | None, changes: Mapping[str, Any], *, trusted: bool = False) -> StampedDimensions:
    """Apply a patch (Q46b): an omitted key is unchanged, a key set to null is removed, any other key
    is set with its provenance settled as :func:`supplied` settles it."""
    out = StampedDimensions(dict(stored or {}))
    for key, value in changes.items():
        if value is None:
            out.pop(declared(key).id, None)
        else:
            dim_id, entry = _entry(key, value, trusted=trusted, where="dimensions patch")
            out[dim_id] = entry
    return out


def rederive(stored: Mapping[str, Any] | None, derived_values: Mapping[str, str]) -> StampedDimensions:
    """Write derived values (Q46c): a derived value replaces an absent or derived one, and never a
    declared or default one."""
    out = StampedDimensions(dict(stored or {}))
    for key, value in derived_values.items():
        dim_id, entry = _entry(key, {"v": value, "src": SRC_DERIVED}, trusted=True, where="re-derivation")
        current = out.get(dim_id)
        if current is None or (isinstance(current, Mapping) and current.get("src") == SRC_DERIVED):
            out[dim_id] = entry
    return out
