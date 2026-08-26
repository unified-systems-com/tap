"""Tests for FLIP field-path map logic (tap_grid.flip)."""

import itertools

import pytest

from tap.pytest_harness import batch_ctx
from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
from tap_grid.flip import update_flip_map

_counter = itertools.count()


def make_instance(schemas=None, internal_only=False):
    """Create a fake BaseModel-like instance with SERVICE_CRUD_SCHEMA (not FLIP_CONFIG)."""
    cls = type(
        f"FakeModel_{next(_counter)}",
        (),
        {
            "SERVICE_CRUD_SCHEMA": schemas or {},
            "INTERNAL_ONLY": internal_only,
        },
    )
    instance = object.__new__(cls)
    instance.flip_map = {}
    return instance


@pytest.fixture(autouse=True)
def reset_context():
    """Clear the batch scope between tests, keeping the (test) actor.

    FLIP tests need a clean batch context, but service writes (e.g. create_batch
    in batch_ctx) still require a named actor under the on-by-default enforcement,
    so we preserve the actor the root fixture bound and only drop the batch_id.
    """
    prev = get_caller_context()
    actor = prev.user if prev is not None else None
    set_caller_context(CallerContext(user=actor, batch_id=None))
    yield
    set_caller_context(prev)


class TestUpdateFlipMapNoOp:
    """update_flip_map is a no-op when there are no service-writeable fields."""

    def test_returns_false_when_no_service_schemas(self):
        instance = make_instance({})
        assert update_flip_map(instance, ["status"], "batch-123") is False

    def test_returns_false_when_no_properties_in_schemas(self):
        instance = make_instance(
            {
                "create": {"type": "object"},
                "patch": {"type": "object"},
                "replace": {"type": "object"},
            }
        )
        assert update_flip_map(instance, ["status"], "batch-123") is False

    def test_returns_false_for_internal_only(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}}},
            },
            internal_only=True,
        )
        assert update_flip_map(instance, ["status"], "batch-123") is False

    def test_no_mutation_for_internal_only(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}}},
            },
            internal_only=True,
        )
        update_flip_map(instance, ["status"], "batch-123")
        assert instance.flip_map == {}


class TestUpdateFlipMapNoBatch:
    """No batch_id: returns False silently (no error, no stamping)."""

    def test_returns_false_when_no_batch_id(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}}},
            }
        )
        result = update_flip_map(instance, ["status"], None)
        assert result is False

    def test_no_exception_when_no_batch_id(self):
        """Default-on FLIP does not raise when no batch_id is present."""
        instance = make_instance(
            {
                "patch": {"type": "object", "properties": {"name": {"type": "string"}}},
                "create": {"type": "object", "properties": {"name": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"name": {"type": "string"}}},
            }
        )
        # Should not raise NoBatchContextError
        result = update_flip_map(instance, None, None)
        assert result is False


class TestUpdateFlipMapPartialSave:
    """update_flip_map stamps only fields in both changed_fields and the tracked set."""

    def test_stamps_tracked_changed_field(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}, "name": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}, "name": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}, "name": {"type": "string"}}},
            }
        )
        result = update_flip_map(instance, ["status"], "batch-abc")
        assert result is True
        assert instance.flip_map == {"status": "batch-abc"}

    def test_ignores_untracked_changed_fields(self):
        """Fields not in SERVICE_CRUD_SCHEMA are not stamped."""
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}}},
            }
        )
        result = update_flip_map(instance, ["internal_field", "description"], "batch-abc")
        assert result is False
        assert instance.flip_map == {}

    def test_stamps_multiple_tracked_fields(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"a": {}, "b": {}, "c": {}}},
                "patch": {"type": "object", "properties": {"a": {}, "b": {}, "c": {}}},
                "replace": {"type": "object", "properties": {"a": {}, "b": {}, "c": {}}},
            }
        )
        update_flip_map(instance, ["a", "b"], "batch-xyz")
        assert instance.flip_map == {"a": "batch-xyz", "b": "batch-xyz"}

    def test_returns_false_when_no_overlap(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {"type": "string"}}},
                "patch": {"type": "object", "properties": {"status": {"type": "string"}}},
                "replace": {"type": "object", "properties": {"status": {"type": "string"}}},
            }
        )
        result = update_flip_map(instance, ["name"], "batch-abc")
        assert result is False


class TestUpdateFlipMapFullSave:
    """When changed_fields is None (full save), all service-writeable fields are stamped."""

    def test_stamps_all_schema_fields_on_full_save(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"a": {}, "b": {}}},
                "patch": {"type": "object", "properties": {"a": {}, "b": {}}},
                "replace": {"type": "object", "properties": {"a": {}, "b": {}}},
            }
        )
        result = update_flip_map(instance, None, "batch-full")
        assert result is True
        assert instance.flip_map == {"a": "batch-full", "b": "batch-full"}


class TestUpdateFlipMapOverwrite:
    """Subsequent writes overwrite prior batch IDs for the same field."""

    def test_overwrites_previous_batch_id(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {}}},
                "patch": {"type": "object", "properties": {"status": {}}},
                "replace": {"type": "object", "properties": {"status": {}}},
            }
        )
        instance.flip_map = {"status": "old-batch"}
        update_flip_map(instance, ["status"], "new-batch")
        assert instance.flip_map["status"] == "new-batch"

    def test_preserves_unrelated_flip_entries(self):
        instance = make_instance(
            {
                "create": {"type": "object", "properties": {"status": {}, "name": {}}},
                "patch": {"type": "object", "properties": {"status": {}, "name": {}}},
                "replace": {"type": "object", "properties": {"status": {}, "name": {}}},
            }
        )
        instance.flip_map = {"name": "prior-batch"}
        update_flip_map(instance, ["status"], "new-batch")
        assert instance.flip_map["name"] == "prior-batch"
        assert instance.flip_map["status"] == "new-batch"


@pytest.mark.django_db
class TestUpdateFlipMapIntegration:
    """Integration: flip_map is persisted atomically with the save."""

    def test_flip_map_written_on_create(self):
        """Default-on FLIP writes flip_map for service-writeable fields on create."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.services import create_entity

        with batch_ctx(source="test:flip") as batch_id:
            entity = create_entity("grid_fixtures__constrained_source", name="Frodo")
            char = ConstrainedSource.objects.create(entity=entity, name="Frodo", description="A hobbit")

        char.refresh_from_db()
        assert char.flip_map.get("description") == batch_id
        assert char.flip_map.get("name") == batch_id

    def test_flip_map_updated_on_partial_save(self):
        """Partial save (update_fields) stamps only the changed tracked field."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.services import create_entity

        with batch_ctx(source="test:flip-create"):
            entity = create_entity("grid_fixtures__constrained_source", name="Sam")
            char = ConstrainedSource.objects.create(entity=entity, description="A gardener")

        with batch_ctx(source="test:flip-update") as batch_id2:
            char.description = "Gardener of the Shire"
            char.save(update_fields=["description"])

        char.refresh_from_db()
        assert char.flip_map.get("description") == batch_id2

    def test_untracked_field_not_in_flip_map(self):
        """System-managed fields (not in SERVICE_CRUD_SCHEMA) are absent from flip_map."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.services import create_entity

        with batch_ctx(source="test:flip-untracked"):
            entity = create_entity("grid_fixtures__constrained_source", name="Gandalf")
            char = ConstrainedSource.objects.create(entity=entity, name="Gandalf", description="A wizard")

        char.refresh_from_db()
        # batch_id and flip_map themselves are not service-writeable → not in flip_map
        assert "batch_id" not in char.flip_map
        assert "flip_map" not in char.flip_map
        # name and bio are service-writeable → in flip_map
        assert "description" in char.flip_map
        assert "name" in char.flip_map

    def test_no_flip_stamping_without_batch_context(self):
        """Direct ORM save without CallerContext leaves flip_map empty."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.services import create_entity

        entity = create_entity("grid_fixtures__constrained_source", name="Tom Bombadil")
        char = ConstrainedSource.objects.create(entity=entity, description="A mystery")
        char.refresh_from_db()
        assert char.flip_map == {}
