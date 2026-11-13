"""The spine natural key (``req-grid-entity-natural-key-19`` .. ``-25``; Issue# 1178 - tap).

``Entity.natural_key`` holds each keyed row's natural key in the grid's standard form, derived from
the declared columns on every write and never supplied (spine only — no per-model column). A
single-field key is its value verbatim (an ARN, bare); a multi-field key joins its field-coerced
values in declared order with ``|``, escaping only ``%`` and ``|``. The identity lock key keeps its
own format, so old and new importers still share a lock. ``panel`` is the live fixture: keyed on ``slug`` alone, so its key is the slug.
"""

from __future__ import annotations

import datetime
import decimal
import inspect
import re
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import FieldDoesNotExist
from django.db import connection, models

from tap_grid.grift import grift_import
from tap_grid.models import Entity
from tap_grid.natural_key import (
    KEY_SEPARATOR,
    PREFIX_INDEX_CHARS,
    compose_natural_key,
    encode_key_part,
    identity_lock_key,
    natural_key_prefix,
    recipe_fingerprint,
    split_key,
)
from tap_grid.services import create_node, delete_node, patch_node
from tap_grid.spine_natural_key import check, find_by_spine_key, resync_natural_keys, sync
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

_PANEL_FIELDS: dict[str, Any] = {"name": "Identity", "view": "tap_web/panels/identity.html"}


def _panel(slug: str) -> Any:
    result = create_node("panel", {"slug": slug, **_PANEL_FIELDS})
    assert result.success, result.errors
    return Panel.objects.get(entity_id=result.entity_id)


def _fake_model(declared: tuple[str, ...] = (), **fields: models.Field[Any, Any]) -> Any:
    """Just enough of a model for coercion: ``_meta.get_field`` over real, unbound Django fields."""

    def get_field(name: str) -> models.Field[Any, Any]:
        if name not in fields:
            raise FieldDoesNotExist(name)
        return fields[name]

    return SimpleNamespace(_meta=SimpleNamespace(get_field=get_field), NATURAL_KEY=declared, ENTITY_TYPE="probe")


ADDRESS = _fake_model(
    ("network_name", "address", "transport", "port"),
    network_name=models.CharField(max_length=64),
    address=models.GenericIPAddressField(),
    transport=models.CharField(max_length=8),
    port=models.IntegerField(),
    config=models.JSONField(),
)


class TestSingleFieldKeys:
    """-19: a single-field key is its value, verbatim — no prefix, no escaping."""

    def test_an_arn_arrives_bare(self) -> None:
        arn = "arn:aws-us-gov:ec2:us-gov-west-1:123456789012:vpc/vpc-0abc"
        assert compose_natural_key(None, {"arn": arn}) == arn

    def test_separators_and_percents_are_not_escaped(self) -> None:
        assert compose_natural_key(None, {"v": "a|b%c"}) == "a|b%c"

    def test_a_hole_is_null_and_empty_is_a_value(self) -> None:
        assert compose_natural_key(None, {"v": None}) is None
        assert compose_natural_key(None, {"v": ""}) == ""


class TestStringificationIsPinned:
    """-19: each scalar has exactly one spelling (tenable c, anchore a)."""

    def test_uuid_lower_case_hyphenated(self) -> None:
        value = uuid.UUID("0000000A-0000-0000-0000-00000000000B")
        assert compose_natural_key(None, {"v": value}) == "0000000a-0000-0000-0000-00000000000b"

    def test_datetime_iso_8601_in_utc(self) -> None:
        eastern = datetime.timezone(datetime.timedelta(hours=-5))
        aware = datetime.datetime(2026, 11, 11, 0, 0, tzinfo=eastern)
        assert compose_natural_key(None, {"v": aware}) == "2026-11-11T05:00:00+00:00"
        assert compose_natural_key(None, {"v": datetime.datetime(2026, 11, 11, 5)}) == "2026-11-11T05:00:00+00:00"

    def test_date_iso_8601(self) -> None:
        assert compose_natural_key(None, {"v": datetime.date(2026, 11, 11)}) == "2026-11-11"

    def test_bool_int_and_decimal(self) -> None:
        assert compose_natural_key(None, {"v": True}) == "true"
        assert compose_natural_key(None, {"v": 443}) == "443"
        assert compose_natural_key(None, {"v": 2.0}) == "2"
        assert compose_natural_key(None, {"v": decimal.Decimal("1.50")}) == "1.5"
        assert compose_natural_key(None, {"v": decimal.Decimal("1E+2")}) == "100"

    def test_ip_in_the_field_s_canonical_form(self) -> None:
        long = compose_natural_key(ADDRESS, {"address": "FE80:0000:0000:0000:0000:0000:0000:0001"})
        assert long == compose_natural_key(ADDRESS, {"address": "fe80::1"}) == "fe80::1"

    def test_empty_is_a_value_distinct_from_a_hole(self) -> None:
        assert compose_natural_key(None, {"a": "a", "b": ""}) == "a|"
        assert compose_natural_key(None, {"a": "a", "b": None}) is None

    def test_a_json_entry_keeps_its_json_type_in_the_string(self) -> None:
        """A JSON entry renders as JSON, so 123 and "123" — two identities to the typed search — are
        two strings too."""
        assert compose_natural_key(ADDRESS, {"config.k": 123}) == "123"
        assert compose_natural_key(ADDRESS, {"config.k": "123"}) == '"123"'
        assert compose_natural_key(ADDRESS, {"config.k": {"b": 1, "a": 1.0}}) == '{"a":1,"b":1}'


class TestMultiFieldKeys:
    """-19: values joined in declared order, escaped so the join splits back exactly."""

    def test_values_join_in_declared_order_and_stay_readable(self) -> None:
        properties = {"network_name": "corp", "address": "fe80::1", "transport": "tcp", "port": "443"}
        assert compose_natural_key(ADDRESS, properties) == "corp|fe80::1|tcp|443"

    def test_the_separator_and_the_escape_are_escaped(self) -> None:
        assert encode_key_part("a|b%c") == "a%7Cb%25c"
        assert compose_natural_key(None, {"a": "x|y", "b": "50%"}) == "x%7Cy|50%25"

    def test_the_join_splits_back_exactly(self) -> None:
        for parts in (["fe80::1", "%7C", "a|b%c"], ["", "x"], ["50%25", "|"]):
            key = compose_natural_key(None, {f"c{i}": part for i, part in enumerate(parts)})
            assert key is not None
            assert split_key(key) == parts

    def test_the_separator_is_one_constant(self) -> None:
        assert KEY_SEPARATOR == "|"

    def test_the_lock_key_keeps_its_format(self) -> None:
        """A changed lock string would let an old and a new importer lock different strings for one
        object during a rolling deploy and both create it, so the lock key did not move."""
        assert identity_lock_key("panel", {"slug": "s"}) == 'panel\x1f{"slug":"s"}'
        assert identity_lock_key("panel", {"slug": None}) is None

    def test_there_is_no_per_model_column_or_format(self) -> None:
        """Ruled 2026-11-11 (Q34): spine only; the representation is core's."""
        from tap_grid.models import BaseModel

        assert not hasattr(BaseModel, "NATURAL_KEY_FORMAT")
        assert "natural_key" not in {f.name for f in Panel._meta.get_fields()}


class TestPrefixes:
    """-24: a prefix of leading values ends with the separator."""

    def test_the_prefix_ends_with_the_separator(self) -> None:
        prefix = natural_key_prefix(ADDRESS, {"network_name": "corp", "address": "10.0.1.5"})
        assert prefix == "corp|10.0.1.5|"
        assert "corp|10.0.1.5|tcp|443".startswith(prefix)
        assert not "corp|10.0.1.50|tcp|443".startswith(prefix)

    def test_values_in_a_prefix_are_coerced_and_escaped_like_the_key(self) -> None:
        assert natural_key_prefix(ADDRESS, {"network_name": "a|b"}) == "a%7Cb|"

    def test_only_a_leading_run_shorter_than_the_key(self) -> None:
        with pytest.raises(ValueError, match="leading run"):
            natural_key_prefix(ADDRESS, {"address": "10.0.1.5"})
        with pytest.raises(ValueError, match="leading run"):
            natural_key_prefix(ADDRESS, {"network_name": "c", "address": "a", "transport": "t", "port": 1})
        with pytest.raises(ValueError, match="two or more"):
            natural_key_prefix(_fake_model(("arn",)), {"arn": "x"})


@pytest.mark.django_db
class TestTheWritePaths:
    """-19: every write derives the spine key; nothing authors it."""

    def test_create_and_patch(self) -> None:
        panel = _panel("before-rename")
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "before-rename"
        result = patch_node(str(panel.entity_id), {"slug": "after-rename"})
        assert result.success, result.errors
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "after-rename"

    def test_a_prespecified_id_create(self) -> None:
        from tap_grid.service_types import WriteOperation
        from tap_grid.services import write_batch

        entity_id = uuid.uuid7()
        op = WriteOperation(
            verb="create_node",
            type_slug="panel",
            payload={"slug": "given-id", **_PANEL_FIELDS},
            entity_id=str(entity_id),
        )
        written = write_batch([op])
        assert written.success, written.errors
        assert Entity.objects.get(pk=entity_id).natural_key == "given-id"

    def test_a_supplied_key_never_lands(self) -> None:
        result = create_node("panel", {"slug": "honest", "natural_key": "forged", **_PANEL_FIELDS})
        if result.success:
            assert result.entity_id is not None
            assert Entity.objects.get(pk=result.entity_id).natural_key == "honest"

    def test_a_keyless_row_has_no_key(self) -> None:
        from tap_grid.models import Batch

        _panel("makes-a-batch")
        batch = Batch.objects.order_by("-entity__created_at").first()
        assert batch is not None
        assert batch.entity.natural_key is None

    def test_a_partial_save_keys_on_what_the_row_holds(self) -> None:
        """update_fields leaves the slug unsaved, so the spine key stays the stored slug."""
        from tap_grid.write_guard import unguarded_write

        panel = _panel("partly-saved")
        panel.slug = "never-written"
        panel.name = "renamed"
        with unguarded_write():
            panel.save(update_fields=["name"])
        assert Panel.objects.get(entity_id=panel.entity_id).slug == "partly-saved"
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "partly-saved"

    def test_a_partial_save_of_a_constituting_column_re_derives(self) -> None:
        from tap_grid.write_guard import unguarded_write

        panel = _panel("before-partial")
        panel.slug = "after-partial"
        with unguarded_write():
            panel.save(update_fields=["slug"])
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "after-partial"

    @pytest.mark.enforce_write_guard
    def test_a_key_column_update_outside_the_service_layer_is_still_refused(self) -> None:
        """The key-column branch of update() reimplements the write; it must still fail closed, and
        refuse before it reads anything."""
        from tap_auth.errors import UnguardedOperation

        panel = _panel("guarded")
        with pytest.raises(UnguardedOperation):
            # update() is typed against BaseModel, so django-stubs cannot see Panel.slug.
            Panel.objects.filter(slug="guarded").update(slug="never")  # type: ignore[misc]
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "guarded"

    def test_a_queryset_update_of_a_constituting_column_re_derives(self) -> None:
        """The filter matches on the very column being changed, so the rows are named first."""
        from tap_grid.write_guard import unguarded_write

        panel = _panel("by-update")
        other = _panel("untouched")
        with unguarded_write():
            # BaseModelQuerySet.update is typed against BaseModel, so django-stubs cannot see Panel.slug.
            Panel.objects.filter(slug="by-update").update(slug="renamed-by-update")  # type: ignore[misc]
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "renamed-by-update"
        assert Entity.objects.get(pk=other.entity_id).natural_key == "untouched"

    def test_a_bulk_update_of_a_constituting_column_re_derives(self) -> None:
        from tap_grid.write_guard import unguarded_write

        panel = _panel("bulk-before")
        panel.slug = "bulk-after"
        with unguarded_write():
            Panel.objects.bulk_update([panel], ["slug"])
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "bulk-after"

    def test_a_bulk_update_that_writes_nothing_leaves_the_spine(self) -> None:
        """A filtered queryset can skip the object; its unsaved slug must not reach the spine."""
        from tap_grid.write_guard import unguarded_write

        panel = _panel("bulk-skipped")
        panel.slug = "never-written-in-bulk"
        with unguarded_write():
            # none() is typed against BaseModel, so django-stubs cannot see Panel.slug.
            Panel.objects.none().bulk_update([panel], ["slug"])  # type: ignore[misc]
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "bulk-skipped"

    def test_a_bulk_create_conflict_ignored_leaves_the_spine(self) -> None:
        """ignore_conflicts skips the insert for an existing row, so the spine keeps the stored key."""
        from tap_grid.write_guard import unguarded_write

        panel = _panel("bulk-existing")
        clash = Panel(entity_id=panel.entity_id, slug="never-inserted", **_PANEL_FIELDS)
        with unguarded_write():
            Panel.objects.bulk_create([clash], ignore_conflicts=True)
        assert Panel.objects.get(entity_id=panel.entity_id).slug == "bulk-existing"
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "bulk-existing"

    def test_a_tombstone_keeps_its_key(self) -> None:
        """-25 (anchore b): retirement never nulls the key; the indexes are not partial."""
        panel = _panel("retired-one")
        assert delete_node(panel.entity_id).success
        retired = Entity.objects.get(pk=panel.entity_id)
        assert retired.deleted_at is not None
        assert retired.natural_key == "retired-one"
        assert find_by_spine_key(equals="retired-one", entity_type="panel").filter(pk=panel.entity_id).exists()

    def test_stored_equals_derived_for_every_keyed_live_row(self) -> None:
        """The invariant, over every registered keyed type with rows in this database."""
        from tap_grid.models import BaseModel
        from tap_grid.registry import get_model_class, list_entity_types

        _panel("invariant-a")
        _panel("invariant-b")
        wrong = []
        checked = 0
        for entity_type in list_entity_types():
            model = get_model_class(entity_type)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                continue
            for row in model.objects.live().select_related("entity"):
                checked += 1
                if row.entity.natural_key != row.derive_natural_key():
                    wrong.append((entity_type, row.entity_id, row.entity.natural_key, row.derive_natural_key()))
        assert checked >= 2
        assert wrong == []


def _panel_bundle(slug: str, *, name: str = "Imported", config: dict[str, Any] | None = None) -> dict[str, Any]:
    node = {
        "entity": {"ref": "it", "entity_type": "panel", "name": name, "dimensions": {"tap.graph": "web"}},
        "node": {
            "name": name,
            "slug": slug,
            "description": "",
            "view": "tap_web/panel_error.html",
            "config": config or {},
        },
    }
    return _minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])])


def _imported(result: Any) -> str:
    assert result.success, result.errors
    return str(result.imported_batches[0].resolved_refs["it"])


@pytest.mark.django_db
class TestThroughTheImporter:
    """-19 (anchore): the GRIFT importer is the only path some plugins write through."""

    def test_a_node_created_and_updated_by_import_carries_its_key(self) -> None:
        first = _imported(grift_import(_panel_bundle("imported-panel")))
        assert Entity.objects.get(pk=first).natural_key == "imported-panel"
        again = _imported(grift_import(_panel_bundle("imported-panel", name="Renamed On Reimport")))
        assert again == first
        assert Entity.objects.get(pk=first).natural_key == "imported-panel"

    def test_a_key_over_the_btree_row_limit_stores_and_is_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """-22: a 3000+ byte key must not fail the write, and equality and prefix must find it."""
        monkeypatch.setattr(Panel, "NATURAL_KEY", ("slug", "config.tenant"))
        tenant = "é" * 1600  # 3200 bytes in UTF-8
        entity_id = _imported(grift_import(_panel_bundle("long", config={"tenant": tenant})))
        stored = Entity.objects.get(pk=entity_id).natural_key
        assert stored is not None and len(stored.encode("utf-8")) >= 3000
        assert stored == f'long|"{tenant}"'
        assert [str(pk) for pk in find_by_spine_key(equals=stored).values_list("pk", flat=True)] == [entity_id]
        assert find_by_spine_key(prefix="long|", entity_type="panel").filter(pk=entity_id).exists()
        beyond_the_index = stored[: PREFIX_INDEX_CHARS + 100]
        assert find_by_spine_key(prefix=beyond_the_index).filter(pk=entity_id).exists()
        assert not find_by_spine_key(prefix=beyond_the_index + "x").filter(pk=entity_id).exists()


@pytest.mark.django_db
class TestTheIndexesAreUsed:
    """-22: equality uses the hash index, a prefix the expression index (tenable)."""

    @staticmethod
    def _plan(queryset: Any) -> str:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
        return str(queryset.explain())

    def test_equality_uses_the_hash_index(self) -> None:
        _panel("planned")
        assert "idx_entity_natural_key_hash" in self._plan(find_by_spine_key(equals="planned"))

    def test_a_prefix_uses_the_expression_index(self) -> None:
        _panel("planned-prefix")
        assert "idx_entity_natural_key_prefix" in self._plan(find_by_spine_key(prefix="planned"))

    def test_like_wildcards_in_a_prefix_are_literal(self) -> None:
        _panel("under-score")
        _panel("underXscore")
        found = set(find_by_spine_key(prefix="under_s").values_list("natural_key", flat=True))
        assert found == set()
        assert set(find_by_spine_key(prefix="under-").values_list("natural_key", flat=True)) == {"under-score"}


@pytest.mark.django_db
class TestOutputOnly:
    """-21: nothing finds, merges or refuses a row by the spine key."""

    def test_a_wrong_spine_key_does_not_change_what_resolution_finds(self) -> None:
        from tap_grid.services import resolve_identity
        from tap_grid.write_guard import unguarded_write

        real = _panel("the-real-one")
        decoy = _panel("the-decoy")
        with unguarded_write():
            Entity.objects.filter(pk=decoy.entity_id).update(natural_key="the-real-one")
            Entity.objects.filter(pk=real.entity_id).update(natural_key="something-else")

        resolution = resolve_identity("panel", {"slug": "the-real-one", **_PANEL_FIELDS})
        assert str(resolution.entity_id) == str(real.entity_id)

    def test_a_duplicate_key_refuses_nothing(self) -> None:
        """-22: two rows with one key is legal; neither write is blocked."""
        from tap_grid.write_guard import unguarded_write

        first = _panel("dup-first")
        second = _panel("dup-second")
        with unguarded_write():
            Entity.objects.filter(pk=second.entity_id).update(natural_key="dup-first")
        result = patch_node(str(first.entity_id), {"name": "Still Writable"})
        assert result.success, result.errors

    @pytest.mark.parametrize("function", ["resolve_identity", "find_existing", "search"])
    def test_identity_code_never_names_the_column(self, function: str) -> None:
        from tap_grid import natural_key
        from tap_grid.models import BaseModel
        from tap_grid.services import resolve_identity

        targets: dict[str, Any] = {
            "resolve_identity": resolve_identity,
            "find_existing": BaseModel.find_existing,
            "search": natural_key.search,
        }
        source = inspect.getsource(targets[function])
        lines = [
            line
            for line in source.splitlines()
            if re.search(r"\bnatural_key\b", line) and not re.search(r"tap_grid\.natural_key|find_by_natural_key", line)
        ]
        assert lines == [], f"{function} names the spine key: {lines}"


@pytest.mark.django_db
class TestCatchUpAndDrift:
    """-23, -25: stale keys are re-derived; drift and changed recipes are reported."""

    def _stale(self, panel: Any) -> None:
        from tap_grid.write_guard import unguarded_write

        with unguarded_write():
            Entity.objects.filter(pk=panel.entity_id).update(natural_key="stale")

    def test_sync_rewrites_a_stale_key_and_is_idempotent(self) -> None:
        panel = _panel("stale-one")
        self._stale(panel)
        assert sync(["panel"]).written >= 1
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "stale-one"
        assert sync(["panel"]).written == 0

    def test_resync_is_the_call_for_a_plugin_data_migration(self) -> None:
        panel = _panel("resynced")
        self._stale(panel)
        assert resync_natural_keys("panel").written >= 1
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "resynced"
        with pytest.raises(ValueError, match="name the entity types"):
            resync_natural_keys()

    def test_check_reports_drift_and_is_clean_after_sync(self) -> None:
        panel = _panel("drifting")
        sync(["panel"])
        self._stale(panel)
        drift = check(["panel"], sample=10_000)
        assert [row[0] for row in drift.drifted["panel"]] == [str(panel.entity_id)]
        sync(["panel"])
        assert check(["panel"], sample=10_000).clean

    def test_a_changed_field_option_changes_the_fingerprint(self) -> None:
        """to_python can depend on options as well as the class (unpack_ipv4 on an IP field)."""
        from tap_grid.natural_key import _field_recipe

        packed = models.GenericIPAddressField(name="address")
        unpacked = models.GenericIPAddressField(name="address", unpack_ipv4=True, protocol="both")
        assert _field_recipe(packed) != _field_recipe(unpacked)
        assert _field_recipe(models.CharField(name="s", max_length=9, help_text="a")) == _field_recipe(
            models.CharField(name="s", max_length=9, help_text="b")
        ), "a cosmetic option must not re-derive a type"

    def test_the_fingerprint_is_stable_across_processes(self) -> None:
        """A callable option is spelled by its import path, never a repr with a memory address."""
        from tap_grid.natural_key import _field_recipe

        fk = models.ForeignKey("tap_grid.Entity", on_delete=models.CASCADE, name="owner")
        assert "0x" not in _field_recipe(fk)

    def test_a_filtered_bulk_update_re_derives_a_row_it_moved_out_of_the_filter(self) -> None:
        from tap_grid.write_guard import unguarded_write

        panel = _panel("filtered-before")
        panel.slug = "filtered-after"
        with unguarded_write():
            # The filter is typed against BaseModel, so django-stubs cannot see Panel.slug.
            Panel.objects.filter(slug="filtered-before").bulk_update([panel], ["slug"])  # type: ignore[misc]
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "filtered-after"

    def test_a_rollback_does_not_run_the_catch_up(self) -> None:
        from tap_grid.spine_natural_key import sync_after_migrate

        panel = _panel("rolled-back")
        sync(["panel"])
        self._stale(panel)
        from tap_grid.models import NaturalKeyRecipe

        NaturalKeyRecipe.objects.filter(entity_type="panel").delete()
        sync_after_migrate(None, plan=[(object(), True)])
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "stale"

    def test_a_changed_field_class_changes_the_fingerprint(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Composition runs the field's to_python first, so a constituting column changing class can
        change every key with the NATURAL_KEY tuple untouched; the fingerprint must see it."""
        before = recipe_fingerprint(Panel)
        real = Panel._meta.get_field

        def get_field(name: str) -> Any:
            return models.IntegerField(name="slug") if name == "slug" else real(name)

        monkeypatch.setattr(Panel._meta, "get_field", get_field)
        assert recipe_fingerprint(Panel) != before

    def test_a_changed_recipe_is_stale_until_the_changed_only_sync(self, monkeypatch: pytest.MonkeyPatch) -> None:
        panel = _panel("recipe")
        sync(["panel"])
        assert check(["panel"]).stale_recipes == []
        before = recipe_fingerprint(Panel)
        monkeypatch.setattr(Panel, "NATURAL_KEY", ("slug", "name"))
        assert recipe_fingerprint(Panel) != before
        assert check(["panel"]).stale_recipes == ["panel"]
        report = sync(["panel"], changed_only=True)
        assert report.types == 1
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "recipe|Identity"
        assert check(["panel"]).stale_recipes == []
        assert sync(["panel"], changed_only=True).types == 0

    def test_the_command_fails_on_drift(self) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        panel = _panel("commanded")
        sync(["panel"])
        self._stale(panel)
        with pytest.raises(CommandError, match="stale"):
            call_command("sync_spine_natural_keys", "--check", "--type", "panel")
        call_command("sync_spine_natural_keys", "--type", "panel")
        call_command("sync_spine_natural_keys", "--check", "--type", "panel")

    def test_an_undeclared_type_is_skipped_not_synced(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Undeclared is never keyless (-5): it gets no fingerprint and the check is not clean."""
        _panel("undeclared")
        monkeypatch.setattr(Panel, "NATURAL_KEY", None)
        report = sync(["panel"])
        assert "panel" in report.skipped and "undeclared" in report.skipped["panel"]
        assert not check(["panel"]).clean

    def test_an_undeclared_type_already_recorded_is_still_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The changed-only short-circuit must not carry a once-recorded type past the undeclared
        guard, and a skip alone (no stale recipe) keeps the check from being clean."""
        from tap_grid.models import NaturalKeyRecipe

        _panel("recorded-then-undeclared")
        monkeypatch.setattr(Panel, "NATURAL_KEY", None)
        # Record the fingerprint the undeclared type has now, so only the guard can catch it.
        NaturalKeyRecipe.objects.update_or_create(
            entity_type="panel", defaults={"fingerprint": recipe_fingerprint(Panel)}
        )
        report = sync(["panel"], changed_only=True)
        assert "undeclared" in report.skipped.get("panel", "")
        drift = check(["panel"])
        assert drift.stale_recipes == []
        assert "panel" in drift.skipped and not drift.clean

    def test_a_zero_row_sample_is_refused(self) -> None:
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(ValueError, match="at least 1"):
            check(["panel"], sample=0)
        with pytest.raises(CommandError, match="at least 1"):
            call_command("sync_spine_natural_keys", "--check", "--sample", "0", "--type", "panel")

    def test_a_skipped_type_is_not_clean(self) -> None:
        """A type the check could not read was not checked, so the report cannot be clean."""
        from tap_grid.spine_natural_key import DriftReport

        assert DriftReport().clean
        assert not DriftReport(skipped={"panel": "table tap_panel does not exist yet"}).clean

    def test_the_queryset_respine_fills_a_null_key(self) -> None:
        """exclude(natural_key=k) compiles to NOT (k = x AND k IS NOT NULL), so a null spine key is
        filled, not skipped."""
        from tap_grid.models import _copy_keys_to_spine
        from tap_grid.write_guard import unguarded_write

        panel = _panel("was-null")
        with unguarded_write():
            Entity.objects.filter(pk=panel.entity_id).update(natural_key=None)
            _copy_keys_to_spine([panel])
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "was-null"

    def test_a_named_type_that_does_not_exist_fails_the_command(self) -> None:
        """A typo would otherwise check zero types and report clean."""
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="unknown entity type"):
            call_command("sync_spine_natural_keys", "--check", "--type", "definitely-not-a-type")
        with pytest.raises(CommandError, match="unknown entity type"):
            call_command("sync_spine_natural_keys", "--type", "definitely-not-a-type")

    def test_migrate_runs_the_catch_up_and_flush_does_not(self) -> None:
        """post_migrate from migrate (a plan, even an empty one) re-derives changed recipes; from flush
        (no plan) it does nothing."""
        from tap_grid.spine_natural_key import sync_after_migrate

        panel = _panel("after-migrate")
        sync(["panel"])
        self._stale(panel)
        sync_after_migrate(None, plan=None)
        assert Entity.objects.get(pk=panel.entity_id).natural_key != "after-migrate"
        from tap_grid.models import NaturalKeyRecipe

        NaturalKeyRecipe.objects.filter(entity_type="panel").delete()
        sync_after_migrate(None, plan=[])
        assert Entity.objects.get(pk=panel.entity_id).natural_key == "after-migrate"
