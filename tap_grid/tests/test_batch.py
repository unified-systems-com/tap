"""Tests for batch service layer."""

import pytest
from django.contrib.auth import get_user_model

from tap_grid.batch import (
    close_batch,
    create_batch,
    fail_batch,
    get_batch,
    get_batch_events,
    get_entity_batches,
    produced_batches,
    produced_batches_by_producer,
    record_batch_event,
)
from tap_grid.context import set_batch_id
from tap_grid.history import set_history_user
from tap_grid.models import BatchEventType, BatchStatus
from tap_grid.services import create_edge, create_entity

User = get_user_model()


@pytest.mark.django_db
class TestCreateBatch:
    """Tests for create_batch function."""

    def test_creates_batch_with_entity(self):
        """create_batch creates a Batch with backing Entity."""
        batch = create_batch(source="test:create")

        assert batch.entity is not None
        assert batch.entity.entity_type == "batch"

    def test_batch_starts_open(self):
        """Created batch has OPEN status."""
        batch = create_batch()

        assert batch.status == BatchStatus.OPEN

    def test_batch_has_source(self):
        """create_batch sets source field."""
        batch = create_batch(source="scanner:aws")

        assert batch.source == "scanner:aws"

    def test_batch_has_actor(self):
        """create_batch can set actor."""
        user = User.objects.create_user(username="batchactor", password="test")
        batch = create_batch(actor=user)

        assert batch.actor == user

    def test_batch_actor_from_context(self):
        """create_batch falls back to context user."""
        user = User.objects.create_user(username="contextactor", password="test")
        set_history_user(user)

        try:
            batch = create_batch()
            assert batch.actor == user
        finally:
            set_history_user(None)

    def test_batch_has_name(self):
        """create_batch sets name on entity."""
        batch = create_batch(name="My Test Batch")

        assert batch.entity.name == "My Test Batch"

    def test_batch_has_metadata(self):
        """create_batch sets metadata."""
        batch = create_batch(metadata={"key": "value"})

        assert batch.metadata == {"key": "value"}


@pytest.mark.django_db
class TestCloseBatch:
    """Tests for close_batch function."""

    def test_close_batch_sets_status_closed(self):
        """close_batch sets status to CLOSED."""
        batch = create_batch()
        close_batch(batch)

        batch.refresh_from_db()
        assert batch.status == BatchStatus.CLOSED

    def test_close_batch_sets_closed_at(self):
        """close_batch sets closed_at timestamp."""
        batch = create_batch()
        assert batch.closed_at is None

        close_batch(batch)
        batch.refresh_from_db()

        assert batch.closed_at is not None

    def test_close_batch_returns_batch(self):
        """close_batch returns the updated batch."""
        batch = create_batch()
        result = close_batch(batch)

        assert result == batch
        assert result.status == BatchStatus.CLOSED

    def test_cannot_close_already_closed_batch(self):
        """close_batch raises ValueError if batch not open."""
        batch = create_batch()
        close_batch(batch)

        with pytest.raises(ValueError, match="Cannot close batch"):
            close_batch(batch)

    def test_cannot_close_failed_batch(self):
        """close_batch raises ValueError if batch is failed."""
        batch = create_batch()
        fail_batch(batch)

        with pytest.raises(ValueError, match="Cannot close batch"):
            close_batch(batch)


@pytest.mark.django_db
class TestFailBatch:
    """Tests for fail_batch function."""

    def test_fail_batch_sets_status_failed(self):
        """fail_batch sets status to FAILED."""
        batch = create_batch()
        fail_batch(batch)

        batch.refresh_from_db()
        assert batch.status == BatchStatus.FAILED

    def test_fail_batch_sets_error_message(self):
        """fail_batch sets error_message."""
        batch = create_batch()
        fail_batch(batch, error_message="Something went wrong")

        batch.refresh_from_db()
        assert batch.error_message == "Something went wrong"

    def test_fail_batch_sets_closed_at(self):
        """fail_batch sets closed_at timestamp."""
        batch = create_batch()
        fail_batch(batch)

        batch.refresh_from_db()
        assert batch.closed_at is not None

    def test_cannot_fail_closed_batch(self):
        """fail_batch raises ValueError if batch not open."""
        batch = create_batch()
        close_batch(batch)

        with pytest.raises(ValueError, match="Cannot fail batch"):
            fail_batch(batch)


@pytest.mark.django_db
class TestRecordBatchEvent:
    """Tests for record_batch_event function."""

    def test_records_event_in_batch(self):
        """record_batch_event creates BatchEvent."""
        batch = create_batch()
        set_batch_id(str(batch.entity.id))

        try:
            entity = create_entity("concept", name="Test")
            event = record_batch_event(
                entity=entity,
                event_type=BatchEventType.CREATE,
                model_name="Concept",
            )

            assert event is not None
            assert event.batch == batch
            assert event.event_type == BatchEventType.CREATE
            assert event.entity_id == entity.id
            assert event.model_name == "Concept"
        finally:
            set_batch_id(None)

    def test_returns_none_without_context(self):
        """No event recorded when no batch context."""
        entity = create_entity("concept", name="Test")

        event = record_batch_event(
            entity=entity,
            event_type=BatchEventType.CREATE,
        )

        assert event is None

    def test_explicit_batch_id_overrides_context(self):
        """Explicit batch_id parameter overrides context."""
        batch1 = create_batch(name="Batch 1")
        batch2 = create_batch(name="Batch 2")

        set_batch_id(str(batch1.entity.id))

        try:
            entity = create_entity("concept", name="Test")
            event = record_batch_event(
                entity=entity,
                event_type=BatchEventType.CREATE,
                batch_id=str(batch2.entity.id),  # Override
            )

            assert event is not None
            assert event.batch == batch2
        finally:
            set_batch_id(None)


@pytest.mark.django_db
class TestGetBatch:
    """Tests for get_batch function."""

    def test_retrieves_batch_by_entity_id(self):
        """get_batch retrieves batch by entity ID."""
        batch = create_batch(name="Get Test")
        batch_id = str(batch.entity.id)

        result = get_batch(batch_id)

        assert result is not None
        assert result.id == batch.id

    def test_returns_none_for_invalid_id(self):
        """get_batch returns None for non-existent ID."""
        result = get_batch("00000000-0000-0000-0000-000000000000")

        assert result is None


@pytest.mark.django_db
class TestGetBatchEvents:
    """Tests for get_batch_events function."""

    def test_retrieves_events_for_batch(self):
        """get_batch_events returns events for a batch."""
        batch = create_batch()
        batch_id = str(batch.entity.id)
        set_batch_id(batch_id)

        try:
            entity1 = create_entity("concept", name="Test 1")
            entity2 = create_entity("concept", name="Test 2")

            record_batch_event(entity1, BatchEventType.CREATE, "Concept")
            record_batch_event(entity2, BatchEventType.CREATE, "Concept")

            events = get_batch_events(batch_id)

            assert len(events) == 2
        finally:
            set_batch_id(None)

    def test_returns_empty_for_invalid_batch(self):
        """get_batch_events returns empty list for non-existent batch."""
        events = get_batch_events("00000000-0000-0000-0000-000000000000")

        assert events == []


@pytest.mark.django_db
class TestGetEntityBatches:
    """Tests for get_entity_batches function."""

    def test_retrieves_batches_for_entity(self):
        """get_entity_batches returns batches that affected an entity."""
        batch = create_batch()
        set_batch_id(str(batch.entity.id))

        try:
            entity = create_entity("concept", name="Test")
            record_batch_event(entity, BatchEventType.CREATE, "Concept")

            batches = get_entity_batches(entity.id)

            assert len(batches) == 1
            assert batches[0].id == batch.id
        finally:
            set_batch_id(None)

    def test_returns_empty_for_untracked_entity(self):
        """get_entity_batches returns empty list for entity not in any batch."""
        entity = create_entity("concept", name="Untracked")

        batches = get_entity_batches(entity.id)

        assert batches == []


@pytest.mark.django_db
class TestProducedBatches:
    """produced_batches / produced_batches_by_producer over PRODUCED_BATCH edges.

    The canonical replacement for the removed CollectionJob.grift_batches field
    (req-grid-edge-produced-batch). The disposition edge property partitions the
    targets into imported vs skipped.
    """

    def _producer(self, name="run"):
        return create_entity("concept", name=name)

    def _link(self, producer, batch, disposition):
        create_edge(
            from_entity=producer,
            to_entity=batch.entity,
            edge_type="PRODUCED_BATCH",
            properties={"disposition": disposition},
        )

    def test_groups_by_disposition(self):
        producer = self._producer()
        imported = create_batch(source="t:imp")
        skipped = create_batch(source="t:skip")
        self._link(producer, imported, "imported")
        self._link(producer, skipped, "skipped")

        result = produced_batches(producer.id)

        assert result["imported"] == [str(imported.entity_id)]
        assert result["skipped"] == [str(skipped.entity_id)]

    def test_producer_with_no_edges_returns_empty_lists(self):
        producer = self._producer()

        assert produced_batches(producer.id) == {"imported": [], "skipped": []}

    def test_bulk_partitions_per_producer(self):
        p1 = self._producer("run-1")
        p2 = self._producer("run-2")
        b1 = create_batch(source="t:1")
        b2 = create_batch(source="t:2")
        self._link(p1, b1, "imported")
        self._link(p2, b2, "skipped")

        out = produced_batches_by_producer([p1.id, p2.id])

        assert out[str(p1.id)] == {"imported": [str(b1.entity_id)], "skipped": []}
        assert out[str(p2.id)] == {"imported": [], "skipped": [str(b2.entity_id)]}

    def test_bulk_empty_input_returns_empty_dict(self):
        assert produced_batches_by_producer([]) == {}


@pytest.mark.django_db
class TestAutoCreatedBatchAttribution:
    """A batch the service layer mints must be named and attributed.

    req-grid-service-batch-metadata-1: `name` is required on every batch, including
    the ones the service layer mints, and `source` names the service layer as the
    producer. (The name itself now always comes from the caller or its context,
    req-grid-service-batch-label-required.) The defect this covers: `Batch.get_name()` projects the Batch's
    name down onto `Entity.name` on every save, so an auto-created batch that
    was handed no `name=` erased the Entity name a hand-rolled create had just
    set — presence-is-not-correctness on the spine.
    """

    def test_auto_created_batch_keeps_its_name(self):
        """The spine projection must not blank the name the service layer set."""
        from tap_grid.services import create_node

        result = create_node("grid_fixtures__constrained_source", {"name": "Frodo"})
        assert result.success

        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.name != ""
        # The Entity projection agrees with the Batch — the sync ran and found
        # something true to project, rather than overwriting with "".
        assert batch.entity.name == batch.name

    def test_auto_created_batch_carries_a_source(self):
        """`source=""` must no longer mean "the service layer made this"."""
        from tap_grid.batch import AUTO_BATCH_SOURCE
        from tap_grid.services import create_node

        result = create_node("grid_fixtures__constrained_source", {"name": "Merry"})
        batch = get_batch(result.batch_id)

        assert batch is not None
        assert batch.source == AUTO_BATCH_SOURCE

    def test_caller_supplied_batch_is_left_alone(self):
        """_ensure_batch stays idempotent: a caller's own batch keeps its identity."""
        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node

        mine = create_batch(name="My own batch", source="test:caller-owned")
        result = create_node(
            "grid_fixtures__constrained_source",
            {"name": "Pippin"},
            caller_context=CallerContext(batch_id=str(mine.entity_id)),
        )
        assert result.success

        mine.refresh_from_db()
        assert mine.name == "My own batch"
        assert mine.source == "test:caller-owned"
        assert mine.entity.name == "My own batch"
        # And the write landed in it.
        assert len(get_batch_events(str(mine.entity_id))) >= 1


@pytest.mark.django_db
class TestBatchNameClamp:
    """req-grid-service-batch-metadata-8: a name too long for the column is
    clamped at the one place that writes both ends, not rejected.

    Every production caller composes a batch name from data it does not own, and
    the table-panel editor composes from raw user form input. A batch is
    routinely opened INSIDE the caller's transaction, so an overlong name that
    raised would not merely lose a label — it would roll the caller's work back.
    """

    def test_an_overlong_authored_name_succeeds_and_is_clamped(self):
        batch = create_batch(name="x" * 300, source="test:clamp")

        assert len(batch.name) == 255
        assert batch.name == "x" * 255

    def test_both_ends_of_the_spine_get_the_same_clamped_value(self):
        """The Batch and its Entity projection must not disagree — the original defect."""
        batch = create_batch(name="y" * 300, source="test:clamp")

        assert batch.entity.name == batch.name
        batch.refresh_from_db()
        assert batch.entity.name == batch.name

    def test_a_name_that_fits_is_untouched(self):
        batch = create_batch(name="a readable name", source="test:clamp")

        assert batch.name == "a readable name"
        assert batch.entity.name == "a readable name"

    def test_the_clamp_is_recorded_not_silent(self, caplog):
        """A truncation a consumer cannot see is a lie the data cannot report."""
        import logging

        with caplog.at_level(logging.INFO, logger="tap_grid.batch"):
            create_batch(name="z" * 300, source="test:clamp")

        assert any("truncated" in r.message or "truncated" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
class TestCallerNamedServiceBatches:
    """req-grid-service-batch-caller-name: an ad-hoc service-layer write can say
    what the change was, instead of only being named after its operations.

    Mandatory for a minting write since req-grid-service-batch-label-required; see
    TestMintedBatchLabelRequired.
    """

    @pytest.mark.spec("req-grid-service-batch-caller-name-1")
    def test_write_batch_names_the_batch_it_mints(self):
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import write_batch

        result = write_batch(
            [WriteOperation(verb="create_node", type_slug="grid_fixtures__constrained_source", payload={"name": "A"})],
            batch_name="highbar design: add the shared account",
            batch_description="Gruntwork's default Shared account and its cross-account key.",
        )
        assert result.success

        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.name == "highbar design: add the shared account"
        assert batch.description == "Gruntwork's default Shared account and its cross-account key."
        # Both ends of the spine carry the caller's name, not the derived one.
        batch.refresh_from_db()
        assert batch.entity.name == batch.name

    @pytest.mark.spec("req-grid-service-batch-caller-name-2")
    def test_create_node_passes_the_name_through(self):
        from tap_grid.services import create_node

        result = create_node(
            "grid_fixtures__constrained_source",
            {"name": "Frodo"},
            batch_name="named by create_node",
            batch_description="through the single-op verb",
        )
        assert result.success
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.name == "named by create_node"
        assert batch.description == "through the single-op verb"

    @pytest.mark.spec("req-grid-service-batch-caller-name-2")
    def test_delete_node_passes_the_name_through(self):
        """The delete runs in a batch of its own: the test harness binds one ambient
        batch per test, which the create mints first, and a write joining an existing
        batch keeps that batch's name (-4)."""
        import uuid

        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node, delete_node

        created = create_node("grid_fixtures__constrained_source", {"name": "Boromir"})
        assert created.success

        assert created.entity_id is not None
        result = delete_node(
            created.entity_id,
            caller_context=CallerContext(batch_id=str(uuid.uuid7())),
            batch_name="retire a stale design node",
        )
        assert result.success
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.name == "retire a stale design node"

    @pytest.mark.spec("req-grid-service-batch-caller-name-2")
    @pytest.mark.parametrize(
        ("verb", "args"),
        [
            ("create_node", ("grid_fixtures__constrained_source", {"name": "x"})),
            ("patch_node", ("00000000-0000-0000-0000-000000000000", {"name": "x"})),
            ("replace_node", ("00000000-0000-0000-0000-000000000000", {"name": "x"})),
            ("delete_node", ("00000000-0000-0000-0000-000000000000",)),
            ("patch_edge", ("00000000-0000-0000-0000-000000000000", {})),
            ("replace_edge", ("00000000-0000-0000-0000-000000000000", {})),
            ("delete_edge_by_entity", ("00000000-0000-0000-0000-000000000000",)),
        ],
    )
    def test_every_single_operation_verb_forwards_both_arguments(self, monkeypatch, verb, args):
        """The forward is checked at the seam, so a verb that drops either argument fails."""
        import tap_grid.services as services
        from tap_grid.service_types import BatchWriteResult

        seen: dict[str, object] = {}

        def fake_write_batch(operations, **kwargs):
            seen.update(kwargs)
            return BatchWriteResult(success=False, batch_id="x", dry_run=False, results=[], errors=[])

        monkeypatch.setattr(services, "write_batch", fake_write_batch)
        getattr(services, verb)(*args, batch_name="the name", batch_description="the description")

        assert seen.get("batch_name") == "the name"
        assert seen.get("batch_description") == "the description"

    @pytest.mark.spec("req-grid-service-batch-caller-name-2")
    def test_create_edge_names_the_batch_not_the_edge(self):
        """`create_edge` already takes `name` for the edge; `batch_name` is the batch's."""
        producer = create_entity("concept", name="producer")
        target = create_batch(source="t:target")

        edge = create_edge(
            from_entity=producer,
            to_entity=target.entity,
            edge_type="PRODUCED_BATCH",
            properties={"disposition": "imported"},
            name="the edge",
            batch_name="the batch",
        )

        assert edge.entity.name == "the edge"
        names = [b.name for b in get_entity_batches(edge.entity.id)]
        assert "the batch" in names

    @pytest.mark.spec("req-grid-service-batch-caller-name-1")
    def test_a_named_batch_is_still_attributed_to_the_service_layer(self):
        from tap_grid.batch import AUTO_BATCH_SOURCE
        from tap_grid.services import create_node

        result = create_node("grid_fixtures__constrained_source", {"name": "Merry"}, batch_name="named")
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.source == AUTO_BATCH_SOURCE

    @pytest.mark.spec("req-grid-service-batch-caller-name-4")
    def test_joining_an_existing_batch_with_its_own_name_is_accepted(self):
        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node

        mine = create_batch(name="My own batch", source="test:caller-owned")
        result = create_node(
            "grid_fixtures__constrained_source",
            {"name": "Pippin"},
            caller_context=CallerContext(batch_id=str(mine.entity_id)),
            batch_name="My own batch",
        )
        assert result.success
        mine.refresh_from_db()
        assert mine.name == "My own batch"

    @pytest.mark.spec("req-grid-service-batch-caller-name-4")
    @pytest.mark.parametrize("field", ["batch_name", "batch_description"])
    def test_renaming_an_existing_batch_is_refused_before_any_write(self, field):
        from tap_grid.caller_context import CallerContext
        from tap_grid.models import Entity
        from tap_grid.services import create_node

        mine = create_batch(name="My own batch", description="mine", source="test:caller-owned")
        before = Entity.objects.filter(entity_type="grid_fixtures__constrained_source").count()

        joined = CallerContext(batch_id=str(mine.entity_id))
        with pytest.raises(ValueError, match="keeps its own") as refused:
            if field == "batch_name":
                create_node(
                    "grid_fixtures__constrained_source",
                    {"name": "Gandalf"},
                    caller_context=joined,
                    batch_name="something else",
                )
            else:
                create_node(
                    "grid_fixtures__constrained_source",
                    {"name": "Gandalf"},
                    caller_context=joined,
                    batch_description="something else",
                )

        # The refusal names only the caller's value, not the stored one.
        assert "My own batch" not in str(refused.value)
        assert "'mine'" not in str(refused.value)
        mine.refresh_from_db()
        assert mine.name == "My own batch"
        assert mine.description == "mine"
        assert Entity.objects.filter(entity_type="grid_fixtures__constrained_source").count() == before

    @pytest.mark.spec("req-grid-service-batch-caller-name-4")
    def test_an_ambient_batch_scope_is_held_to_the_same_rule(self):
        """The harness binds one ambient batch per test: the first write mints it with
        its name, and a second write naming it differently is refused, not ignored."""
        from tap_grid.services import create_node

        first = create_node("grid_fixtures__constrained_source", {"name": "Legolas"}, batch_name="A")
        assert first.success

        with pytest.raises(ValueError, match="keeps its own"):
            create_node("grid_fixtures__constrained_source", {"name": "Gimli"}, batch_name="B")

        # The same name joins it without complaint.
        again = create_node("grid_fixtures__constrained_source", {"name": "Gimli"}, batch_name="A")
        assert again.success
        assert again.batch_id == first.batch_id

    @pytest.mark.spec("req-grid-service-batch-caller-name-4")
    def test_a_batch_id_with_no_batch_row_is_minted_with_the_callers_name(self):
        import uuid

        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node

        fresh = str(uuid.uuid7())
        result = create_node(
            "grid_fixtures__constrained_source",
            {"name": "Radagast"},
            caller_context=CallerContext(batch_id=fresh),
            batch_name="pre-generated id, caller's name",
        )
        assert result.success
        batch = get_batch(fresh)
        assert batch is not None
        assert batch.name == "pre-generated id, caller's name"

    @pytest.mark.spec("req-grid-service-batch-caller-name-5")
    def test_an_overlong_caller_name_is_clamped_not_refused(self):
        from tap_grid.services import create_node

        result = create_node("grid_fixtures__constrained_source", {"name": "Treebeard"}, batch_name="n" * 300)
        assert result.success
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert batch.name == "n" * 255
        assert batch.entity.name == batch.name


@pytest.mark.django_db
@pytest.mark.no_default_batch_label
class TestMintedBatchLabelRequired:
    """req-grid-service-batch-label-required: a write that mints its batch must say
    what the change is; a write that joins an existing batch need not.

    These tests run without the harness's default batch label, so the context they
    write under is unlabelled unless a test binds one.
    """

    @staticmethod
    def _op(name: str = "A"):
        from tap_grid.service_types import WriteOperation

        return WriteOperation(verb="create_node", type_slug="grid_fixtures__constrained_source", payload={"name": name})

    @staticmethod
    def _codes(result) -> list[str]:
        return [e.code for e in result.errors]

    @pytest.mark.spec("req-grid-service-batch-label-required-1")
    @pytest.mark.parametrize(
        "name, description",
        [(None, None), ("a name", None), (None, "a description"), ("", ""), ("   ", "a description"), ("a name", "  ")],
    )
    def test_an_unlabelled_minting_write_is_refused_and_writes_nothing(self, name, description):
        from tap_grid.models import Batch, Entity
        from tap_grid.services import write_batch

        batches, nodes = Batch.objects.count(), Entity.objects.count()
        result = write_batch([self._op()], batch_name=name, batch_description=description)

        assert not result.success
        assert self._codes(result) == ["batch_label_required"]
        assert Batch.objects.count() == batches
        assert Entity.objects.count() == nodes

    @pytest.mark.spec("req-grid-service-batch-label-required-1")
    def test_the_refusal_names_what_is_missing(self):
        from tap_grid.services import write_batch

        result = write_batch([self._op()], batch_name="named only")
        assert "missing batch_description (" in result.errors[0].message

    @pytest.mark.spec("req-grid-service-batch-label-required-1")
    def test_a_labelled_minting_write_succeeds(self):
        from tap_grid.services import write_batch

        result = write_batch([self._op()], batch_name="Seed A", batch_description="Why A exists")
        assert result.success
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert (batch.name, batch.description) == ("Seed A", "Why A exists")

    @pytest.mark.spec("req-grid-service-batch-label-required-1")
    def test_a_dry_run_is_held_to_the_rule_too(self):
        from tap_grid.services import write_batch

        result = write_batch([self._op()], dry_run=True)
        assert self._codes(result) == ["batch_label_required"]

    @pytest.mark.spec("req-grid-service-batch-label-required-2")
    def test_joining_an_existing_batch_needs_no_label(self):
        from tap_grid.caller_context import CallerContext
        from tap_grid.services import write_batch

        opened = create_batch(name="Opened elsewhere", description="by a collector", source="test:opener")
        result = write_batch([self._op()], caller_context=CallerContext(batch_id=str(opened.entity_id)))

        assert result.success
        opened.refresh_from_db()
        assert opened.name == "Opened elsewhere"

    @pytest.mark.spec("req-grid-service-batch-label-required-2")
    def test_an_ambient_existing_batch_is_joined_without_a_label(self):
        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.services import write_batch

        opened = create_batch(name="Ambient scope", description="bound upstream", source="test:opener")
        prior = get_caller_context()
        set_caller_context(CallerContext(user=prior.user if prior else None, batch_id=str(opened.entity_id)))
        try:
            result = write_batch([self._op()])
        finally:
            set_caller_context(prior)
        assert result.success
        assert result.batch_id == str(opened.entity_id)

    @pytest.mark.spec("req-grid-service-batch-label-required-2")
    def test_a_fresh_batch_id_with_no_row_is_minting_and_refused(self):
        import uuid

        from tap_grid.caller_context import CallerContext
        from tap_grid.models import Batch
        from tap_grid.services import write_batch

        fresh = str(uuid.uuid7())
        result = write_batch([self._op()], caller_context=CallerContext(batch_id=fresh))

        assert self._codes(result) == ["batch_label_required"]
        assert not Batch.objects.filter(entity_id=fresh).exists()

    @pytest.mark.spec("req-grid-service-batch-label-required-3")
    @pytest.mark.parametrize("verb", ["create_node", "delete_node"])
    def test_single_operation_verbs_return_the_refusal(self, verb):
        import uuid

        from tap_grid import services
        from tap_grid.caller_context import CallerContext, get_caller_context

        bound = get_caller_context()
        assert bound is not None
        user = bound.user
        if verb == "create_node":
            result = services.create_node("grid_fixtures__constrained_source", {"name": "Boromir"})
        else:
            # Seed in a batch of its own, so the delete below mints a fresh one.
            made = services.create_node(
                "grid_fixtures__constrained_source",
                {"name": "Faramir"},
                caller_context=CallerContext(user=user, batch_id=str(uuid.uuid7())),
                batch_name="seed",
                batch_description="seed",
            )
            assert made.success
            assert made.entity_id is not None
            result = services.delete_node(
                made.entity_id, reason="operator", caller_context=CallerContext(user=user, batch_id=str(uuid.uuid7()))
            )

        assert not result.success
        assert [e.code for e in result.errors] == ["batch_label_required"]

    @pytest.mark.spec("req-grid-service-batch-label-required-3")
    def test_create_edge_raises_the_refusal(self):
        from tap_grid.exceptions import EdgePropertyValidationError
        from tap_grid.services import create_edge

        producer = create_entity("concept", name="producer")
        target = create_batch(source="t:target")
        with pytest.raises(EdgePropertyValidationError, match="batch_description"):
            create_edge(
                from_entity=producer,
                to_entity=target.entity,
                edge_type="PRODUCED_BATCH",
                properties={"disposition": "imported"},
            )

    @pytest.mark.spec("req-grid-service-batch-label-required-4")
    def test_a_context_label_names_the_minted_batch(self):
        from tap_grid.caller_context import CallerContext, get_caller_context
        from tap_grid.services import write_batch

        prior = get_caller_context()
        ctx = CallerContext(
            user=prior.user if prior else None, batch_name="From the context", batch_description="context why"
        )
        result = write_batch([self._op()], caller_context=ctx)

        assert result.success
        batch = get_batch(result.batch_id)
        assert batch is not None
        assert (batch.name, batch.description) == ("From the context", "context why")

    @pytest.mark.spec("req-grid-service-batch-label-required-4")
    def test_the_calls_own_label_wins_over_the_contexts(self):
        from tap_grid.caller_context import CallerContext, get_caller_context
        from tap_grid.services import write_batch

        prior = get_caller_context()
        ctx = CallerContext(user=prior.user if prior else None, batch_name="context", batch_description="context")
        result = write_batch([self._op()], caller_context=ctx, batch_name="call", batch_description="call why")

        batch = get_batch(result.batch_id)
        assert batch is not None
        assert (batch.name, batch.description) == ("call", "call why")

    @pytest.mark.spec("req-grid-service-batch-label-required-4")
    def test_an_explicit_context_inherits_the_ambient_label(self):
        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.services import write_batch

        prior = get_caller_context()
        user = prior.user if prior else None
        set_caller_context(CallerContext(user=user, batch_name="ambient", batch_description="ambient why"))
        try:
            result = write_batch([self._op()], caller_context=CallerContext(user=user))
        finally:
            set_caller_context(prior)

        batch = get_batch(result.batch_id)
        assert batch is not None
        assert (batch.name, batch.description) == ("ambient", "ambient why")
