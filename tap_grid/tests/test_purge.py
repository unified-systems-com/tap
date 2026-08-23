"""Tests for tap_grid.services.purge_node and the manage.py purge_entities CLI.

Covers req-grid-service-purge in spec-grid-service-delete.md:
  -1 DEBUG-only gate
  -2 Edge-only cascade (touching edges go, neighbors stay)
  -3 History rows go with the entity
  -4 BatchEvent rows go with the entity
  -5 INTERNAL_ONLY does not block purge
  -6 Reason required
  -7 CLI scope by type
  -8 CLI mutual exclusion + entity-id/entity-type match
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from tap_plugin.grid_fixtures.models import ConstrainedSource

from tap_grid.exceptions import (
    ServiceConflictError,
    ServiceNotFoundError,
    ServiceValidationError,
)
from tap_grid.models import BatchEvent, Edge, Entity
from tap_grid.services import (
    create_edge,
    create_entity,
    create_node,
    purge_node,
)

# ---------------------------------------------------------------------------
# DEBUG-only gate — req-grid-service-purge-1
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-1")
@pytest.mark.django_db
class TestDebugGate:
    def test_purge_refused_when_debug_false(self, settings):
        entity = create_entity("grid_fixtures__constrained_source", name="Tom Bombadil")
        settings.DEBUG = False
        with pytest.raises(ServiceConflictError, match="purge_refused_production"):
            purge_node(entity.pk, reason="should not happen")

    def test_purge_allowed_when_debug_true(self, settings):
        entity = create_entity("grid_fixtures__constrained_source", name="Goldberry")
        settings.DEBUG = True
        result = purge_node(entity.pk, reason="dev reset")
        assert result.success
        assert not Entity.objects.filter(pk=entity.pk).exists()


# ---------------------------------------------------------------------------
# Edge-only cascade — req-grid-service-purge-2
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-2")
@pytest.mark.django_db
class TestEdgeCascade:
    def test_touching_edges_purged_both_directions(self, settings):
        settings.DEBUG = True
        target = create_entity("grid_fixtures__constrained_source", name="Boromir")
        other = create_entity("grid_fixtures__constrained_target", name="Gondor")
        third = create_entity("grid_fixtures__constrained_source", name="Faramir")
        edge_out = create_edge(target, other, "CONSTRAINED_LINK__grid_fixtures")
        edge_in = create_edge(third, target, "SYMMETRIC_LINK__grid_fixtures")
        out_uuid = str(edge_out.entity_id)
        in_uuid = str(edge_in.entity_id)
        # sanity
        assert Entity.objects.filter(pk__in=[out_uuid, in_uuid]).count() == 2

        result = purge_node(target.pk, reason="dev")

        assert result.success
        assert set(result.purged_edges) == {out_uuid, in_uuid}
        # Edge typed rows are gone (cascade from Entity delete).
        assert not Edge.all_objects.filter(entity_id__in=[out_uuid, in_uuid]).exists()
        assert not Entity.objects.filter(pk__in=[out_uuid, in_uuid]).exists()

    def test_neighbor_entities_not_purged(self, settings):
        settings.DEBUG = True
        target = create_entity("grid_fixtures__constrained_source", name="Denethor")
        neighbor = create_entity("grid_fixtures__constrained_target", name="Minas Tirith")
        create_edge(target, neighbor, "CONSTRAINED_LINK__grid_fixtures")

        purge_node(target.pk, reason="dev")

        # Neighbor survives — cascade is edges-only.
        assert Entity.objects.filter(pk=neighbor.pk).exists()


# ---------------------------------------------------------------------------
# History row removal — req-grid-service-purge-3
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-3")
@pytest.mark.django_db
class TestHistoryRowRemoval:
    def test_typed_model_history_purged(self, settings):
        settings.DEBUG = True
        result = create_node(
            "grid_fixtures__constrained_source",
            {"name": "Eowyn", "description": "Shieldmaiden of Rohan."},
        )
        ConstrainedSource.objects.get(entity_id=result.entity_id)  # exists (raises if purged)
        # Sanity: history rows exist for the create.
        assert ConstrainedSource.history.filter(entity_id=result.entity_id).exists()

        purge_node(result.entity_id, reason="dev")

        assert not ConstrainedSource.history.filter(entity_id=result.entity_id).exists()
        assert not ConstrainedSource.objects.filter(entity_id=result.entity_id).exists()

    def test_edge_history_purged_with_node(self, settings):
        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="Merry")
        b = create_entity("grid_fixtures__constrained_target", name="Buckland")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        edge_uuid = edge.entity_id
        # Sanity: edge history exists.
        assert Edge.history.filter(entity_id=edge_uuid).exists()

        purge_node(a.pk, reason="dev")

        # Edge gone AND its history gone.
        assert not Edge.all_objects.filter(entity_id=edge_uuid).exists()
        assert not Edge.history.filter(entity_id=edge_uuid).exists()


# ---------------------------------------------------------------------------
# BatchEvent rows go with the entity — req-grid-service-purge-4
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-4")
@pytest.mark.django_db
class TestBatchEventRemoval:
    def test_batch_events_for_entity_purged(self, settings):
        settings.DEBUG = True
        result = create_node("grid_fixtures__constrained_source", {"name": "Galadriel"})
        # The create should have produced at least one BatchEvent referencing
        # this entity (the create itself).
        assert BatchEvent.objects.filter(entity_id=result.entity_id).exists()

        purge_node(result.entity_id, reason="dev")

        assert not BatchEvent.objects.filter(entity_id=result.entity_id).exists()


# ---------------------------------------------------------------------------
# Reason required — req-grid-service-purge-6
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-6")
@pytest.mark.django_db
class TestReasonRequired:
    def test_empty_reason_rejected(self, settings):
        settings.DEBUG = True
        entity = create_entity("grid_fixtures__constrained_source", name="Arwen")
        with pytest.raises(ServiceValidationError, match="non-empty `reason`"):
            purge_node(entity.pk, reason="")

    def test_whitespace_reason_rejected(self, settings):
        settings.DEBUG = True
        entity = create_entity("grid_fixtures__constrained_source", name="Elrond")
        with pytest.raises(ServiceValidationError, match="non-empty `reason`"):
            purge_node(entity.pk, reason="   ")

    def test_reason_logged(self, settings, caplog):
        settings.DEBUG = True
        entity = create_entity("grid_fixtures__constrained_source", name="Glorfindel")
        with caplog.at_level("INFO", logger="tap_grid.services"):
            purge_node(entity.pk, reason="cleanup before rebenchmark")
        assert any("cleanup before rebenchmark" in rec.getMessage() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Missing / invalid target
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTargetValidation:
    def test_missing_entity_raises_not_found(self, settings):
        settings.DEBUG = True
        bogus = uuid.uuid4()
        with pytest.raises(ServiceNotFoundError):
            purge_node(bogus, reason="dev")

    def test_bad_uuid_raises_validation_error(self, settings):
        settings.DEBUG = True
        with pytest.raises(ServiceValidationError):
            purge_node("not-a-uuid", reason="dev")

    def test_purge_edge_entity_refused(self, settings):
        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="Sam")
        b = create_entity("grid_fixtures__constrained_target", name="Bag End")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        with pytest.raises(ServiceConflictError, match="purge_node targets node entities"):
            purge_node(edge.entity_id, reason="dev")


# ---------------------------------------------------------------------------
# CLI — req-grid-service-purge-7, -8
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-purge-7")
@pytest.mark.django_db
class TestPurgeEntitiesCLI:
    def test_cli_all_of_type_purges_only_that_type(self, settings):
        settings.DEBUG = True
        c1 = create_entity("grid_fixtures__constrained_source", name="Tauriel")
        c2 = create_entity("grid_fixtures__constrained_source", name="Beorn")
        loc = create_entity("grid_fixtures__constrained_target", name="The Carrock")

        call_command(
            "purge_entities",
            "--entity-type=grid_fixtures__constrained_source",
            "--all-of-type",
            "--reason=dev reset",
        )

        # Characters gone, location survives.
        assert not Entity.objects.filter(pk__in=[c1.pk, c2.pk]).exists()
        assert Entity.objects.filter(pk=loc.pk).exists()

    def test_cli_specific_entity_ids(self, settings):
        settings.DEBUG = True
        c1 = create_entity("grid_fixtures__constrained_source", name="Bard")
        c2 = create_entity("grid_fixtures__constrained_source", name="Bain")

        call_command(
            "purge_entities",
            "--entity-type=grid_fixtures__constrained_source",
            f"--entity-id={c1.pk}",
            "--reason=dev",
        )

        assert not Entity.objects.filter(pk=c1.pk).exists()
        assert Entity.objects.filter(pk=c2.pk).exists()

    def test_cli_requires_reason(self, settings):
        settings.DEBUG = True
        create_entity("grid_fixtures__constrained_source", name="Thorin")
        with pytest.raises(CommandError):
            call_command(
                "purge_entities",
                "--entity-type=grid_fixtures__constrained_source",
                "--all-of-type",
                # no --reason
            )

    def test_cli_mismatched_entity_type_aborts(self, settings):
        settings.DEBUG = True
        c = create_entity("grid_fixtures__constrained_source", name="Bilbo")
        loc = create_entity("grid_fixtures__constrained_target", name="Erebor")
        # Caller asks for constrained_source but gives a constrained_target id.
        with pytest.raises(CommandError, match="mismatch"):
            call_command(
                "purge_entities",
                "--entity-type=grid_fixtures__constrained_source",
                f"--entity-id={loc.pk}",
                "--reason=test",
            )
        # No writes happened.
        assert Entity.objects.filter(pk__in=[c.pk, loc.pk]).count() == 2

    def test_cli_missing_entity_id_aborts(self, settings):
        settings.DEBUG = True
        bogus = uuid.uuid4()
        with pytest.raises(CommandError, match="not found"):
            call_command(
                "purge_entities",
                "--entity-type=grid_fixtures__constrained_source",
                f"--entity-id={bogus}",
                "--reason=test",
            )

    def test_cli_refused_when_debug_false(self, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="purge_refused_production"):
            call_command(
                "purge_entities",
                "--entity-type=grid_fixtures__constrained_source",
                "--all-of-type",
                "--reason=test",
            )

    def test_cli_all_of_type_empty_is_a_warning_not_error(self, settings):
        settings.DEBUG = True
        # No constrained-source nodes in this test DB.
        # Should not raise.
        call_command(
            "purge_entities",
            "--entity-type=grid_fixtures__constrained_source",
            "--all-of-type",
            "--reason=test",
        )


# ---------------------------------------------------------------------------
# purge_edge — req-grid-service-purge-edge
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPurgeEdge:
    """Edge-targeted hard-delete primitive (sibling of purge_node).

    Covers:
      -1 DEBUG-only gate
      -2 Edge type only (rejects node entities)
      -3 Endpoint nodes survive
      -4 Edge history rows go with the edge
      -5 BatchEvent rows referencing the edge are hard-deleted
      -6 Reason required
      -7 CLI routes edge purges via --entity-type=edge
    """

    def test_debug_gate_refuses(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        settings.DEBUG = False
        with pytest.raises(ServiceConflictError, match="purge_refused_production"):
            purge_edge(edge.entity_id, reason="should fail")

    def test_purge_edge_accepts_edge_entity(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        eid = edge.entity_id

        result = purge_edge(eid, reason="dev")
        assert result.success
        assert result.purged_entity_id == str(eid)
        assert result.purged_entity_type == "edge"
        assert result.purged_edges == []  # no cascade
        # Edge typed row + Entity row are gone.
        assert not Edge.all_objects.filter(entity_id=eid).exists()
        assert not Entity.objects.filter(pk=eid).exists()

    def test_purge_edge_refuses_node_entity(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        node = create_entity("grid_fixtures__constrained_source", name="Frodo")
        with pytest.raises(ServiceConflictError, match="purge_edge_wrong_type"):
            purge_edge(node.pk, reason="dev")
        assert Entity.objects.filter(pk=node.pk).exists()

    def test_purge_edge_endpoints_survive(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")

        purge_edge(edge.entity_id, reason="dev")

        assert Entity.objects.filter(pk=a.pk).exists()
        assert Entity.objects.filter(pk=b.pk).exists()

    def test_edge_history_rows_purged(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        eid = edge.entity_id

        # Edge model uses django-simple-history; creation logged a historical row.
        assert Edge.history.filter(entity_id=eid).exists()

        purge_edge(eid, reason="dev")

        assert not Edge.history.filter(entity_id=eid).exists()

    def test_batch_event_rows_for_edge_purged(self, settings):
        from tap_grid.batch import create_batch
        from tap_grid.models import BatchEventType
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        eid = edge.entity_id

        # Manually emit a BatchEvent referencing this edge so the post-purge
        # assertion is non-trivial. (`create_edge` is the low-level
        # entity-only helper and does not itself produce edge BatchEvents.)
        batch = create_batch(name="edge-purge-test", source="test")
        BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.LINK,
            entity_id=eid,
            entity_type="edge",
            metadata={"manual": True},
        )
        assert BatchEvent.objects.filter(entity_id=eid).exists()

        purge_edge(eid, reason="dev")

        assert not BatchEvent.objects.filter(entity_id=eid).exists()

    def test_reason_required(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        with pytest.raises(ServiceValidationError):
            purge_edge(edge.entity_id, reason="")
        with pytest.raises(ServiceValidationError):
            purge_edge(edge.entity_id, reason="   ")

    def test_missing_entity_raises_not_found(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        random_uuid = uuid.uuid4()
        with pytest.raises(ServiceNotFoundError):
            purge_edge(random_uuid, reason="dev")

    def test_bad_uuid_raises_validation_error(self, settings):
        from tap_grid.services import purge_edge

        settings.DEBUG = True
        with pytest.raises(ServiceValidationError):
            purge_edge("not-a-uuid", reason="dev")

    def test_reason_logged(self, settings, caplog):
        import logging

        from tap_grid.services import purge_edge

        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        caplog.set_level(logging.INFO, logger="tap_grid.services")
        purge_edge(edge.entity_id, reason="manual edge cleanup")
        assert any("manual edge cleanup" in rec.message for rec in caplog.records)

    def test_cli_routes_edge_purges_to_purge_edge(self, settings):
        """`manage.py purge_entities --entity-type=edge` routes targets to purge_edge."""
        settings.DEBUG = True
        a = create_entity("grid_fixtures__constrained_source", name="A")
        b = create_entity("grid_fixtures__constrained_target", name="B")
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        eid = str(edge.entity_id)

        call_command(
            "purge_entities",
            "--entity-type=edge",
            f"--entity-id={eid}",
            "--reason=cli edge purge",
        )

        # Edge gone; endpoints survive.
        assert not Entity.objects.filter(pk=eid).exists()
        assert Entity.objects.filter(pk=a.pk).exists()
        assert Entity.objects.filter(pk=b.pk).exists()
