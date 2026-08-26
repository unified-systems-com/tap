"""Tests for tap_grid history module (context management and history service)."""

import pytest
from django.contrib.auth import get_user_model

from tap.pytest_harness import batch_ctx
from tap_grid.context import get_batch_id, set_batch_id
from tap_grid.history import (
    get_historical_records,
    get_history_service,
    get_history_user,
    is_history_enabled,
    set_history_user,
)

User = get_user_model()


class TestHistoryUserContext:
    """Tests for history user context management."""

    def test_default_user_is_none(self):
        """Unset context returns None."""
        set_history_user(None)
        assert get_history_user() is None

    @pytest.mark.django_db
    def test_set_and_get_user(self):
        """Can set and retrieve user from context."""
        user = User.objects.create_user(username="testuser", password="testpass")
        set_history_user(user)
        assert get_history_user() == user
        set_history_user(None)

    def test_set_user_to_none_clears_context(self):
        """Can clear user context by setting to None."""
        set_history_user(None)
        assert get_history_user() is None


class TestBatchIdContext:
    """Tests for batch_id context management (via tap_grid.context)."""

    def test_default_batch_id_is_none(self):
        """Unset context returns None."""
        set_batch_id(None)
        assert get_batch_id() is None

    def test_set_and_get_batch_id(self):
        """Can set and retrieve batch_id from context."""
        batch_id = "019468b7-1234-7def-8000-000000000001"
        set_batch_id(batch_id)
        assert get_batch_id() == batch_id
        set_batch_id(None)

    def test_clear_batch_id(self):
        """Can clear batch_id context."""
        set_batch_id("some-batch-id")
        set_batch_id(None)
        assert get_batch_id() is None


class TestContextIsolation:
    """Tests for context isolation between operations."""

    @pytest.mark.django_db
    def test_user_and_batch_are_independent(self):
        """User and batch_id contexts are independent."""
        user = User.objects.create_user(username="isolation", password="test")

        set_history_user(user)
        set_batch_id("batch-123")

        assert get_history_user() == user
        assert get_batch_id() == "batch-123"

        set_history_user(None)
        assert get_history_user() is None
        assert get_batch_id() == "batch-123"

        set_batch_id(None)


class TestIsHistoryEnabled:
    """Tests for is_history_enabled module function."""

    def test_returns_true_when_history_attr_present(self):
        """is_history_enabled checks for presence of 'history' attribute."""

        class WithHistory:
            history = object()

        assert is_history_enabled(WithHistory) is True

    def test_returns_false_when_no_history_attr(self):
        """is_history_enabled returns False when no 'history' attr."""

        class NoHistory:
            pass

        assert is_history_enabled(NoHistory) is False


@pytest.mark.django_db
class TestHistoryServiceRawRecords:
    """Tests for HistoryService.raw_records() — all concrete BaseModel subclasses
    have history enabled by default (inherited from BaseModel)."""

    def test_all_concrete_subclasses_have_history(self):
        """All concrete BaseModel subclasses inherit HistoricalRecords from BaseModel."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource, ConstrainedTarget

        assert is_history_enabled(ConstrainedSource) is True
        assert is_history_enabled(ConstrainedTarget) is True

    def test_character_has_history_manager(self):
        """ConstrainedSource has the history manager from django-simple-history."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        assert hasattr(ConstrainedSource, "history")

    def test_location_has_history_manager(self):
        """ConstrainedTarget also has history (inherited from BaseModel)."""
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        assert hasattr(ConstrainedTarget, "history")

    def test_new_character_has_creation_record(self):
        """New ConstrainedSource instance has at least one history record (creation)."""

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.services import create_entity

        with batch_ctx(source="test:history"):
            entity = create_entity("grid_fixtures__constrained_source", name="Test ConstrainedSource")
            character = ConstrainedSource.objects.create(entity=entity, description="Initial bio")

        svc = get_history_service(character)
        assert svc.is_enabled() is True

        records = get_historical_records(character)
        assert len(list(records)) >= 1

    def test_history_service_timeline_raises_not_implemented(self):
        """HistoryService.timeline() is backlogged — raises NotImplementedError."""
        from tap_plugin.grid_fixtures.models import ConstrainedTarget

        from tap_grid.services import create_entity

        entity = create_entity("grid_fixtures__constrained_target", name="Timeline Test")
        location = ConstrainedTarget.objects.create(entity=entity, description="A place")

        svc = get_history_service(location)
        with pytest.raises(NotImplementedError):
            svc.timeline()
