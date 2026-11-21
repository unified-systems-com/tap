"""The harness's baseline is committed once per test database, not re-seeded in each test (tap#1280).

The auth bootstrap and the dimension vocabulary are baseline data every DB test inherits. Written
once, as the test database is set up, they are committed rows any connection can see. Written
lazily by ``default_caller_context`` inside the test's own transaction (what happened while the
session ``django_db_setup`` override was shadowed by pytest-django's), they are visible only to the
test's connection and are rolled back with it, so every DB test paid ~1.6 s to seed them again.

So the probe is a second connection: it sees committed rows only.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tap.pytest_harness import _CORE_TAP_META, _tap_test_key


@pytest.fixture
def outside_connection() -> Iterator[Any]:
    """A fresh connection to the test database, outside the test's transaction."""
    from django.db import DEFAULT_DB_ALIAS, connections

    connection = connections.create_connection(DEFAULT_DB_ALIAS)
    try:
        yield connection
    finally:
        connection.close()


def _committed(connection: Any, model: Any, **where: Any) -> bool:
    table = connection.ops.quote_name(model._meta.db_table)
    clauses = " AND ".join(f"{connection.ops.quote_name(model._meta.get_field(k).column)} = %s" for k in where)
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT 1 FROM {table} WHERE {clauses} LIMIT 1", list(where.values()))  # noqa: S608 — names from model meta
        return cursor.fetchone() is not None


@pytest.mark.django_db
@pytest.mark.spec("req-tap-test-fixtures-5")
class TestBaselineIsCommittedOnce:
    def test_dimension_vocabulary_is_committed_outside_the_test(self, outside_connection):
        from tap_grid.models import Dimension

        assert Dimension.all_objects.filter(entity_id=_CORE_TAP_META).exists()  # the test sees it either way
        assert _committed(outside_connection, Dimension, entity_id=_CORE_TAP_META), (
            "the dimension vocabulary exists only inside this test's transaction: the once-per-database "
            "seed did not run, and default_caller_context re-seeded it for this test (tap#1280)"
        )

    def test_test_actor_is_committed_outside_the_test(self, outside_connection):
        from django.contrib.auth import get_user_model

        assert _committed(outside_connection, get_user_model(), tap_builtin_key=_tap_test_key()), (
            "the tap_test actor exists only inside this test's transaction: the once-per-database "
            "auth bootstrap did not run (tap#1280)"
        )


@pytest.mark.spec("req-tap-test-fixtures-5")
def test_the_seed_rides_setup_databases_not_a_shadowable_fixture():
    """The seed is attached to the call that makes the test databases, so no fixture can shadow it."""
    import django.test.utils as test_utils

    assert getattr(test_utils.setup_databases, "tap_seeded", False)
