"""Tests for the FIELD_CRUD_SCHEMA service contract: startup invariants and synthesis.

Covers:
  - _check_service_contract: all concrete BaseModel subclasses must declare FIELD_CRUD_SCHEMA
  - _build_service_schemas: synthesizes correct SERVICE_CRUD_SCHEMA from the new ClassVars
  - Content spot-checks for Edge, Search, and ConstrainedSource
"""

from typing import Any, ClassVar

import jsonschema
import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from tap_plugin.grid_fixtures.models import ConstrainedSource

from tap_grid.models import BaseModel, Edge, Search

# ---------------------------------------------------------------------------
# Minimal abstract base for test-only concrete models (no table, no CASCADE).
# ---------------------------------------------------------------------------


class _TestBaseModel(BaseModel):
    entity = models.OneToOneField(
        "tap_grid.Entity",
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        abstract = True


# ---------------------------------------------------------------------------
# Startup invariant tests
# ---------------------------------------------------------------------------


class TestServiceContractInvariant:
    """_check_service_contract fires at class definition for concrete subclasses."""

    def test_missing_field_schema_raises(self):
        """Concrete subclass missing FIELD_CRUD_SCHEMA raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="FIELD_CRUD_SCHEMA"):

            class _NoSchema(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_no_schema_xyz"

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_field_schema_non_dict_raises(self):
        """FIELD_CRUD_SCHEMA that is not a dict raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="must be a dict"):

            class _BadSchema(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_bad_schema_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[Any] = "not a dict"  # type: ignore[assignment]

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_field_schema_entry_non_dict_raises(self):
        """FIELD_CRUD_SCHEMA entry that is not a dict raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="must be a dict"):

            class _BadEntry(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_bad_entry_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                    "name": "not a dict",  # type: ignore[dict-item]
                }

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_create_required_unknown_field_raises(self):
        """CREATE_REQUIRED referencing a field not in FIELD_CRUD_SCHEMA raises."""
        with pytest.raises(ImproperlyConfigured, match="not in FIELD_CRUD_SCHEMA"):

            class _BadRequired(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_bad_required_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                    "name": {"type": "string"},
                }
                CREATE_REQUIRED: ClassVar[list[str]] = ["name", "unknown_field"]

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_replace_required_unknown_field_raises(self):
        """REPLACE_REQUIRED referencing a field not in FIELD_CRUD_SCHEMA raises."""
        with pytest.raises(ImproperlyConfigured, match="not in FIELD_CRUD_SCHEMA"):

            class _BadReplaceRequired(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_bad_replace_req_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                    "name": {"type": "string"},
                }
                REPLACE_REQUIRED: ClassVar[list[str]] = ["name", "ghost_field"]

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_patch_extra_fields_non_dict_value_raises(self):
        """PATCH_EXTRA_FIELDS with a non-dict value raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="must be a dict"):

            class _BadPatchExtra(_TestBaseModel):
                ENTITY_TYPE: ClassVar[str] = "test_bad_patch_extra_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                    "name": {"type": "string"},
                }
                PATCH_EXTRA_FIELDS: ClassVar[dict[str, Any]] = {
                    "status": "not a dict",  # type: ignore[dict-item]
                }

                class Meta(_TestBaseModel.Meta):
                    managed = False

    def test_abstract_intermediate_without_entity_type_exempt(self):
        """Abstract class without ENTITY_TYPE in its own __dict__ is skipped."""

        class _AbstractMiddle(_TestBaseModel):
            class Meta(_TestBaseModel.Meta):
                abstract = True

        assert True  # reaching here means no ImproperlyConfigured was raised

    def test_valid_field_schema_accepted(self):
        """A concrete class with valid FIELD_CRUD_SCHEMA is accepted and SERVICE_CRUD_SCHEMA synthesized."""

        class _Valid(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_valid_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert {"create", "patch", "replace"} == set(_Valid.SERVICE_CRUD_SCHEMA.keys())


# ---------------------------------------------------------------------------
# Synthesis correctness tests
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-crud-2")
class TestServiceSchemasSynthesis:
    """_build_service_schemas produces correct SERVICE_CRUD_SCHEMA from ClassVars."""

    def test_create_required_propagated(self):
        """CREATE_REQUIRED ends up in SERVICE_CRUD_SCHEMA['create']['required']."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_create_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
                "description": {"type": "string"},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert _M.SERVICE_CRUD_SCHEMA["create"]["required"] == ["name"]
        assert "required" not in _M.SERVICE_CRUD_SCHEMA["patch"]

    @pytest.mark.spec("req-grid-service-write-schema-cleanup-3")
    def test_replace_required_defaults_to_create_required(self):
        """When REPLACE_REQUIRED is omitted, replace uses CREATE_REQUIRED."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_replace_default_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert _M.SERVICE_CRUD_SCHEMA["replace"]["required"] == ["name"]

    def test_replace_required_override(self):
        """Explicit REPLACE_REQUIRED produces different required from CREATE_REQUIRED."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_replace_override_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
                "description": {"type": "string"},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]
            REPLACE_REQUIRED: ClassVar[list[str]] = ["name", "description"]

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert _M.SERVICE_CRUD_SCHEMA["create"]["required"] == ["name"]
        assert _M.SERVICE_CRUD_SCHEMA["replace"]["required"] == ["name", "description"]

    def test_patch_extra_fields_appear_only_in_patch(self):
        """PATCH_EXTRA_FIELDS fields appear in patch but not in create or replace."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_patch_extra_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
            }
            PATCH_EXTRA_FIELDS: ClassVar[dict[str, Any]] = {
                "status": {"type": "string"},
            }

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert "status" in _M.SERVICE_CRUD_SCHEMA["patch"]["properties"]
        assert "status" not in _M.SERVICE_CRUD_SCHEMA["create"]["properties"]
        assert "status" not in _M.SERVICE_CRUD_SCHEMA["replace"]["properties"]

    def test_no_required_fields_produces_no_required_key(self):
        """A model with no CREATE_REQUIRED produces schemas without 'required'."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_no_required_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
            }

            class Meta(_TestBaseModel.Meta):
                managed = False

        assert "required" not in _M.SERVICE_CRUD_SCHEMA["create"]
        assert "required" not in _M.SERVICE_CRUD_SCHEMA["replace"]
        assert "required" not in _M.SERVICE_CRUD_SCHEMA["patch"]

    def test_additional_properties_false_in_all_verbs(self):
        """Synthesized schemas always have additionalProperties: False."""

        class _M(_TestBaseModel):
            ENTITY_TYPE: ClassVar[str] = "test_synth_addl_props_xyz"
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string"},
            }

            class Meta(_TestBaseModel.Meta):
                managed = False

        for verb in ("create", "patch", "replace"):
            assert _M.SERVICE_CRUD_SCHEMA[verb]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Concrete model spot-checks
# ---------------------------------------------------------------------------


class TestAllConcreteModelsPublishSchemas:
    """Every registered concrete model must have SERVICE_CRUD_SCHEMA with required keys."""

    def test_character_has_all_required_keys(self):
        assert {"create", "patch", "replace"} <= set(ConstrainedSource.SERVICE_CRUD_SCHEMA.keys())

    def test_edge_has_all_required_keys(self):
        assert {"create", "patch", "replace"} <= set(Edge.SERVICE_CRUD_SCHEMA.keys())

    def test_edge_replace_excludes_edge_type(self):
        """Edge.SERVICE_CRUD_SCHEMA['replace'] must not include edge_type (immutable)."""
        replace_props = Edge.SERVICE_CRUD_SCHEMA["replace"].get("properties", {})
        assert "edge_type" not in replace_props

    def test_edge_create_excludes_from_to_entity(self):
        """Edge create payload uses dedicated params; from/to entity not in properties."""
        create_props = Edge.SERVICE_CRUD_SCHEMA["create"].get("properties", {})
        assert "from_entity" not in create_props
        assert "to_entity" not in create_props

    def test_search_create_validates_good_payload(self):
        """Search.SERVICE_CRUD_SCHEMA['create'] accepts a valid payload."""
        payload = {"name": "My Search", "search_type": "orm", "root": "node"}
        jsonschema.validate(instance=payload, schema=Search.SERVICE_CRUD_SCHEMA["create"])

    def test_search_create_rejects_unknown_field(self):
        """Search.SERVICE_CRUD_SCHEMA['create'] rejects unknown fields (additionalProperties=False)."""
        payload = {
            "name": "My Search",
            "search_type": "orm",
            "root": "node",
            "bad_field": "oops",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=payload, schema=Search.SERVICE_CRUD_SCHEMA["create"])

    def test_search_create_rejects_missing_required(self):
        """Search.SERVICE_CRUD_SCHEMA['create'] rejects payload missing 'name'."""
        payload = {"search_type": "orm", "root": "node"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=payload, schema=Search.SERVICE_CRUD_SCHEMA["create"])

    def test_search_patch_has_no_required_fields(self):
        """Search.SERVICE_CRUD_SCHEMA['patch'] requires no fields."""
        assert "required" not in Search.SERVICE_CRUD_SCHEMA["patch"]

    def test_search_patch_validates_empty_payload(self):
        """Search.SERVICE_CRUD_SCHEMA['patch'] accepts an empty payload (all fields optional)."""
        jsonschema.validate(instance={}, schema=Search.SERVICE_CRUD_SCHEMA["patch"])
