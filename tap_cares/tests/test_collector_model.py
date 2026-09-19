"""Tests for the Collector model — req-tap-cares-collector-model."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from tap_cares.models import Collector


def _kwargs(**overrides):
    base = {
        "name": "Test Collector",
        "description": "fixture",
        "collector_registry": "tap_cares.tests.fakes:dummy",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Entity spine + class constants (req-tap-cares-collector-model-1, -5, -6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollectorIsEntity:
    def test_entity_type_constant(self):
        assert Collector.ENTITY_TYPE == "collector"

    def test_default_dimensions(self):
        assert Collector.DEFAULT_DIMENSIONS == {"tap_cares": "collector"}

    def test_creates_backing_entity_on_save(self):
        c = Collector.objects.create(**_kwargs())
        assert c.entity_id is not None
        assert c.entity.entity_type == "collector"

    def test_save_applies_default_dimension(self):
        c = Collector.objects.create(**_kwargs())
        assert c.entity.dimensions == {"tap_cares": "collector"}


# ---------------------------------------------------------------------------
# CREATE_REQUIRED (req-tap-cares-collector-model-1, -8)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateRequired:
    def test_create_required_is_name_and_collector_registry(self):
        assert set(Collector.CREATE_REQUIRED) == {"name", "collector_registry"}

    def test_v0_field_set_is_minimal(self):
        # req-tap-cares-collector-model-8 — name/description/collector_registry, plus the two
        # reconcile run-configuration fields the reconcile verb reads (req-grid-reconcile-verb-2/-3,
        # Issue# 652 - tap): authority (off by default) and budget (null = the class default).
        declared = {f.name for f in Collector._meta.get_fields() if hasattr(f, "attname")}
        # entity, id, batch_id, flip_map come from BaseModel; the rest are the model's own.
        own = declared - {
            "id",
            "entity",
            "entity_id",
            "batch_id",
            "flip_map",
        }
        assert own == {"name", "description", "collector_registry", "reconcile_authority", "reconcile_budget"}


# ---------------------------------------------------------------------------
# collector_registry validation (req-tap-cares-collector-model-3, -4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollectorRegistryValidation:
    def test_valid_scope_key_passes(self):
        c = Collector(**_kwargs(collector_registry="plugins.fedramp_20x_ksi.collectors:ksi-catalog"))
        c.full_validate()  # does not raise

    def test_short_key_rejected(self):
        c = Collector(**_kwargs(collector_registry="ksi-catalog"))
        with pytest.raises(ValidationError) as exc_info:
            c.full_validate()
        assert "collector_registry" in exc_info.value.message_dict

    def test_malformed_scope_rejected(self):
        c = Collector(**_kwargs(collector_registry="bad scope:ok"))
        with pytest.raises(ValidationError) as exc_info:
            c.full_validate()
        assert "collector_registry" in exc_info.value.message_dict

    def test_malformed_key_rejected(self):
        c = Collector(**_kwargs(collector_registry="ok.scope:bad key"))
        with pytest.raises(ValidationError) as exc_info:
            c.full_validate()
        assert "collector_registry" in exc_info.value.message_dict

    def test_empty_collector_registry_rejected(self):
        c = Collector(**_kwargs(collector_registry=""))
        with pytest.raises(ValidationError) as exc_info:
            c.full_validate()
        assert "collector_registry" in exc_info.value.message_dict

    def test_validator_uses_shared_helper(self):
        # req-tap-cares-collector-registry-10 — model and registry share format rules.
        # Tokens that are valid in one are valid in the other.
        from tap_cares.exceptions import InvalidCollectorRegistryKeyError
        from tap_cares.registry import _validate_collector_token

        with pytest.raises(InvalidCollectorRegistryKeyError):
            _validate_collector_token("bad key")

        c = Collector(**_kwargs(collector_registry="ok.scope:bad key"))
        with pytest.raises(ValidationError):
            c.full_validate()


# ---------------------------------------------------------------------------
# Uniqueness (req-tap-cares-collector-model-7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCollectorRegistryUniqueness:
    def test_duplicate_collector_registry_rejected(self):
        Collector.objects.create(**_kwargs(name="first", collector_registry="my.scope:dup"))
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Collector.objects.create(**_kwargs(name="second", collector_registry="my.scope:dup"))

    def test_different_keys_coexist(self):
        Collector.objects.create(**_kwargs(name="a", collector_registry="my.scope:alpha"))
        Collector.objects.create(**_kwargs(name="b", collector_registry="my.scope:beta"))
        assert Collector.objects.count() == 2


# ---------------------------------------------------------------------------
# Display projection (req-grid-node-display via Collector)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDisplayProjection:
    def test_entity_name_synced_from_get_name(self):
        c = Collector.objects.create(**_kwargs(name="My Collector"))
        assert c.entity.name == "My Collector"

    def test_get_name_returns_name(self):
        c = Collector(**_kwargs(name="X"))
        assert c.get_name() == "X"

    def test_str_returns_name(self):
        c = Collector(**_kwargs(name="Y"))
        assert str(c) == "Y"

    def test_entity_name_resyncs_on_save(self):
        c = Collector.objects.create(**_kwargs(name="Before"))
        c.name = "After"
        c.save()
        c.entity.refresh_from_db()
        assert c.entity.name == "After"
