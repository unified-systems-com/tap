"""A NATURAL_KEY entry may name a path into a JSON field (``req-grid-entity-natural-key-14``..``-18``;
Issue# 874 - tap).

A plugin whose source identity lives inside a JSON document (the first consumer is zizmor's
``location`` document) declares ``"location.route"`` instead of copying each value into a column.
What that entry must mean is decided once, in the identity module beside the sentinel, and these tests hold every
consumer of it to the same answer:

- the payload extraction (``constituting_properties``) and the lock (``identity_lock_key``),
- the generated search (``find_existing``) and the index it should be answered from,
- the guard that refuses a declaration pointing nowhere.

``panel`` is the fixture: keyed on ``slug`` in core, and it carries a ``config`` JSONField. Tests that
need the path form re-key it (``monkeypatch``) and add the matching index inside the test's
transaction, so nothing outlives the test. No core type declares a path; this is the feature's proof.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, models
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
from django.db.migrations.state import ModelState, ProjectState
from django.db.migrations.writer import MigrationWriter

from tap_grid.grift import grift_import
from tap_grid.models import Entity, _install_natural_key_index
from tap_grid.natural_key import (
    AmbiguousIdentity,
    constituting_properties,
    declaration_problems,
    identity_lock_key,
    index_expressions,
    is_path,
    search,
    split_path,
)
from tap_grid.services import delete_node
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

DECLARED = ("slug", "config.tenant")
SPEC_14 = pytest.mark.spec("req-grid-entity-natural-key-14")
SPEC_15 = pytest.mark.spec("req-grid-entity-natural-key-15")
SPEC_16 = pytest.mark.spec("req-grid-entity-natural-key-16")
SPEC_17 = pytest.mark.spec("req-grid-entity-natural-key-17")
SPEC_18 = pytest.mark.spec("req-grid-entity-natural-key-18")


class TestGrammar:
    @SPEC_14
    def test_a_column_is_not_a_path_and_a_dotted_entry_is(self) -> None:
        assert not is_path("slug")
        assert is_path("config.tenant")
        assert split_path("slug") == ("slug", ())
        assert split_path("config.tenant") == ("config", ("tenant",))
        assert split_path("config.tenant.id") == ("config", ("tenant", "id"))

    @SPEC_14
    @pytest.mark.parametrize("entry", ["config.", ".tenant", "config..tenant", "."])
    def test_an_empty_segment_is_refused(self, entry: str) -> None:
        with pytest.raises(ValueError, match="empty segment"):
            split_path(entry)

    @SPEC_14
    def test_an_all_digit_key_is_refused_because_django_would_read_it_as_an_array_index(self) -> None:
        with pytest.raises(ValueError, match="array index"):
            split_path("config.123")
        # A key that merely contains digits is a key.
        assert split_path("config.v2") == ("config", ("v2",))


class TestExtraction:
    """-14 and -16: the payload is read against the declaration in one place."""

    @SPEC_14
    def test_columns_and_paths_are_read_together(self) -> None:
        payload = {"slug": "s", "config": {"tenant": "acme", "other": 1}, "unrelated": True}
        assert constituting_properties(DECLARED, payload) == {"slug": "s", "config.tenant": "acme"}

    @SPEC_14
    def test_nested_paths(self) -> None:
        payload = {"location": {"workflow": {"id": 7}}}
        assert constituting_properties(("location.workflow.id",), payload) == {"location.workflow.id": 7}

    @SPEC_16
    def test_missing_key_json_null_and_a_non_object_parent_are_all_the_same_hole(self) -> None:
        for config in ({}, {"tenant": None}, None, "not an object", ["tenant"], 5):
            assert constituting_properties(DECLARED, {"slug": "s", "config": config})["config.tenant"] is None, config
        assert constituting_properties(DECLARED, {"slug": "s"})["config.tenant"] is None

    @SPEC_16
    def test_empty_string_is_a_value_not_a_hole(self) -> None:
        assert constituting_properties(DECLARED, {"slug": "s", "config": {"tenant": ""}})["config.tenant"] == ""

    @SPEC_15
    def test_scalars_keep_their_json_type(self) -> None:
        for value in (123, "123", 1.5, True, False):
            got = constituting_properties(("config.k",), {"config": {"k": value}})["config.k"]
            assert got == value and type(got) is type(value)


class TestLockKey:
    """-13/-15/-16: the lock is keyed on the same values, in the same types, as the search."""

    @SPEC_16
    def test_only_none_is_a_hole_and_empty_string_is_locked_like_it_is_searched(self) -> None:
        assert identity_lock_key("panel", {"slug": "s", "config.tenant": None}) is None
        assert identity_lock_key("panel", {"slug": "s", "config.tenant": ""}) is not None
        assert identity_lock_key("panel", {"slug": ""}) is not None
        assert identity_lock_key("panel", {"slug": "s", "config.tenant": ""}) != identity_lock_key(
            "panel", {"slug": "s", "config.tenant": "x"}
        )

    @SPEC_15
    def test_a_number_and_its_string_are_two_identities(self) -> None:
        as_number = identity_lock_key("panel", {"config.k": 123})
        as_string = identity_lock_key("panel", {"config.k": "123"})
        assert as_number != as_string
        assert identity_lock_key("panel", {"config.k": True}) != identity_lock_key("panel", {"config.k": 1})

    @SPEC_15
    def test_an_integral_float_and_the_integer_are_one_identity_as_jsonb_compares_them(self) -> None:
        assert identity_lock_key("panel", {"config.k": 1.0}) == identity_lock_key("panel", {"config.k": 1})
        assert identity_lock_key("panel", {"config.k": 1.5}) != identity_lock_key("panel", {"config.k": 1})

    @SPEC_15
    def test_the_canonical_form_reaches_into_object_and_array_leaves(self) -> None:
        """A leaf may be an object or array; ``jsonb`` equates ``{"n": 1}`` and ``{"n": 1.0}``, so the
        lock key must too, or two writers of one database identity take different locks."""
        key = identity_lock_key
        assert key("panel", {"config.k": {"n": 1}}) == key("panel", {"config.k": {"n": 1.0}})
        assert key("panel", {"config.k": [1, {"a": 2}]}) == key("panel", {"config.k": [1.0, {"a": 2.0}]})
        assert key("panel", {"config.k": {"a": 1, "b": 2}}) == key("panel", {"config.k": {"b": 2, "a": 1}})
        assert key("panel", {"config.k": {"n": 1}}) != key("panel", {"config.k": {"n": 1.5}})
        assert key("panel", {"config.k": [1, 2]}) != key("panel", {"config.k": [2, 1]}), "array order is identity"

    @SPEC_14
    def test_the_key_is_a_function_of_the_declared_entries(self) -> None:
        one = constituting_properties(DECLARED, {"slug": "s", "config": {"tenant": "t"}})
        two = constituting_properties(DECLARED, {"config": {"tenant": "t", "noise": 1}, "slug": "s"})
        assert identity_lock_key("panel", one) == identity_lock_key("panel", two)


@pytest.fixture
def keyed_on_a_path(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    """``panel`` re-keyed on ``(slug, config.tenant)`` with the index the declaration generates.

    The index is created through the schema editor inside the test's transaction, so PostgreSQL
    really has it (the plan test below depends on that) and the rollback removes it.
    """
    monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
    index = models.Index(*index_expressions(DECLARED), name="nk_web_panel_json_probe")
    with connection.schema_editor() as editor:
        editor.add_index(Panel, index)
    return DECLARED


def _panel(slug: str, config: dict[str, Any] | None) -> Panel:
    """Create a panel row directly: Panel's CRUD schema is not the subject here."""
    entity = Entity.objects.create(entity_type="panel", name=slug)
    made: Panel = Panel.objects.create(
        entity=entity, slug=slug, name=slug, view="tap_web/panels/identity.html", config=config
    )
    return made


@pytest.mark.django_db
class TestTheGeneratedSearch:
    """The search answers over a declared path, typed, among live rows."""

    @SPEC_14
    def test_finds_the_row_by_a_path_and_a_column(self, keyed_on_a_path: tuple[str, ...]) -> None:
        made = _panel("p", {"tenant": "acme"})
        _panel("p", {"tenant": "other"})
        found = Panel.find_existing(**{"slug": "p", "config.tenant": "acme"})
        assert found is not None and found.entity_id == made.entity_id
        assert Panel.find_existing(**{"slug": "p", "config.tenant": "nobody"}) is None

    @SPEC_14
    def test_nested_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "NATURAL_KEY", ("slug", "config.a.b"))
        made = _panel("p", {"a": {"b": "deep"}})
        _panel("p", {"a": {"b": "elsewhere"}})
        found = Panel.find_existing(**{"slug": "p", "config.a.b": "deep"})
        assert found is not None and found.entity_id == made.entity_id

    @SPEC_15
    def test_typed_equality_a_number_is_not_its_string(self, keyed_on_a_path: tuple[str, ...]) -> None:
        as_number = _panel("p", {"tenant": 123})
        as_string = _panel("p", {"tenant": "123"})
        by_number = Panel.find_existing(**{"slug": "p", "config.tenant": 123})
        by_string = Panel.find_existing(**{"slug": "p", "config.tenant": "123"})
        assert by_number is not None and by_number.entity_id == as_number.entity_id
        assert by_string is not None and by_string.entity_id == as_string.entity_id
        assert Panel.find_existing(**{"slug": "p", "config.tenant": True}) is None

    @SPEC_15
    def test_an_object_leaf_compares_by_jsonb_value_which_the_lock_key_mirrors(
        self, keyed_on_a_path: tuple[str, ...]
    ) -> None:
        made = _panel("p", {"tenant": {"n": 1}})
        found = Panel.find_existing(**{"slug": "p", "config.tenant": {"n": 1.0}})
        assert found is not None and found.entity_id == made.entity_id
        assert identity_lock_key("panel", {"config.tenant": {"n": 1}}) == identity_lock_key(
            "panel", {"config.tenant": {"n": 1.0}}
        )

    @SPEC_16
    def test_none_is_absent_without_a_query(
        self, keyed_on_a_path: tuple[str, ...], django_assert_num_queries: Any
    ) -> None:
        _panel("p", {"tenant": None})
        with django_assert_num_queries(0):
            assert Panel.find_existing(**{"slug": "p", "config.tenant": None}) is None

    @SPEC_16
    def test_empty_string_is_searched_and_finds_its_own_row(self, keyed_on_a_path: tuple[str, ...]) -> None:
        """Consistent with Issue# 866 - tap: ``""`` is observed-empty, so a key with an empty JSON
        part resolves to itself instead of reading as a second miss."""
        made = _panel("p", {"tenant": ""})
        _panel("p", {"tenant": "x"})
        _panel("p", {})
        found = Panel.find_existing(**{"slug": "p", "config.tenant": ""})
        assert found is not None and found.entity_id == made.entity_id

    @SPEC_16
    def test_a_stored_null_or_missing_key_is_never_matched_by_an_empty_string(
        self, keyed_on_a_path: tuple[str, ...]
    ) -> None:
        _panel("p", {"tenant": None})
        _panel("p", {})
        assert Panel.find_existing(**{"slug": "p", "config.tenant": ""}) is None

    @SPEC_14
    def test_two_live_matches_raise_and_a_tombstone_is_not_a_match(self, keyed_on_a_path: tuple[str, ...]) -> None:
        first = _panel("p", {"tenant": "t"})
        second = _panel("p", {"tenant": "t"})
        with pytest.raises(AmbiguousIdentity) as excinfo:
            Panel.find_existing(**{"slug": "p", "config.tenant": "t"})
        assert {str(c) for c in excinfo.value.candidates} == {str(first.entity_id), str(second.entity_id)}
        assert delete_node(second.entity_id).success
        found = Panel.find_existing(**{"slug": "p", "config.tenant": "t"})
        assert found is not None and found.entity_id == first.entity_id

    @SPEC_14
    def test_the_declared_entries_are_exactly_what_the_search_takes(self, keyed_on_a_path: tuple[str, ...]) -> None:
        with pytest.raises(ValueError, match=r"missing=\['config.tenant'\]"):
            Panel.find_existing(slug="p")


@pytest.mark.django_db
class TestTheIndexAnswersTheSearch:
    @SPEC_18
    def test_the_search_and_the_index_spell_the_expression_the_same_way(
        self, keyed_on_a_path: tuple[str, ...]
    ) -> None:
        """The search's expression and the index's are the same text, so PostgreSQL CAN match them.
        Two authored copies would drift silently; this compares the two directly.

        **Deliberately not an EXPLAIN assertion, and that is the point of this test's history.**
        It used to set ``enable_seqscan = off`` and assert the index NAME appeared in the plan.
        That passed locally and failed in CI (`product-lines`, 2026-09-29/30), because it asserted a
        planner CHOICE rather than the property above. The CI plan contained no sequential scan at
        all — `enable_seqscan` was honoured and irrelevant, since it discourages seq scans and does
        nothing to stop the planner preferring a DIFFERENT index. On a one-row table it took the
        unique index on ``entity_id`` and applied this predicate as a plain filter, which is a
        perfectly good plan and says nothing about drift.

        What drift would actually look like: the index is created once, at migration time, from
        ``index_expressions``; the search is compiled on every call. Both call ``_key_transform``
        today, so they cannot diverge in code — but a MIGRATED index outlives the code that wrote
        it. Comparing the stored ``indexdef`` against today's compiled SQL is what catches that, and
        it involves no planner, no row counts and no statistics.
        """
        _panel("p", {"tenant": "t"})
        sql, _params = search(Panel.objects.live(), {"slug": "p", "config.tenant": "t"}).query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = %s", ["nk_web_panel_json_probe"])
            (definition,) = cursor.fetchone()

        # The operator is the whole question: `->` yields jsonb and can answer a jsonb index;
        # `->>` yields text and silently cannot. Compare what each side spells on `config`.
        operator = re.compile(r"config\"?\s*(#>>|#>|->>|->)")
        in_search = operator.findall(sql.replace('"', ""))
        in_index = operator.findall(definition)
        assert in_search, sql
        assert in_index, definition
        assert set(in_search) == set(in_index) == {"->"}, (in_search, in_index, sql, definition)

    @SPEC_15
    def test_the_index_is_typed_jsonb_not_text(self, keyed_on_a_path: tuple[str, ...]) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'nk_web_panel_json_probe'")
            (definition,) = cursor.fetchone()
        assert "config #>" in definition or "config ->" in definition
        assert "->>" not in definition and "#>>" not in definition, definition


@pytest.mark.django_db
class TestResolvedThroughTheImporter:
    """End to end: a ref-addressed node whose identity lives in JSON is found again on re-import."""

    @staticmethod
    def _bundle(slug: str, config: dict[str, Any]) -> dict[str, Any]:
        node = {
            "entity": {"ref": "it", "entity_type": "panel", "name": slug, "dimensions": {"tap.graph": "web"}},
            "node": {
                "name": slug,
                "slug": slug,
                "description": "",
                "view": "tap_web/panel_error.html",
                "config": config,
            },
        }
        return _minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])])

    def _resolved(self, result: Any) -> str:
        assert result.success, result.errors
        return str(result.imported_batches[0].resolved_refs["it"])

    @SPEC_14
    def test_reimport_finds_the_same_row_and_a_different_path_value_makes_a_new_one(
        self, keyed_on_a_path: tuple[str, ...]
    ) -> None:
        first = self._resolved(grift_import(self._bundle("p", {"tenant": "acme"})))
        again = self._resolved(grift_import(self._bundle("p", {"tenant": "acme", "note": "changed"})))
        other = self._resolved(grift_import(self._bundle("p", {"tenant": "globex"})))
        assert again == first
        assert other != first
        assert Panel.objects.filter(slug="p").count() == 2

    @SPEC_16
    def test_an_empty_path_value_resolves_to_its_own_row_on_reimport(self, keyed_on_a_path: tuple[str, ...]) -> None:
        first = self._resolved(grift_import(self._bundle("p", {"tenant": ""})))
        again = self._resolved(grift_import(self._bundle("p", {"tenant": ""})))
        assert again == first
        assert Panel.objects.filter(slug="p").count() == 1

    @SPEC_16
    def test_a_hole_in_the_path_is_not_found_so_each_import_mints(self, keyed_on_a_path: tuple[str, ...]) -> None:
        """Documented behaviour, identical to a null column: with nothing to find by, a source that
        never offered the identifying value cannot be recognised again."""
        first = self._resolved(grift_import(self._bundle("p", {})))
        again = self._resolved(grift_import(self._bundle("p", {})))
        assert again != first


class _Probe:
    """A throwaway Django model with a JSON column, removed from the app registry on exit."""

    def __init__(self, declared: tuple[str, ...], schema: dict[str, Any] | None = None) -> None:
        attrs: dict[str, Any] = {
            "__module__": __name__,
            "NATURAL_KEY": declared,
            "repo": models.CharField(max_length=20),
            "location": models.JSONField(default=dict),
            "Meta": type("Meta", (), {"app_label": "tap_grid"}),
        }
        if schema is not None:
            attrs["FIELD_VALIDATION_SCHEMA"] = {"location": {"validation": "jsonschema", "schema": schema}}
        self.model: Any = type("NkJsonProbe", (models.Model,), attrs)

    def __enter__(self) -> Any:
        return self.model

    def __exit__(self, *exc: object) -> None:
        apps.all_models["tap_grid"].pop("nkjsonprobe", None)
        apps.clear_cache()


class TestTheGuard:
    """-17: a declaration that points nowhere is a failure, not a search that finds nothing."""

    SCHEMA = {
        "type": "object",
        "properties": {"route": {"type": "string"}, "workflow": {"type": "object", "properties": {"id": {}}}},
    }

    @SPEC_17
    def test_a_sound_declaration_has_no_problems(self) -> None:
        with _Probe(("repo", "location.route"), self.SCHEMA) as model:
            assert declaration_problems(model, model.NATURAL_KEY) == []

    @SPEC_17
    def test_a_path_under_a_column_that_is_not_json_is_refused(self) -> None:
        with _Probe(("repo.x",)) as model:
            (problem,) = declaration_problems(model, model.NATURAL_KEY)
            assert "CharField" in problem and "not a JSONField" in problem

    @SPEC_17
    def test_an_unknown_root_and_a_malformed_entry_are_refused(self) -> None:
        with _Probe(("repo",)) as model:
            problems = declaration_problems(model, ("nope.x", "location.", "nope"))
        assert len(problems) == 3
        assert "'nope' is not a model field" in problems[0]

    @SPEC_17
    def test_a_key_the_declared_schema_does_not_have_is_refused(self) -> None:
        with _Probe(("location.rout",), self.SCHEMA) as model:
            (problem,) = declaration_problems(model, model.NATURAL_KEY)
            assert "'rout' is not among the schema's properties" in problem and "route" in problem

    @SPEC_17
    def test_the_schema_is_walked_level_by_level_and_silence_is_not_a_failure(self) -> None:
        with _Probe(("location.workflow.id", "location.workflow.unlisted.deeper"), self.SCHEMA) as model:
            problems = declaration_problems(model, model.NATURAL_KEY)
        # workflow.properties names only "id": "unlisted" is a miss; "id" has no properties, so is fine.
        assert len(problems) == 1 and "'unlisted'" in problems[0]

    @SPEC_17
    def test_no_schema_means_no_key_check(self) -> None:
        with _Probe(("location.anything.goes",)) as model:
            assert declaration_problems(model, model.NATURAL_KEY) == []

    @SPEC_17
    def test_startup_refuses_a_path_it_cannot_index_and_names_the_entry(self) -> None:
        with _Probe(("repo.x",)) as model, pytest.raises(ImproperlyConfigured, match=r"repo\.x.*not a JSONField"):
            _install_natural_key_index(model)

    @SPEC_17
    def test_startup_does_not_police_the_schema(self) -> None:
        """A key the schema does not list is the guard's finding, not a reason to refuse to boot."""
        with _Probe(("location.rout",), self.SCHEMA) as model:
            _install_natural_key_index(model)
            assert [i.name for i in model._meta.indexes] == ["nk_tap_grid_nkjsonprobe"]


class TestIndexAndMigration:
    """-18: an expression index, visible to the autodetector, and unchanged for column-only keys."""

    @staticmethod
    def _diff(old: ModelState, new: ModelState) -> list[str]:
        before, after = ProjectState(), ProjectState()
        before.add_model(old.clone())
        after.add_model(new.clone())
        detector: Any = MigrationAutodetector(before, after, NonInteractiveMigrationQuestioner())
        changes = detector._detect_changes()
        return [type(op).__name__ for migrations in changes.values() for m in migrations for op in m.operations]

    @staticmethod
    def _without_index(state: ModelState) -> ModelState:
        bare = state.clone()
        bare.options = {**bare.options, "indexes": []}
        return bare

    @SPEC_18
    def test_a_path_declaration_generates_an_expression_index_the_autodetector_sees(self) -> None:
        with _Probe(("repo", "location.route")) as model:
            _install_natural_key_index(model)
            (index,) = model._meta.indexes
            assert index.name == "nk_tap_grid_nkjsonprobe"
            assert index.expressions and not index.fields
            assert model._meta.original_attrs["indexes"] is model._meta.indexes
            state = ModelState.from_model(model)
            assert self._diff(self._without_index(state), state) == ["AddIndex"]
            # It serialises into a migration a reader can review.
            operation = MigrationWriter.serialize(index)[0]
            assert "KeyTransform('route', 'location')" in operation and "models.F('repo')" in operation

    @SPEC_18
    def test_changing_a_declared_path_is_a_migration(self) -> None:
        """-8: same index name, different definition, so remove-then-add — not silently nothing."""
        with _Probe(("repo", "location.route")) as model:
            _install_natural_key_index(model)
            before = ModelState.from_model(model)
            model.NATURAL_KEY = ("repo", "location.workflow")
            model._meta.indexes = []
            _install_natural_key_index(model)
            after = ModelState.from_model(model)
        assert self._diff(before, after) == ["RemoveIndex", "AddIndex"]

    @SPEC_18
    def test_a_column_only_declaration_keeps_its_fields_index(self) -> None:
        with _Probe(("repo", "location")) as model:
            _install_natural_key_index(model)
            (index,) = model._meta.indexes
            assert list(index.fields) == ["repo", "location"] and not index.expressions

    @SPEC_18
    def test_a_core_column_declaration_still_generates_the_fields_index(self) -> None:
        """No core type declares a path (asserted in the declaration guard), so no core migration moves."""
        (panel_index,) = (i for i in Panel._meta.indexes if i.name.startswith("nk_"))
        assert list(panel_index.fields) == ["slug"] and not panel_index.expressions
