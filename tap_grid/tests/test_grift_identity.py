"""Identity resolution at the gate — slice 2 (Issue# 594 - tap; parent Issue# 571 - tap;
#571 done-tests 1, 2, 3, 6, 7; ``req-grid-entity-natural-key-9`` and ``-13``).

Inside the batch transaction each ref node goes through ``resolve_identity``: the type's
declared search finds the live row the source object already has, or the preflight's
assigned id stands. Zero matches assigns, one returns, more than one fails the whole batch
with one application-class Flaw. Two writers resolving the same source object serialise on
a lock keyed by the declaration, so the second finds what the first created — observed with
two connections, not asserted from reading.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import pytest
from django.db import transaction

from tap_grid.cascade_corpus.timing import finish, in_thread
from tap_grid.exceptions import ServiceValidationError
from tap_grid.grift import grift_import
from tap_grid.models import Batch, Entity
from tap_grid.natural_key import constituting_properties, identity_lock_key
from tap_grid.services import create_node, delete_node, resolve_identity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

WEB = {"tap.graph": "web"}


def _panel_ref(ref: str, slug: str, name: str = "Panel") -> dict[str, Any]:
    return {
        "entity": {"ref": ref, "entity_type": "panel", "name": name, "dimensions": WEB},
        "node": {"name": name, "slug": slug, "description": "", "view": "tap_web/panel_error.html"},
    }


def _bundle(slug: str, name: str = "Panel") -> dict[str, Any]:
    """A fresh batch (its own id) naming one panel by ref, keyed on ``slug``."""
    return _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_panel_ref("it", slug, name)])])


def _resolved(result: Any) -> str:
    assert result.success, result.errors
    return str(result.imported_batches[0].resolved_refs["it"])


def _flaws(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "message_code", None) == "FLAW"]


@pytest.mark.django_db
class TestResolution:
    def test_reimporting_a_ref_bundle_finds_the_same_rows(self) -> None:
        """#571 done-test 1: the second batch is a replace of the row the first created."""
        first = _resolved(grift_import(_bundle("home", "Home")))
        second_result = grift_import(_bundle("home", "Home, renamed"))
        second = _resolved(second_result)
        assert second == first
        assert Panel.objects.filter(slug="home").count() == 1
        assert Entity.objects.get(pk=uuid.UUID(first)).name == "Home, renamed"
        (batch,) = second_result.imported_batches
        assert [u.entity_id for u in batch.upserted_entities] == [first], "the second import replaced, not created"
        assert Batch.objects.filter(entity__deleted_at__isnull=True).count() >= 2

    def test_a_tombstoned_row_is_not_found_and_a_new_id_is_assigned(self) -> None:
        """#571 done-test 2: the tombstone is terminal and untouched; the return is a new row."""
        first = _resolved(grift_import(_bundle("gone")))
        assert delete_node(first, reason="operator").success
        tombstone = Entity.objects.get(pk=uuid.UUID(first))
        assert tombstone.deleted_at is not None
        version_after_delete = tombstone.version

        third = _resolved(grift_import(_bundle("gone")))
        assert third != first and uuid.UUID(third).version == 7
        tombstone.refresh_from_db()
        assert tombstone.deleted_at is not None and tombstone.version == version_after_delete
        assert Panel.objects.filter(slug="gone", entity__deleted_at__isnull=True).count() == 1

    def test_ambiguity_fails_the_whole_batch_with_one_flaw(self, caplog: pytest.LogCaptureFixture) -> None:
        """#571 done-test 3: two live panels share a slug (legal at the model layer, #555)."""
        payload = {"name": "Dup", "slug": "dup", "description": "", "view": "tap_web/panel_error.html"}
        ids = sorted(str(create_node("panel", payload, caller_context=None).entity_id) for _ in range(2))
        before = Entity.objects.count()
        doc = _minimal_doc(
            [_batch_container(_batch_entity_id(), nodes=[_panel_ref("fine", "unique-here"), _panel_ref("it", "dup")])]
        )
        with caplog.at_level(logging.ERROR, logger="tap_grid.grift.importer"):
            result = grift_import(doc)
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "identity_ambiguous" and issue.entity_type == "panel"
        assert issue.path.endswith(".nodes[1].entity.ref")
        assert all(candidate in issue.message for candidate in ids), "the detail names both candidates"
        flaws = _flaws(caplog)
        assert len(flaws) == 1, "exactly one application-class Flaw per failed batch"
        data = flaws[0].__dict__["message_data"]
        assert data["flaw_class"] == "app" and data["invariant_id"] == "identity_ambiguous"
        assert data["context"]["candidates"] == ids
        assert Entity.objects.count() == before, "nothing written — not even the unambiguous node"
        assert not Batch.objects.filter(entity_id=doc["batches"][0]["batch_entity"]["entity_id"]).exists()

    def test_an_undeclared_type_is_refused(self) -> None:
        """Undeclared is never keyless: a ref on a type with no NATURAL_KEY fails closed."""
        before = Entity.objects.count()
        node = {
            "entity": {"ref": "it", "entity_type": "grid_fixtures__constrained_source", "name": "x", "dimensions": {}},
            "node": {"name": "x", "description": "y"},
        }
        doc = _minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])])
        result = grift_import(doc)
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "identity_undeclared" and "NATURAL_KEY" in issue.message
        assert Entity.objects.count() == before

    def test_two_refs_describing_one_object_on_an_empty_grid_fail_the_batch(self) -> None:
        """Issue# 602 - tap: resolution precedes the batch's writes, so the search cannot see the
        first of the pair; the derived identity key can. Nothing is written, not the bystander either."""
        before = Entity.objects.count()
        doc = _minimal_doc(
            [
                _batch_container(
                    _batch_entity_id(),
                    nodes=[_panel_ref("bystander", "unrelated"), _panel_ref("a", "same"), _panel_ref("b", "same", "B")],
                )
            ]
        )
        result = grift_import(doc)
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "duplicate_entity_id" and issue.path.endswith(".nodes[2].entity.ref")
        assert "'a'" in issue.message and issue.entity_type == "panel"
        assert Entity.objects.count() == before
        assert not Batch.objects.filter(entity_id=doc["batches"][0]["batch_entity"]["entity_id"]).exists()
        assert not Panel.objects.filter(slug__in=["same", "unrelated"]).exists()

    @pytest.mark.parametrize("ref_first", [True, False], ids=["ref-then-id", "id-then-ref"])
    def test_a_ref_that_resolves_to_a_row_this_batch_also_addresses_by_id_fails_the_batch(
        self, ref_first: bool
    ) -> None:
        """Issue# 606 - tap: preflight's duplicate check saw the provisional id, so it is re-applied
        against the id the ref actually resolved to. Both orders; nothing written."""
        existing = _resolved(grift_import(_bundle("x", "X")))
        before = Entity.objects.count()
        version = Entity.objects.get(pk=uuid.UUID(existing)).version
        explicit = {
            "entity": {"entity_id": existing, "entity_type": "panel", "name": "X by id", "dimensions": WEB},
            "node": {"name": "X by id", "slug": "x", "description": "", "view": "tap_web/panel_error.html"},
        }
        nodes = (
            [_panel_ref("it", "x", "X by ref"), explicit]
            if ref_first
            else [explicit, _panel_ref("it", "x", "X by ref")]
        )
        bid = _batch_entity_id()
        result = grift_import(_minimal_doc([_batch_container(bid, nodes=nodes)]))
        assert not result.success
        (issue,) = result.errors
        assert (
            issue.code == "duplicate_entity_id" and issue.entity_id == existing and issue.path.endswith(".entity.ref")
        )
        assert Entity.objects.count() == before
        assert Entity.objects.get(pk=uuid.UUID(existing)).version == version
        assert Entity.objects.get(pk=uuid.UUID(existing)).name == "X", "neither write landed"
        assert not Batch.objects.filter(entity_id=bid).exists()

    @pytest.mark.parametrize("section", ["deletes", "purges"])
    def test_a_ref_that_resolves_to_a_removal_target_of_this_batch_fails_the_batch(
        self, section: str, settings: Any
    ) -> None:
        """Issue# 606 - tap: the upsert-versus-removal collision, re-applied to the resolved id."""
        settings.DEBUG = True  # purge sections are DEBUG-only; the deletes case does not need it
        existing = _resolved(grift_import(_bundle("x", "X")))
        before = Entity.objects.count()
        bid = _batch_entity_id()
        container = _batch_container(bid, nodes=[_panel_ref("it", "x", "X again")])
        policy = {
            "on_missing": "error",
            "edges": [],
            "nodes": [{"entity_id": existing, "entity_type": "panel", "reason": "gone"}],
        }
        if section == "deletes":
            policy["on_tombstoned"] = "error"
        container[section] = policy
        result = grift_import(_minimal_doc([container]))
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "entity_id_in_upsert_and_removal" and issue.entity_id == existing
        assert f"{section}.nodes" in issue.message
        assert Entity.objects.count() == before
        row = Entity.objects.get(pk=uuid.UUID(existing))
        assert row.deleted_at is None and row.name == "X", "neither the write nor the removal landed"
        assert not Batch.objects.filter(entity_id=bid).exists()

    @pytest.mark.parametrize("ref_first", [True, False], ids=["ref-then-id", "id-then-ref"])
    def test_a_ref_that_misses_beside_an_explicit_new_node_with_its_values_fails_the_batch(
        self, ref_first: bool
    ) -> None:
        """Grok on PR# 604 - tap: empty grid, one ref and one explicitly addressed *new* node carrying the
        same declared values. Neither search can see the other, so the derived key decides."""
        before = Entity.objects.count()
        explicit = {
            "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "panel", "name": "By id", "dimensions": WEB},
            "node": {"name": "By id", "slug": "same", "description": "", "view": "tap_web/panel_error.html"},
        }
        nodes = [_panel_ref("it", "same"), explicit] if ref_first else [explicit, _panel_ref("it", "same")]
        bid = _batch_entity_id()
        result = grift_import(_minimal_doc([_batch_container(bid, nodes=nodes)]))
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "duplicate_entity_id" and issue.path.endswith(".entity.ref")
        assert explicit["entity"]["entity_id"] in issue.message
        assert Entity.objects.count() == before and not Panel.objects.filter(slug="same").exists()
        assert not Batch.objects.filter(entity_id=bid).exists()

    def test_a_ref_beside_a_different_explicit_row_is_fine(self) -> None:
        other = _resolved(grift_import(_bundle("other", "Other")))
        explicit = {
            "entity": {"entity_id": other, "entity_type": "panel", "name": "Other, renamed", "dimensions": WEB},
            "node": {"name": "Other, renamed", "slug": "other", "description": "", "view": "tap_web/panel_error.html"},
        }
        result = grift_import(
            _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_panel_ref("it", "x"), explicit])])
        )
        assert result.success, result.errors
        assert Panel.objects.filter(slug__in=["x", "other"]).count() == 2

    def test_two_refs_with_different_keys_are_both_created(self) -> None:
        """The dedupe is by identity key, so distinct source objects of one type are not a false positive."""
        doc = _minimal_doc(
            [_batch_container(_batch_entity_id(), nodes=[_panel_ref("a", "one"), _panel_ref("b", "two")])]
        )
        result = grift_import(doc)
        assert result.success, result.errors
        assert Panel.objects.filter(slug__in=["one", "two"]).count() == 2

    def test_two_refs_that_resolve_to_one_row_fail_the_batch(self) -> None:
        _resolved(grift_import(_bundle("one")))
        before = Entity.objects.count()
        doc = _minimal_doc(
            [_batch_container(_batch_entity_id(), nodes=[_panel_ref("a", "one"), _panel_ref("b", "one", "B")])]
        )
        result = grift_import(doc)
        assert not result.success and {e.code for e in result.errors} == {"duplicate_entity_id"}
        assert Entity.objects.count() == before


@pytest.mark.django_db
class TestTheVerb:
    def test_a_keyless_type_is_always_assigned(self) -> None:
        with transaction.atomic():
            first = resolve_identity("edge", {"edge_type": "USES_PANEL"})
            second = resolve_identity("edge", {"edge_type": "USES_PANEL"})
        assert first.keyless and second.keyless and not first.found
        assert first.key is None, "a keyless type has no identity key, so nothing dedupes on it"
        assert first.entity_id != second.entity_id and first.entity_id.version == 7

    def test_the_provisional_id_stands_when_nothing_is_found(self) -> None:
        provisional = uuid.uuid7()
        with transaction.atomic():
            resolution = resolve_identity("panel", {"slug": "nobody-has-this"}, provisional=provisional)
        assert resolution.entity_id == provisional and not resolution.found
        assert resolution.key is not None and "nobody-has-this" in resolution.key

    def test_a_hole_in_a_constituting_value_assigns_without_a_search(self) -> None:
        with transaction.atomic():
            resolution = resolve_identity("panel", {"name": "no slug at all"})
        assert not resolution.found

    def test_an_unknown_type_is_a_validation_error(self) -> None:
        with transaction.atomic(), pytest.raises(ServiceValidationError, match="Unknown entity type"):
            resolve_identity("no_such_type", {})


@pytest.mark.django_db(transaction=True)
class TestOutsideATransaction:
    def test_the_verb_refuses_to_run_without_one(self) -> None:
        """The lock is transaction-scoped; resolution outside one would release it before the write."""
        with pytest.raises(ServiceValidationError, match="inside the caller's transaction"):
            resolve_identity("panel", {"slug": "x"})


@pytest.mark.django_db(transaction=True)
class TestTwoWriters:
    def test_two_concurrent_imports_of_one_ref_bundle_make_one_row(self) -> None:
        """#571 done-test 6: the lock serialises the two resolutions; the second finds the first's row."""
        a = in_thread(lambda: grift_import(_bundle("race", "A")))
        b = in_thread(lambda: grift_import(_bundle("race", "B")))
        finish(a, b)
        ra, rb = a[1].value, b[1].value
        assert ra.success and rb.success, (ra.errors, rb.errors)
        assert ra.imported_batches[0].resolved_refs["it"] == rb.imported_batches[0].resolved_refs["it"]
        assert Panel.objects.filter(slug="race").count() == 1
        assert Batch.objects.count() >= 2, "both batches committed"


def test_the_lock_key_is_a_function_of_the_declaration() -> None:
    props = constituting_properties(("slug", "name"), {"name": "N", "slug": "s", "extra": 1})
    assert props == {"slug": "s", "name": "N"}
    assert identity_lock_key("panel", props) == identity_lock_key("panel", {"name": "N", "slug": "s"})
    assert identity_lock_key("panel", props) != identity_lock_key("page", props)
    assert identity_lock_key("panel", constituting_properties(("slug",), {})) is None
    assert identity_lock_key("panel", {"slug": ""}) is None
