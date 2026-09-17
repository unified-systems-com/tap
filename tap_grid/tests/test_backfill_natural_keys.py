"""The natural-key backfill (``req-grid-entity-natural-key-6``, ``-8``).

Setup uses the service layer for creating nodes (the normal path) and reads Entity
directly for assertions, because what is under test is below-service-layer
infrastructure: the command deliberately writes with ``bulk_update`` so a backfill
does not masquerade as a mutation of the object.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tap_grid.models import Entity
from tap_grid.natural_key import natural_key
from tap_grid.services import create_node

pytestmark = pytest.mark.django_db


def _panel(slug: str, name: str = "A panel") -> Entity:
    """A panel, created through the service layer.

    `panel` rather than `page` because a page's layout must carry a non-empty
    `columns` whose `panel-id` slots hotlink to real panels — real validation, but
    scaffolding this test does not need. Both are keyed on `slug` identically.

    The assertion matters: without it a validation failure surfaces later as a
    confusing Entity.DoesNotExist instead of naming the actual problem.
    """
    result = create_node("panel", {"slug": slug, "name": name, "view": "tap_web/panels/table.html"})
    assert result.success, f"panel setup failed: {result.errors}"
    assert result.entity_id is not None, "a successful create must carry an entity_id"
    return Entity.objects.get(pk=result.entity_id)


class TestReportIsReadOnly:
    def test_report_writes_nothing(self) -> None:
        entity = _panel("alpha")
        assert entity.natural_key is None
        call_command("backfill_natural_keys", "--type", "panel")
        entity.refresh_from_db()
        assert entity.natural_key is None, "report mode must not write"


class TestApply:
    def test_apply_writes_the_derived_key(self) -> None:
        entity = _panel("beta")
        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        entity.refresh_from_db()
        assert entity.natural_key == natural_key("panel", {"slug": "beta"})

    def test_apply_does_not_look_like_a_mutation(self) -> None:
        """The load-bearing claim of the command's design.

        A backfill computes something TAP already knew; the source object did not
        change. So it must not bump Entity.version (req-grid-history-version-2
        increments on canonical mutations) and must not move updated_at.
        """
        entity = _panel("gamma")
        version_before, updated_before = entity.version, entity.updated_at

        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        entity.refresh_from_db()

        assert entity.natural_key is not None, "sanity: the key was actually written"
        assert entity.version == version_before, "a backfill must not bump the version"
        assert entity.updated_at == updated_before, "a backfill must not move updated_at"

    def test_apply_is_idempotent(self) -> None:
        entity = _panel("delta")
        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        entity.refresh_from_db()
        first = entity.natural_key
        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        entity.refresh_from_db()
        assert entity.natural_key == first


class TestCheckDetectsDrift:
    def test_check_is_clean_after_apply(self) -> None:
        _panel("epsilon")
        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        call_command("backfill_natural_keys", "--check", "--type", "panel")  # must not raise

    def test_check_catches_a_stored_key_that_no_longer_derives(self) -> None:
        """The recipe-edited-without-a-migration detector. Simulated by corrupting the
        stored key, which is indistinguishable from a recipe having moved under it."""
        entity = _panel("zeta")
        call_command("backfill_natural_keys", "--apply", "--type", "panel")
        Entity.objects.filter(pk=entity.pk).update(natural_key=natural_key("panel", {"slug": "WRONG"}))

        with pytest.raises(CommandError, match="disagree with a recompute"):
            call_command("backfill_natural_keys", "--check", "--type", "panel")

    def test_check_writes_nothing_even_when_it_finds_drift(self) -> None:
        entity = _panel("eta")
        wrong = natural_key("panel", {"slug": "WRONG"})
        Entity.objects.filter(pk=entity.pk).update(natural_key=wrong)
        with pytest.raises(CommandError):
            call_command("backfill_natural_keys", "--check", "--type", "panel")
        entity.refresh_from_db()
        assert entity.natural_key == wrong, "check must not repair what it reports"


class TestCollisions:
    def test_same_key_same_dimensions_fails_loudly(self) -> None:
        """req-grid-entity-natural-key-6: record both, never choose. A thin key
        document and a carried duplicate have opposite remedies."""
        a = _panel("theta")
        b = _panel("theta-other")
        # Force the collision by making b's slug equal a's, which is what a too-thin
        # key document would produce naturally.
        from tap_web.models import Panel

        Panel.objects.filter(entity_id=b.pk).update(slug="theta")  # type: ignore[misc]  # django-stubs sees BaseModel's manager
        Entity.objects.filter(pk__in=[a.pk, b.pk]).update(dimensions={})

        with pytest.raises(CommandError, match="collision"):
            call_command("backfill_natural_keys", "--type", "panel")

    def test_same_key_different_dimensions_is_permitted(self) -> None:
        """req-grid-entity-natural-key-3: the correlation property. Reported, not fatal."""
        a = _panel("iota")
        b = _panel("iota-other")
        from tap_web.models import Panel

        Panel.objects.filter(entity_id=b.pk).update(slug="iota")  # type: ignore[misc]  # django-stubs sees BaseModel's manager
        Entity.objects.filter(pk=a.pk).update(dimensions={"tap.perspective": "one"})
        Entity.objects.filter(pk=b.pk).update(dimensions={"tap.perspective": "two"})

        call_command("backfill_natural_keys", "--type", "panel")  # must not raise


class TestEmptyScanIsNotAFalseGreen:
    def test_unknown_type_refuses_rather_than_reporting_zero(self) -> None:
        with pytest.raises(CommandError, match="No keyed entity types"):
            call_command("backfill_natural_keys", "--type", "batch")

    def test_keyless_type_refuses(self) -> None:
        """batch is keyless by declaration; asking to backfill it is a mistake worth
        surfacing rather than a no-op worth reporting as success."""
        with pytest.raises(CommandError, match="keyless"):
            call_command("backfill_natural_keys", "--type", "batch")
