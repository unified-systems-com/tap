"""The parity check between a migrated and a model-built database (req-boot-schema-from-models-5).

The nightly runs the real thing (product-lines.yml `migrations`); these pin what it compares and
what it ignores, without building two databases.
"""

from __future__ import annotations

import pytest

from tap import schema_parity
from tap.schema_parity import Snapshot

_DUMP_A = """--
-- PostgreSQL database dump
--
\\restrict abc123
SET statement_timeout = 0;
SELECT pg_catalog.set_config('search_path', '', false);

CREATE TABLE public.tap_entity (
    entity_id uuid NOT NULL,
    name character varying(255) NOT NULL
);

CREATE INDEX tap_entity_name_idx ON public.tap_entity USING btree (name);
\\unrestrict abc123
"""

# Same schema, different run: other restrict key, statements in another order, other spacing.
_DUMP_B = """\\restrict zzz999
CREATE INDEX tap_entity_name_idx ON public.tap_entity USING btree (name);

CREATE TABLE public.tap_entity (
  entity_id uuid NOT NULL,
  name character varying(255) NOT NULL
);
\\unrestrict zzz999
"""


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_dump_noise_and_order_do_not_count() -> None:
    assert schema_parity.schema_statements(_DUMP_A) == schema_parity.schema_statements(_DUMP_B)


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_parity_is_silent() -> None:
    same = Snapshot(["CREATE TABLE t (a int)"], {"t": (0, "")}, {("app", "0001_initial")})
    assert schema_parity.compare(same, same) == ([], [])


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_each_kind_of_difference_is_named() -> None:
    migrated = Snapshot(
        ["CREATE TABLE t (a int)", "CREATE TRIGGER trg AFTER INSERT ON t"],
        {"t": (0, ""), "django_site": (1, "x")},
        {("app", "0001_initial"), ("app", "0002_seed")},
    )
    models = Snapshot(["CREATE TABLE t (a int)"], {"t": (0, ""), "django_site": (0, "")}, {("app", "0001_initial")})
    problems, _notes = schema_parity.compare(migrated, models)
    report = "\n".join(problems)
    assert "schema differs" in report and "-CREATE TRIGGER trg AFTER INSERT ON t" in report
    assert "rows differ in django_site: migrated 1 row(s), models 0" in report
    assert "app.0002_seed recorded only by the migrated road" in report


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_column_order_and_generated_names_are_noted_not_failed() -> None:
    """A migration appends columns and names constraints by creation order; neither is a drift."""
    migrated = Snapshot(
        [
            "CREATE TABLE public.t ( id bigint NOT NULL, b jsonb CONSTRAINT t_b_not_null1 NOT NULL, a integer )",
            "ALTER TABLE ONLY public.t ADD CONSTRAINT t_a_3f2a9c1e_uniq UNIQUE (a)",
        ]
    )
    models = Snapshot(
        [
            "CREATE TABLE public.t ( id bigint NOT NULL, a integer, b jsonb NOT NULL )",
            "ALTER TABLE ONLY public.t ADD CONSTRAINT t_a_key UNIQUE (a)",
        ]
    )
    problems, notes = schema_parity.compare(migrated, models)
    assert problems == []
    assert notes and "differ only in column order or generated names" in notes[0]


@pytest.mark.spec("req-boot-schema-from-models-5")
def test_a_type_difference_fails_unless_it_is_a_known_one() -> None:
    def table(name: str, kind: str) -> Snapshot:
        return Snapshot([f"CREATE TABLE {name} ( id {kind} NOT NULL, group_id integer NOT NULL )"])

    problems, _ = schema_parity.compare(table("public.t", "bigint"), table("public.t", "integer"))
    assert problems and "schema differs" in problems[0]
    known = "public.auth_group_permissions"
    problems, notes = schema_parity.compare(table(known, "bigint"), table(known, "integer"))
    assert problems == [] and notes == [f"accepted difference in {known}: {schema_parity.KNOWN_DIFFERENCES[known]}"]


def test_a_known_table_still_fails_on_any_drift_but_the_id_width() -> None:
    known = "public.auth_group_permissions"
    migrated = Snapshot([f"CREATE TABLE {known} ( id bigint NOT NULL, group_id integer NOT NULL )"])
    models = Snapshot([f"CREATE TABLE {known} ( id integer NOT NULL, group_id integer NOT NULL, extra text )"])
    problems, notes = schema_parity.compare(migrated, models)
    assert problems and "schema differs" in problems[0]
    assert not any("accepted difference" in note for note in notes)
