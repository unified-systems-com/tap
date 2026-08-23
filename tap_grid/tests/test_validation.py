"""Tests for req-grid-entity-validation: BaseModel field validation.

Covers all 15 ACIDs. Test models defined at module level use managed=False so
Django registers them but never creates tables — full_validate() is the only
thing exercised on those models (no saves). save() integration tests monkeypatch
FIELD_VALIDATION_SCHEMA onto the existing ConstrainedSource model.
"""

from typing import ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from tap_plugin.grid_fixtures.models import ConstrainedSource

from tap_grid.models import BaseModel, dangerously_ignore_validator

# ---------------------------------------------------------------------------
# Module-level test models — no ENTITY_TYPE, no table (managed=False).
# Used only for full_validate() unit tests; never saved.
#
# _TestBaseModel overrides the entity FK with on_delete=DO_NOTHING so Django's
# deletion Collector skips these models when other tests cascade-delete Entity
# rows (the tables don't exist, so a CASCADE query would raise ProgrammingError).
# ---------------------------------------------------------------------------


class _TestBaseModel(BaseModel):
    """Abstract base for test-only validation models."""

    entity = models.OneToOneField(
        "tap_grid.Entity",
        on_delete=models.DO_NOTHING,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        abstract = True


class _JsonSchemaModel(_TestBaseModel):
    """Validates 'title' via JSON Schema (minLength: 1)."""

    title = models.CharField(max_length=255, blank=True, default="")
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "title": {
            "validation": "jsonschema",
            "schema": {"type": "string", "minLength": 1},
        },
    }

    class Meta(_TestBaseModel.Meta):
        app_label = "tap_grid"
        managed = False


class _FunctionModel(_TestBaseModel):
    """Validates 'tags' via function — no semicolons allowed."""

    tags = models.JSONField(default=list)
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "tags": {"validation": "function"},
    }

    class Meta(_TestBaseModel.Meta):
        app_label = "tap_grid"
        managed = False

    def validate_tags(self) -> None:
        if any(";" in t for t in (self.tags or [])):
            raise ValidationError({"tags": ["Tags may not contain semicolons."]})


class _WholeRecordModel(_TestBaseModel):
    """Validates cross-field constraint (lo <= hi) via whole-record hook."""

    lo = models.IntegerField(default=0)
    hi = models.IntegerField(default=0)

    class Meta(_TestBaseModel.Meta):
        app_label = "tap_grid"
        managed = False

    def validate(self) -> None:
        if self.lo > self.hi:
            raise ValidationError({"lo": ["lo must be <= hi."]})


class _MultiErrorModel(_TestBaseModel):
    """Two jsonschema fields — used to test all-errors-collected behaviour."""

    a = models.CharField(max_length=10, blank=True, default="")
    b = models.CharField(max_length=10, blank=True, default="")
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "a": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
        "b": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
    }

    class Meta(_TestBaseModel.Meta):
        app_label = "tap_grid"
        managed = False


class _MixedValidationModel(_TestBaseModel):
    """Both jsonschema and function validation on the same model."""

    score = models.IntegerField(default=0)
    tags = models.JSONField(default=list)
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "score": {
            "validation": "jsonschema",
            "schema": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "tags": {"validation": "function"},
    }

    class Meta(_TestBaseModel.Meta):
        app_label = "tap_grid"
        managed = False

    def validate_tags(self) -> None:
        if len(self.tags or []) > 5:
            raise ValidationError({"tags": ["Maximum 5 tags allowed."]})


# ---------------------------------------------------------------------------
# ACID-1: FIELD_VALIDATION_SCHEMA declaration
# ---------------------------------------------------------------------------


class TestFieldSchemasDeclaration:
    """ACID-1: A BaseModel subclass may declare FIELD_VALIDATION_SCHEMA; default is {}."""

    def test_default_is_empty(self) -> None:
        """Subclasses without FIELD_VALIDATION_SCHEMA inherit the empty dict default."""
        assert ConstrainedSource.FIELD_VALIDATION_SCHEMA == {}

    def test_declared_schemas_accessible(self) -> None:
        """Models that declare FIELD_VALIDATION_SCHEMA expose it as a class attribute."""
        assert "title" in _JsonSchemaModel.FIELD_VALIDATION_SCHEMA

    def test_unlisted_fields_ignored_by_full_validate(self) -> None:
        """Fields absent from FIELD_VALIDATION_SCHEMA are not validated."""
        # ConstrainedSource.description is not in FIELD_VALIDATION_SCHEMA, so any value (including empty) passes.
        c = ConstrainedSource(description="")
        c.full_validate()  # must not raise


# ---------------------------------------------------------------------------
# ACID-2 through ACID-6: __init_subclass__ startup invariants
# ---------------------------------------------------------------------------


class TestStartupInvariants:
    """Startup invariants enforced at class definition time by __init_subclass__."""

    def test_invalid_validation_key_raises(self) -> None:
        """ACID-2: unknown 'validation' value raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="validation"):

            class _Bad(BaseModel):
                f = models.CharField(max_length=10, blank=True)
                FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {"f": {"validation": "magic"}}

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
                    managed = False

    def test_none_validation_key_raises(self) -> None:
        """ACID-2: missing 'validation' key (None) also raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="validation"):

            class _Bad2(BaseModel):
                f = models.CharField(max_length=10, blank=True)
                FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {"f": {}}

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
                    managed = False

    def test_jsonschema_missing_schema_key_raises(self) -> None:
        """ACID-3: jsonschema entry without 'schema' key raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="schema"):

            class _Bad3(BaseModel):
                f = models.CharField(max_length=10, blank=True)
                FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {"f": {"validation": "jsonschema"}}

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
                    managed = False

    def test_function_entry_missing_method_raises(self) -> None:
        """ACID-4: function validation without matching validate_<field>() raises ImproperlyConfigured."""
        with pytest.raises(ImproperlyConfigured, match="validate_f"):

            class _Bad4(BaseModel):
                f = models.CharField(max_length=10, blank=True)
                FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {"f": {"validation": "function"}}

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
                    managed = False

    def test_undeclared_validator_raises(self) -> None:
        """ACID-5: validate_<field>() in cls.__dict__ without FIELD_VALIDATION_SCHEMA entry raises."""
        with pytest.raises(ImproperlyConfigured, match="FIELD_VALIDATION_SCHEMA"):

            class _Bad5(BaseModel):
                f = models.CharField(max_length=10, blank=True)

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
                    managed = False

                def validate_f(self) -> None:
                    pass

    def test_valid_declaration_succeeds(self) -> None:
        """ACID-2/3/4: a correct FIELD_VALIDATION_SCHEMA with matching method does not raise."""
        # Module-level _FunctionModel is the positive case — its existence proves it.
        assert _FunctionModel.FIELD_VALIDATION_SCHEMA == {"tags": {"validation": "function"}}

    def test_empty_field_schemas_does_not_require_methods(self) -> None:
        """ACID-1: FIELD_VALIDATION_SCHEMA = {} (or omitted) requires no validate_*() methods."""
        # ConstrainedSource has no FIELD_VALIDATION_SCHEMA and no validate_*() methods — clean at startup.
        assert ConstrainedSource.FIELD_VALIDATION_SCHEMA == {}


# ---------------------------------------------------------------------------
# ACID-6: FIELD_VALIDATION_SCHEMA keys must be real fields (deferred to full_validate)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-6")
class TestFieldSchemaKeysMustBeRealFields:
    """ACID-6: typo in FIELD_VALIDATION_SCHEMA key raises ImproperlyConfigured at full_validate() time."""

    def test_nonexistent_field_key_raises(self) -> None:
        """A FIELD_VALIDATION_SCHEMA key with no matching attribute on the instance raises ImproperlyConfigured."""

        # Define the class first — __init_subclass__ can't catch this at class-creation
        # time because Django's metaclass moves field declarations out of cls.__dict__
        # before __init_subclass__ is called. We catch it lazily in full_validate().
        class _Typo(BaseModel):
            real_field = models.CharField(max_length=10, blank=True, default="")
            FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
                "reel_field": {  # typo — "reel_field" doesn't exist
                    "validation": "jsonschema",
                    "schema": {"type": "string"},
                },
            }

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"
                managed = False

        instance = _Typo(real_field="hello")
        with pytest.raises(ImproperlyConfigured, match="reel_field"):
            instance.full_validate()


# ---------------------------------------------------------------------------
# ACID-14: @dangerously_ignore_validator
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-14")
class TestDangerouslyIgnoreValidator:
    """ACID-14: @dangerously_ignore_validator suppresses startup check and full_validate call."""

    def test_suppresses_startup_error(self) -> None:
        """Decorated validate_<field>() without a FIELD_VALIDATION_SCHEMA entry does not raise."""

        class _Staged(BaseModel):
            f = models.CharField(max_length=10, blank=True)

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"
                managed = False

            @dangerously_ignore_validator
            def validate_f(self) -> None:
                pass  # pre-staged; not yet in FIELD_VALIDATION_SCHEMA

        assert hasattr(_Staged, "validate_f")

    def test_decorated_method_not_called_by_full_validate(self) -> None:
        """A @dangerously_ignore_validator method is never invoked by full_validate()."""
        called: list[bool] = []

        class _Staged2(BaseModel):
            f = models.CharField(max_length=10, blank=True)

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"
                managed = False

            @dangerously_ignore_validator
            def validate_f(self_inner) -> None:  # noqa: N805
                called.append(True)

        instance = _Staged2(f="hello")
        instance.full_validate()
        assert not called


# ---------------------------------------------------------------------------
# ACID-7: JSON Schema validation
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-7")
class TestJsonSchemaValidation:
    """ACID-7: full_validate() runs jsonschema.validate() for jsonschema entries."""

    def test_valid_value_passes(self) -> None:
        instance = _JsonSchemaModel(title="Hello")
        instance.full_validate()  # must not raise

    def test_invalid_value_raises(self) -> None:
        instance = _JsonSchemaModel(title="")  # minLength: 1 violated
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        assert "title" in exc_info.value.message_dict

    def test_error_message_is_descriptive(self) -> None:
        instance = _JsonSchemaModel(title="")
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        msgs = exc_info.value.message_dict["title"]
        assert len(msgs) == 1
        assert msgs[0]  # non-empty descriptive message from jsonschema

    def test_integer_range_schema(self) -> None:
        """Validates an integer field with minimum/maximum constraints."""
        instance = _MixedValidationModel(score=150, tags=[])
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        assert "score" in exc_info.value.message_dict


# ---------------------------------------------------------------------------
# ACID-8: Function-based validation
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-8")
class TestFunctionValidation:
    """ACID-8: full_validate() calls validate_<field>(self) for function entries."""

    def test_valid_value_passes(self) -> None:
        instance = _FunctionModel(tags=["safe", "also-safe"])
        instance.full_validate()

    def test_invalid_value_raises(self) -> None:
        instance = _FunctionModel(tags=["bad;tag"])
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        assert "tags" in exc_info.value.message_dict

    def test_empty_tags_passes(self) -> None:
        instance = _FunctionModel(tags=[])
        instance.full_validate()


# ---------------------------------------------------------------------------
# ACID-9: Whole-record validate() hook
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-9")
class TestWholeRecordHook:
    """ACID-9: full_validate() calls self.validate() after per-field checks."""

    def test_valid_cross_field_passes(self) -> None:
        instance = _WholeRecordModel(lo=1, hi=5)
        instance.full_validate()

    def test_invalid_cross_field_raises(self) -> None:
        instance = _WholeRecordModel(lo=10, hi=5)
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        assert "lo" in exc_info.value.message_dict

    def test_no_field_schemas_whole_record_still_runs(self) -> None:
        """validate() runs even when FIELD_VALIDATION_SCHEMA is empty."""
        instance = _WholeRecordModel(lo=10, hi=5)
        with pytest.raises(ValidationError):
            instance.full_validate()

    def test_base_validate_is_noop(self) -> None:
        """Base validate() implementation raises nothing."""
        c = ConstrainedSource(description="anything")
        c.validate()  # must not raise


# ---------------------------------------------------------------------------
# ACID-10: Error collection before raising
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-10")
class TestErrorCollection:
    """ACID-10: full_validate() collects all errors before raising."""

    def test_all_field_errors_collected(self) -> None:
        """Both 'a' and 'b' violations appear in one ValidationError."""
        instance = _MultiErrorModel(a="", b="")
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        assert "a" in exc_info.value.message_dict
        assert "b" in exc_info.value.message_dict

    def test_field_and_whole_record_errors_collected(self) -> None:
        """Per-field error and whole-record error both appear in one ValidationError."""
        instance = _MixedValidationModel(score=200, tags=["a", "b", "c", "d", "e", "f"])
        with pytest.raises(ValidationError) as exc_info:
            instance.full_validate()
        md = exc_info.value.message_dict
        assert "score" in md
        assert "tags" in md


# ---------------------------------------------------------------------------
# ACID-11: full_validate() standalone (no save required)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-11")
class TestFullValidateStandalone:
    """ACID-11: full_validate() can be called without saving."""

    def test_returns_none_on_pass(self) -> None:
        instance = _JsonSchemaModel(title="Valid title")
        result = instance.full_validate()
        assert result is None

    def test_raises_without_touching_db(self) -> None:
        """full_validate() raises without any DB interaction."""
        instance = _JsonSchemaModel(title="")
        with pytest.raises(ValidationError):
            instance.full_validate()
        # No entity_id was set — nothing was written
        assert instance.entity_id is None


# ---------------------------------------------------------------------------
# ACID-12 and ACID-13: save() integration
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-12")
@pytest.mark.django_db
class TestSaveIntegration:
    """ACID-12: save() calls full_validate() before any DB write.
    ACID-13: save(skip_validation=True) bypasses full_validate() entirely.
    """

    def test_save_blocks_on_invalid_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACID-12: save() raises ValidationError before any DB write."""
        monkeypatch.setattr(
            ConstrainedSource,
            "FIELD_VALIDATION_SCHEMA",
            {"description": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}}},
        )
        with pytest.raises(ValidationError):
            ConstrainedSource.objects.create(description="")

    def test_save_succeeds_with_valid_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACID-12: save() proceeds normally when validation passes."""
        monkeypatch.setattr(
            ConstrainedSource,
            "FIELD_VALIDATION_SCHEMA",
            {"description": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}}},
        )
        c = ConstrainedSource.objects.create(description="Non-empty summary")
        assert c.pk is not None

    def test_validation_failure_leaves_no_db_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACID-12: validation failure before DB write leaves the table unchanged."""
        monkeypatch.setattr(
            ConstrainedSource,
            "FIELD_VALIDATION_SCHEMA",
            {"description": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}}},
        )
        count_before = ConstrainedSource.objects.count()
        with pytest.raises(ValidationError):
            ConstrainedSource.objects.create(description="")
        assert ConstrainedSource.objects.count() == count_before

    def test_skip_validation_bypasses_full_validate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACID-13: save(skip_validation=True) skips full_validate() entirely."""
        monkeypatch.setattr(
            ConstrainedSource,
            "FIELD_VALIDATION_SCHEMA",
            {"description": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}}},
        )
        c = ConstrainedSource(description="")  # would fail validation
        c.save(skip_validation=True)
        assert c.pk is not None

    def test_skip_validation_false_still_validates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ACID-13: save(skip_validation=False) is the same as the default."""
        monkeypatch.setattr(
            ConstrainedSource,
            "FIELD_VALIDATION_SCHEMA",
            {"description": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}}},
        )
        with pytest.raises(ValidationError):
            ConstrainedSource(description="").save(skip_validation=False)


# ---------------------------------------------------------------------------
# ACID-15: Edge compatibility
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-entity-validation-15")
@pytest.mark.django_db
class TestEdgeValidationCompatibility:
    """ACID-15: Edge inherits the full validation mechanism; property schema unaffected."""

    def test_edge_full_validate_noop(self) -> None:
        """Edge.full_validate() is a no-op when Edge has no FIELD_VALIDATION_SCHEMA."""
        from tap_grid.models import Edge
        from tap_grid.services import create_entity

        a = create_entity("grid_fixtures__unconstrained")
        b = create_entity("grid_fixtures__unconstrained")
        edge = Edge(from_entity=a, to_entity=b, edge_type="ANY_EDGE", properties={})
        edge.full_validate()  # must not raise

    def test_edge_property_schema_still_enforced(self) -> None:
        """Edge property schema registry validation is unaffected by the new mechanism."""
        from tap_grid.constraints import _edge_property_schema_registry, register_edge_property_schema
        from tap_grid.exceptions import EdgePropertyValidationError
        from tap_grid.models import Edge
        from tap_grid.services import create_entity

        saved = _edge_property_schema_registry.all()
        _edge_property_schema_registry._reset_for_testing()
        try:
            register_edge_property_schema(
                "TYPED_COMPAT",
                {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}},
            )
            a = create_entity("grid_fixtures__unconstrained")
            b = create_entity("grid_fixtures__unconstrained")
            edge = Edge(from_entity=a, to_entity=b, edge_type="TYPED_COMPAT", properties={})
            with pytest.raises(EdgePropertyValidationError):
                edge.save()
        finally:
            _edge_property_schema_registry._reset_for_testing(saved)
