"""Integration tests for batch and history tracking.

Tests the full flow: context → model save → history recording.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

from tap.pytest_harness import batch_ctx
from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
from tap_grid.history import get_historical_records, is_history_enabled, set_history_user
from tap_grid.services import create_entity

User = get_user_model()


@pytest.mark.django_db
class TestFullHistoryFlow:
    """End-to-end tests for history tracking flow."""

    def test_create_update_history_flow(self):
        """Full flow: create → update → history records increase."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        user = User.objects.create_user(username="flowtest", password="test")
        set_history_user(user)
        try:
            with batch_ctx(source="test:history-create"):
                entity = create_entity("grid_fixtures__constrained_source", name="Frodo Baggins")
                character = ConstrainedSource.objects.create(entity=entity, description="A hobbit.")

            with batch_ctx(source="test:history-update"):
                character.description = "A brave hobbit of the Shire."
                character.save()

            records = list(get_historical_records(character))
            assert len(records) == 2  # Create + Update
        finally:
            set_history_user(None)

    def test_history_preserves_old_values(self):
        """History records preserve the state at each point in time."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        with batch_ctx(source="test:history-v1"):
            entity = create_entity("grid_fixtures__constrained_source", name="Gandalf")
            character = ConstrainedSource.objects.create(entity=entity, description="Version 1")

        with batch_ctx(source="test:history-v2"):
            character.description = "Version 2"
            character.save()

        with batch_ctx(source="test:history-v3"):
            character.description = "Version 3"
            character.save()

        records = list(character.history.all().order_by("history_date"))

        assert len(records) == 3
        assert records[0].description == "Version 1"
        assert records[1].description == "Version 2"
        assert records[2].description == "Version 3"

    def test_history_records_user_from_context(self):
        """History records the user from context."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        user = User.objects.create_user(username="historian", password="test")
        set_history_user(user)

        with batch_ctx(source="test:history-user"):
            entity = create_entity("grid_fixtures__constrained_source", name="User Test")
            character = ConstrainedSource.objects.create(entity=entity, description="Test")

        latest_record = character.history.latest("history_id")
        assert latest_record.history_user == user

        set_history_user(None)

    def test_history_without_user_context(self):
        """History works even without user in context (None)."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        set_history_user(None)

        with batch_ctx(source="test:history-no-user"):
            entity = create_entity("grid_fixtures__constrained_source", name="No User Test")
            character = ConstrainedSource.objects.create(entity=entity, description="Test")

        latest_record = character.history.latest("history_id")
        assert latest_record.history_user is None


@pytest.mark.django_db
class TestBatchIdFieldExists:
    """Tests for batch_id field on BaseModel."""

    def test_batch_id_field_exists_on_character(self):
        """ConstrainedSource model has batch_id field populated by CallerContext."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        with batch_ctx(source="test:batch-id") as batch_id:
            entity = create_entity("grid_fixtures__constrained_source", name="Batch ID Test")
            character = ConstrainedSource.objects.create(entity=entity, description="Test")

        assert hasattr(character, "batch_id")
        assert character.batch_id == batch_id

    @pytest.mark.spec("req-grid-service-batch-all-1")
    def test_batch_id_updated_on_subsequent_save(self):
        """batch_id field is updated to the latest CallerContext batch on each save."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        with batch_ctx(source="test:batch-id-create") as first_batch_id:
            entity = create_entity("grid_fixtures__constrained_source", name="Batch Set Test")
            character = ConstrainedSource.objects.create(entity=entity, description="Test")

        second_batch_id = str(uuid.uuid7())
        set_caller_context(CallerContext(user=get_caller_context().user, batch_id=second_batch_id))
        try:
            character.description = "Updated"
            character.save()
        finally:
            set_caller_context(None)

        character.refresh_from_db()
        assert character.batch_id == second_batch_id
        assert character.batch_id != first_batch_id


@pytest.mark.django_db
class TestHistoryEnabledForAllModels:
    """All concrete BaseModel subclasses now have history enabled by default."""

    def test_character_has_history(self):
        """ConstrainedSource has history (FLIP-enabled model)."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        assert is_history_enabled(ConstrainedSource) is True

    def test_location_has_history(self):
        """ConstrainedTarget has history too (all BaseModel subclasses inherit it)."""
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        assert is_history_enabled(ConstrainedTarget) is True

    def test_both_have_history_manager(self):
        """Both ConstrainedSource and ConstrainedTarget have the history manager attribute."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource, ConstrainedTarget

        assert hasattr(ConstrainedSource, "history")
        assert hasattr(ConstrainedTarget, "history")


@pytest.mark.django_db
class TestPerOperationCapability:
    """A write capability does not carry a delete (req-tap-auth-policy per-op).

    End-to-end (through the real `delete_node` verb, not the backstop primitive):
    an actor holding `grid.write` but not `grid.delete` is denied a delete. This
    proves the per-op split is enforced at the service boundary, and that the
    denial is delete-specific — the same actor IS authorized to write.
    """

    def _write_only_user(self) -> object:
        from django.contrib.auth.models import Group, Permission

        from tap_auth import sync

        sync.sync_auth()
        group, _ = Group.objects.get_or_create(name="test_write_only")
        group.permissions.set([Permission.objects.get(codename="grid_write")])
        user = User.objects.create_user(username="write-only", password="x")
        user.groups.add(group)
        return user

    def test_write_only_actor_is_denied_delete(self):
        from tap_auth import policy
        from tap_auth.errors import CapabilityDenied
        from tap_grid.services import delete_node

        ctx = CallerContext(user=self._write_only_user())
        # Sanity: the actor genuinely holds write but not delete — so a delete
        # denial below is about the operation class, not a blanket no-caps actor.
        assert policy.can(ctx, "grid.write") is True
        assert policy.can(ctx, "grid.delete") is False

        # The denial fires in the decorator's authorize(), before any DB work, so
        # a real seeded node is unnecessary — the gate never reaches the body.
        with pytest.raises(CapabilityDenied):
            delete_node(uuid.uuid4(), caller_context=ctx)
