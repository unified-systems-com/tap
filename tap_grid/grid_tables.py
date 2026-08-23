"""Single source of truth for "which DB tables hold TAP-managed grid data".

Implements the derivation half of ``req-grid-table-classification.sec``
(spec-grid-security.md). Classification is declared on the models —
``GRID_TABLE_ROLE = "domain"`` once on ``BaseModel`` (inherited by every
subclass), ``"spine"`` explicitly on ``Entity``/``EntityType`` — and this module
is the only place it is read. Both security consumers derive from here: the
in-code ORM read backstop (:mod:`tap_grid.read_guard`,
req-tap-auth-orm-read-backstop) and the DB-level least-privilege grant for the
read-only search role (:mod:`tap_grid.search_role`,
req-grid-search-readonly-role.sec). Table names come only from each model's
``Meta.db_table`` — no name is ever written as a string literal here or in the
consumers.

Classification is a privilege boundary, so *who declared it* is checked, not
just the value (req-grid-table-classification.sec-4): an explicit
``GRID_TABLE_ROLE`` is honored only when the declaring class is one of the
sanctioned ``tap_grid`` declaration sites. Any other declarer — e.g. a plain
non-BaseModel plugin model claiming ``"spine"``, the door
``BaseModel.__init_subclass__`` cannot see — is a fail-closed error plus a
``security`` Flaw, never silently honored and never silently skipped.

The one deliberate consumer asymmetry, pinned by test
(tap_grid/tests/test_grid_tables.py): ``Entity`` IS granted to the search role
(the executor always reads the spine) but is NOT read-guarded (its reads are
pervasive below the service boundary and the Entity API carries its own gate —
the named open edge of req-tap-auth-orm-read-backstop). Hence
``search_role_grant_tables() == read_guarded_tables() | {Entity's table}``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import models

logger = logging.getLogger(__name__)

_VALID_ROLES = ("domain", "spine")


def _sanctioned_declarers() -> tuple[type, ...]:
    """The only classes that may declare ``GRID_TABLE_ROLE`` in their body.

    Adding a class here is a deliberate, reviewed act: it must land together
    with a spec update to req-grid-table-classification.sec and the pin test.
    """
    from tap_grid.models import BaseModel, Entity, EntityType

    return (BaseModel, Entity, EntityType)


def _declaring_class(model: type[models.Model]) -> type:
    """Return the class in ``model``'s MRO whose own body declares GRID_TABLE_ROLE.

    The attribute is guaranteed present on ``model`` (callers check first), so
    some class in the MRO owns it.
    """
    for klass in model.__mro__:
        if "GRID_TABLE_ROLE" in klass.__dict__:
            return klass
    raise AssertionError(f"{model!r} has GRID_TABLE_ROLE but no MRO declarer")  # pragma: no cover


def classified_models() -> dict[type[models.Model], str]:
    """Every loaded, concrete, classified model, mapped to its role.

    TAP-IMPLEMENTS: req-grid-table-classification.sec@cfce29c3a97f/f4b1ca0afdf2 (derivation) — the one
        derivation of "which tables are grid tables". The ORM read backstop and the
        search-role DB grant both read this; they must never re-derive it, which is the
        divergence that made this the audit's highest-severity finding.

    Scans ``apps.get_models()`` (the ground truth for what this process loaded;
    abstract models are excluded by construction). A model without
    ``GRID_TABLE_ROLE`` anywhere in its MRO is not a grid table and is ignored.
    A classified model whose declaration comes from outside the sanctioned
    ``tap_grid`` sites, or carries an unknown value, fails closed
    (req-grid-table-classification.sec-4).
    """
    from django.apps import apps

    from tap.flaws import HANDLING_REFUSE_BOOT, AppFlaw

    sanctioned = _sanctioned_declarers()
    classified: dict[type[models.Model], str] = {}
    for model in apps.get_models():
        role = getattr(model, "GRID_TABLE_ROLE", None)
        if role is None:
            continue
        declarer = _declaring_class(model)
        if declarer not in sanctioned:
            AppFlaw.report(
                invariant_id="grid_table_classification_foreign_declarer",
                tags=["security"],
                handling=HANDLING_REFUSE_BOOT,
                message=(
                    f"model {model._meta.label} carries GRID_TABLE_ROLE={role!r} declared by "
                    f"{declarer.__module__}.{declarer.__qualname__}; grid-table classification "
                    "may only be declared by tap_grid (req-grid-table-classification.sec-4)"
                ),
                logger=logger,
                model=model._meta.label,
                declarer=f"{declarer.__module__}.{declarer.__qualname__}",
            )
            raise ImproperlyConfigured(
                f"{model._meta.label}: GRID_TABLE_ROLE declared outside tap_grid "
                f"(by {declarer.__module__}.{declarer.__qualname__}) — a model can never "
                "classify itself into the grid security tables "
                "(req-grid-table-classification.sec-4)."
            )
        if role not in _VALID_ROLES:
            raise ImproperlyConfigured(
                f"{model._meta.label}: unknown GRID_TABLE_ROLE {role!r} "
                f"(valid: {_VALID_ROLES}) — req-grid-table-classification.sec."
            )
        classified[model] = role
    return classified


def spine_models() -> set[type[models.Model]]:
    """The models classified ``"spine"`` — pinned by test to {Entity, EntityType}."""
    return {model for model, role in classified_models().items() if role == "spine"}


def grid_tables() -> set[str]:
    """Every classified grid table (domain + spine), by ``Meta.db_table``."""
    return {model._meta.db_table for model in classified_models()}


def read_guarded_tables() -> set[str]:
    """Tables the ORM read backstop enforces on: every classified table except Entity.

    ``Entity`` is the deliberate exemption (see module docstring); it is
    expressed against the model class, never a table-name string.
    """
    from tap_grid.models import Entity

    return grid_tables() - {Entity._meta.db_table}


def search_role_grant_tables() -> set[str]:
    """Tables the read-only search role may ``SELECT``: every classified table.

    Invariant (pinned by test): equals :func:`read_guarded_tables` plus
    ``Entity``'s table. Provisioning additionally reconciles this set against
    the tables that actually exist in the database before granting
    (req-grid-table-classification.sec-6, in :mod:`tap_grid.search_role`).
    """
    return grid_tables()


def existing_public_tables(cursor: Any) -> set[str]:
    """The tables that actually exist in the ``public`` schema.

    Args:
        cursor: An open DB cursor (the caller owns the connection/transaction).

    Returns:
        Every table name in ``public``.
    """
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    return {row[0] for row in cursor.fetchall()}


def classified_but_absent(cursor: Any, *, declared: Iterable[str] | None = None) -> list[str]:
    """Classified grid tables whose table does not exist in the database.

    The single derivation of "the classification and the schema disagree". Two
    consumers ask this same question for different reasons and must not compute
    it separately: search-role provisioning skips absent tables before granting
    (req-grid-table-classification.sec-6), and the grid-population health probe
    reports them (req-tap-health-probes-8). A model class can exist without its
    table — a test-fixture model, or a registered type whose migration has not
    run — which is exactly the schema/registry divergence worth surfacing.

    Args:
        cursor: An open DB cursor.
        declared: Table names to check; defaults to every classified grid table.

    Returns:
        Sorted names of classified tables missing from the database.
    """
    expected = sorted(declared) if declared is not None else sorted(grid_tables())
    existing = existing_public_tables(cursor)
    return [table for table in expected if table not in existing]
