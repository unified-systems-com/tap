"""Tests for Batch and BatchEvent models."""

import pytest

from tap_grid.history import is_history_enabled
from tap_grid.models import BaseModel, Batch, BatchEvent, BatchEventType, BatchStatus
from tap_grid.services import create_entity


@pytest.mark.django_db
class TestBatchModel:
    """Tests for Batch model."""

    def test_batch_is_entity(self):
        """Batch extends BaseModel, has an Entity."""
        entity = create_entity("batch", name="Test Batch")
        batch = Batch.objects.create(entity=entity)

        assert batch.entity == entity
        assert batch.entity.entity_type == "batch"

    @pytest.mark.spec("req-grid-service-batch-model-3")
    def test_batch_default_status_is_open(self):
        """New batches start in OPEN status."""
        entity = create_entity("batch", name="Open Test")
        batch = Batch.objects.create(entity=entity)

        assert batch.status == BatchStatus.OPEN

    def test_batch_status_transitions(self):
        """Batch status can be changed."""
        entity = create_entity("batch", name="Status Test")
        batch = Batch.objects.create(entity=entity)

        batch.status = BatchStatus.CLOSED
        batch.save()
        batch.refresh_from_db()

        assert batch.status == BatchStatus.CLOSED

    def test_batch_has_source_field(self):
        """Batch has source field for tracking origin."""
        entity = create_entity("batch", name="Source Test")
        batch = Batch.objects.create(entity=entity, source="scanner:aws")

        assert batch.source == "scanner:aws"

    def test_batch_has_metadata_field(self):
        """Batch has metadata JSONField."""
        entity = create_entity("batch", name="Metadata Test")
        batch = Batch.objects.create(entity=entity, metadata={"param1": "value1", "count": 42})

        assert batch.metadata == {"param1": "value1", "count": 42}

    def test_batch_has_timestamps(self):
        """Batch has started_at and closed_at fields."""
        entity = create_entity("batch", name="Timestamp Test")
        batch = Batch.objects.create(entity=entity)

        assert batch.started_at is not None
        assert batch.closed_at is None

    def test_batch_str_representation(self):
        """Batch __str__ includes name and status."""
        entity = create_entity("batch", name="My Batch")
        # Pass name to Batch as well — per req-grid-node-display, BaseModel.get_name()
        # is the source of truth for the spine's Entity.name projection. Leaving
        # Batch.name empty would cause save() to overwrite entity.name with "".
        batch = Batch.objects.create(entity=entity, name="My Batch")

        assert "My Batch" in str(batch)
        assert "open" in str(batch)


@pytest.mark.django_db
class TestBatchMetadataFields:
    """Tests for Batch metadata fields (name, description, description_json)."""

    def test_name_stored_and_retrieved(self):
        """name is stored and retrieved correctly."""
        entity = create_entity("batch", name="Name Test")
        batch = Batch.objects.create(entity=entity, name="My Ingestion Run")

        batch.refresh_from_db()
        assert batch.name == "My Ingestion Run"

    def test_name_defaults_to_empty_string(self):
        """name defaults to empty string when not provided."""
        entity = create_entity("batch", name="No Name")
        batch = Batch.objects.create(entity=entity)

        assert batch.name == ""

    def test_description_stored_and_retrieved(self):
        """description is stored and retrieved correctly."""
        entity = create_entity("batch", name="Desc Test")
        batch = Batch.objects.create(entity=entity, description="Imports all AWS resources.")

        batch.refresh_from_db()
        assert batch.description == "Imports all AWS resources."

    @pytest.mark.spec("req-grid-service-batch-metadata-3")
    def test_description_json_valid_shape_accepted(self):
        """description_json with valid {format, data} shape is accepted."""
        from tap_grid.batch import create_batch

        batch = create_batch(
            name="JSON Test",
            description_json={"format": "markdown", "data": {"body": "# Hello"}},
        )
        batch.refresh_from_db()
        assert batch.description_json == {"format": "markdown", "data": {"body": "# Hello"}}

    def test_description_json_none_allowed(self):
        """description_json=None is valid (field is nullable)."""
        entity = create_entity("batch", name="Null JSON")
        batch = Batch.objects.create(entity=entity, description_json=None)

        batch.refresh_from_db()
        assert batch.description_json is None

    def test_create_batch_service_accepts_name(self):
        """create_batch() passes name through to the created Batch."""
        from tap_grid.batch import create_batch

        batch = create_batch(name="Service Name Test", source="test")
        assert batch.name == "Service Name Test"

    def test_create_batch_service_accepts_description(self):
        """create_batch() passes description through to the created Batch."""
        from tap_grid.batch import create_batch

        batch = create_batch(description="Detailed description here.")
        assert batch.description == "Detailed description here."


@pytest.mark.django_db
class TestBatchInternalOnly:
    """Tests for Batch as an internal-only model type."""

    def test_batch_is_internal_only(self):
        """Batch.INTERNAL_ONLY prevents generic service-layer CRUD."""
        assert Batch.INTERNAL_ONLY is True

    @pytest.mark.spec("req-grid-entity-internal-2")
    def test_internal_only_default_is_false_on_base(self):
        """BaseModel default for INTERNAL_ONLY is False."""
        assert BaseModel.INTERNAL_ONLY is False

    def test_batch_has_history_tracking(self):
        """Batch has history tracking enabled (inherited from BaseModel)."""
        assert is_history_enabled(Batch) is True

    def test_batch_has_history_manager(self):
        """Batch has history manager for tracking changes."""
        assert hasattr(Batch, "history")


@pytest.mark.django_db
class TestBatchEventModel:
    """Tests for BatchEvent model."""

    @pytest.mark.spec("req-grid-service-batch-event-2")
    def test_batch_event_links_to_batch(self):
        """BatchEvent belongs to a Batch."""
        batch_entity = create_entity("batch", name="Parent Batch")
        batch = Batch.objects.create(entity=batch_entity)

        target_entity = create_entity("concept", name="Target")
        event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.CREATE,
            entity_id=target_entity.id,
            entity_type=target_entity.entity_type,
            model_name="Concept",
        )

        assert event.batch == batch
        assert event.batch_id == batch.id

    def test_batch_event_is_not_entity(self):
        """BatchEvent does not extend BaseModel (standalone)."""
        assert not issubclass(BatchEvent, BaseModel)

    def test_batch_event_has_uuid_primary_key(self):
        """BatchEvent uses UUIDField as primary key."""
        batch_entity = create_entity("batch", name="UUID Test Batch")
        batch = Batch.objects.create(entity=batch_entity)

        target_entity = create_entity("concept", name="Target")
        event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.CREATE,
            entity_id=target_entity.id,
            entity_type=target_entity.entity_type,
        )

        assert event.id is not None
        assert len(str(event.id)) == 36  # UUID format

    def test_batch_event_types(self):
        """BatchEvent supports all event types."""
        assert BatchEventType.CREATE.value == "create"
        assert BatchEventType.UPDATE.value == "update"
        assert BatchEventType.DELETE.value == "delete"
        assert BatchEventType.LINK.value == "link"
        assert BatchEventType.UNLINK.value == "unlink"

    def test_batch_event_has_metadata(self):
        """BatchEvent has metadata JSONField."""
        batch_entity = create_entity("batch", name="Metadata Batch")
        batch = Batch.objects.create(entity=batch_entity)

        target_entity = create_entity("concept", name="Target")
        event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.CREATE,
            entity_id=target_entity.id,
            entity_type=target_entity.entity_type,
            metadata={"custom_key": "custom_value"},
        )

        assert event.metadata == {"custom_key": "custom_value"}

    def test_batch_event_str_representation(self):
        """BatchEvent __str__ shows event type and entity info."""
        batch_entity = create_entity("batch", name="Str Batch")
        batch = Batch.objects.create(entity=batch_entity)

        target_entity = create_entity("concept", name="Target")
        event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.CREATE,
            entity_id=target_entity.id,
            entity_type="concept",
        )

        assert "create" in str(event)
        assert "concept" in str(event)

    @pytest.mark.spec("req-grid-service-batch-event-6")
    def test_batch_events_cascade_on_batch_delete(self):
        """BatchEvents are deleted when their Batch is deleted."""
        batch_entity = create_entity("batch", name="Cascade Test Batch")
        batch = Batch.objects.create(entity=batch_entity)

        target_entity = create_entity("concept", name="Target")
        event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.CREATE,
            entity_id=target_entity.id,
            entity_type=target_entity.entity_type,
        )
        event_id = event.id

        # Delete the batch (via entity cascade)
        batch_entity.delete()

        # Event should be gone
        assert not BatchEvent.objects.filter(id=event_id).exists()
