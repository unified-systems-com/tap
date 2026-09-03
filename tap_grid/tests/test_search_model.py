"""Tests for the Search model — req-grid-search-obj."""

import pytest
from django.core.exceptions import ValidationError

from tap_grid.models import Search


def _minimal_orm(**kwargs):
    """Return a minimal valid ORM Search kwargs dict, overridable via kwargs."""
    base = {
        "name": "Test Search",
        "search_type": "orm",
        "root": "node",
        "definition": {"filters": {"entity_type": "concept"}},
    }
    base.update(kwargs)
    return base


def _minimal_module(**kwargs):
    """Return a minimal valid module Search kwargs dict."""
    base = {
        "name": "Test Module Search",
        "search_type": "module",
        "root": "node",
        "definition": {"runner_key": "tap_plugins.tests:example"},
    }
    base.update(kwargs)
    return base


@pytest.mark.spec("req-grid-search-obj-1")
@pytest.mark.django_db
class TestSearchIsEntity:
    """req-grid-search-obj-1: Search is a first-class entity derived from BaseModel."""

    def test_creates_backing_entity_on_save(self):
        s = Search.objects.create(**_minimal_orm())
        assert s.entity_id is not None
        assert s.entity.entity_type == "search"

    def test_entity_type_constant(self):
        assert Search.ENTITY_TYPE == "search"

    def test_save_increments_entity_count(self):
        from tap_grid.models import Entity

        before = Entity.objects.filter(entity_type="search").count()
        Search.objects.create(**_minimal_orm(name="S1"))
        after = Entity.objects.filter(entity_type="search").count()
        assert after == before + 1


@pytest.mark.spec("req-grid-search-obj-2")
@pytest.mark.django_db
class TestSearchTypeField:
    """req-grid-search-obj-2: search_type supports 'module' and 'orm'."""

    def test_module_is_valid(self):
        s = Search(**_minimal_module())
        s.full_validate()  # should not raise

    def test_orm_is_valid(self):
        s = Search(**_minimal_orm())
        s.full_validate()

    def test_invalid_search_type_raises(self):
        s = Search(**_minimal_orm(search_type="sql"))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "search_type" in exc_info.value.message_dict

    def test_empty_search_type_raises(self):
        s = Search(**_minimal_orm(search_type=""))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "search_type" in exc_info.value.message_dict


@pytest.mark.spec("req-grid-search-obj-3")
@pytest.mark.django_db
class TestRootField:
    """req-grid-search-obj-3: root supports 'node' and 'edge'."""

    def test_node_is_valid(self):
        s = Search(**_minimal_orm(root="node"))
        s.full_validate()

    def test_edge_is_valid(self):
        s = Search(**_minimal_orm(root="edge"))
        s.full_validate()

    def test_invalid_root_raises(self):
        s = Search(**_minimal_orm(root="graph"))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "root" in exc_info.value.message_dict


@pytest.mark.spec("req-grid-search-obj-4")
@pytest.mark.django_db
class TestDefinitionField:
    """req-grid-search-obj-4: definition stored as JSON object."""

    def test_definition_stored_as_dict(self):
        defn = {"filters": {"entity_type": "concept"}, "order_by": ["id"]}
        s = Search.objects.create(**_minimal_orm(definition=defn))
        s.refresh_from_db()
        assert s.definition == defn

    def test_non_dict_definition_raises(self):
        s = Search(**_minimal_orm(definition=["not", "a", "dict"]))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "definition" in exc_info.value.message_dict


@pytest.mark.spec("req-grid-search-obj-5")
@pytest.mark.django_db
class TestInputSchemaField:
    """req-grid-search-obj-5: input_schema is an optional JSON Schema field."""

    def test_input_schema_none_by_default(self):
        s = Search.objects.create(**_minimal_orm())
        s.refresh_from_db()
        assert s.input_schema is None

    def test_input_schema_stores_json_schema(self):
        schema = {
            "type": "object",
            "required": ["character_id"],
            "properties": {"character_id": {"type": "string"}},
        }
        s = Search.objects.create(**_minimal_orm(input_schema=schema))
        s.refresh_from_db()
        assert s.input_schema == schema

    def test_schema_defaults_fill_absent_inputs(self):
        """req-grid-search-obj-5-2: a top-level `default` fills an absent input; a supplied value wins."""
        from tap_grid.search import _validate_inputs

        schema = {
            "type": "object",
            "properties": {"repo": {"type": "string", "default": "acme/widgets"}, "limit_hint": {"type": "integer"}},
        }
        s = Search.objects.create(**_minimal_orm(input_schema=schema))
        assert _validate_inputs(s, {}) == {"repo": "acme/widgets"}
        assert _validate_inputs(s, {"repo": "acme/other"}) == {"repo": "acme/other"}
        assert _validate_inputs(s, {"limit_hint": 3}) == {"repo": "acme/widgets", "limit_hint": 3}

    def test_schema_default_is_validated_and_no_schema_is_untouched(self):
        """req-grid-search-obj-5-2: defaults pass through validation; a search without a schema returns inputs as given."""
        from django.core.exceptions import ValidationError

        from tap_grid.search import _validate_inputs

        bad = {"type": "object", "properties": {"repo": {"type": "string", "default": 7}}}
        s = Search.objects.create(**_minimal_orm(input_schema=bad))
        with pytest.raises(ValidationError):
            _validate_inputs(s, {})
        plain = Search.objects.create(**_minimal_orm())
        assert _validate_inputs(plain, {"anything": 1}) == {"anything": 1}


@pytest.mark.spec("req-grid-search-obj-6")
@pytest.mark.django_db
class TestReturnsField:
    """req-grid-search-obj-6: returns is an optional preference object."""

    def test_returns_none_by_default(self):
        s = Search.objects.create(**_minimal_orm())
        s.refresh_from_db()
        assert s.returns is None

    def test_returns_stores_preference_object(self):
        prefs = {"primary": "nodes", "include": "both"}
        s = Search.objects.create(**_minimal_orm(returns=prefs))
        s.refresh_from_db()
        assert s.returns == prefs


@pytest.mark.spec("req-grid-search-obj-7")
@pytest.mark.django_db
class TestPaginationFields:
    """req-grid-search-obj-7: default_limit and max_limit are typed IntegerFields."""

    def test_pagination_fields_null_by_default(self):
        s = Search.objects.create(**_minimal_orm())
        s.refresh_from_db()
        assert s.default_limit is None
        assert s.max_limit is None

    def test_pagination_fields_accept_integers(self):
        s = Search.objects.create(**_minimal_orm(default_limit=25, max_limit=100))
        s.refresh_from_db()
        assert s.default_limit == 25
        assert s.max_limit == 100


@pytest.mark.spec("req-grid-search-obj-8")
@pytest.mark.django_db
class TestModuleDefinitionConstraints:
    """req-grid-search-obj-8: module definition only allows runner_key."""

    def test_runner_key_required(self):
        s = Search(**_minimal_module(definition={}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "runner_key" in msgs

    def test_runner_key_must_be_string(self):
        s = Search(**_minimal_module(definition={"runner_key": 42}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "definition" in exc_info.value.message_dict

    def test_extra_keys_rejected(self):
        s = Search(**_minimal_module(definition={"runner_key": "scope:key", "extra": "field"}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "extra" in msgs

    def test_valid_runner_key_accepted(self):
        s = Search(**_minimal_module())
        s.full_validate()  # should not raise


@pytest.mark.spec("req-grid-search-obj-9")
@pytest.mark.django_db
class TestCrossFieldValidation:
    """req-grid-search-obj-9: cross-field validation via validate() hook."""

    def test_orm_filters_required(self):
        s = Search(**_minimal_orm(definition={}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "filters" in msgs

    def test_orm_filters_must_be_dict(self):
        s = Search(**_minimal_orm(definition={"filters": ["list", "not", "dict"]}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "definition" in exc_info.value.message_dict

    def test_orm_hops_max_one(self):
        s = Search(
            **_minimal_orm(
                definition={
                    "filters": {},
                    "hops": [
                        {"direction": "out", "edge_type": "DEPENDS_ON"},
                        {"direction": "in", "edge_type": "APPLIES_TO"},
                    ],
                }
            )
        )
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "one hop" in msgs

    def test_orm_hop_direction_required(self):
        s = Search(
            **_minimal_orm(
                definition={
                    "filters": {},
                    "hops": [{"edge_type": "DEPENDS_ON"}],
                }
            )
        )
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "direction" in msgs

    def test_orm_hop_edge_type_required(self):
        s = Search(
            **_minimal_orm(
                definition={
                    "filters": {},
                    "hops": [{"direction": "out"}],
                }
            )
        )
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "edge_type" in msgs

    def test_orm_valid_with_hop(self):
        s = Search(
            **_minimal_orm(
                definition={
                    "filters": {"entity_type": "concept"},
                    "hops": [{"direction": "out", "edge_type": "DEPENDS_ON"}],
                    "order_by": ["id"],
                }
            )
        )
        s.full_validate()  # should not raise

    def test_orm_order_by_must_be_list(self):
        s = Search(**_minimal_orm(definition={"filters": {}, "order_by": "id"}))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        msgs = " ".join(exc_info.value.message_dict.get("definition", []))
        assert "order_by" in msgs

    def test_invalid_search_type_does_not_crash_validate(self):
        """validate() skips cross-field checks when search_type is invalid."""
        s = Search(
            name="Bad",
            search_type="sql",
            root="node",
            definition={"filters": {}},
        )
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        # search_type error is present, no AttributeError or crash
        assert "search_type" in exc_info.value.message_dict

    def test_title_required(self):
        s = Search(**_minimal_orm(name=""))
        with pytest.raises(ValidationError) as exc_info:
            s.full_validate()
        assert "name" in exc_info.value.message_dict
