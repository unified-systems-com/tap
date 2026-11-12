import django.contrib.postgres.indexes
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    """The spine natural key becomes a published, derived value (req-grid-entity-natural-key-19..22).

    Schema only. The help text says what the column now holds. The plain btree 0004 put on it is
    dropped: a btree index row over ~2700 bytes is an error on insert, and a composed key can be
    longer, so it would fail a batch. In its place a hash index serves equality (no size limit) and a
    btree over the first 600 characters, with ``text_pattern_ops``, serves prefix search. The backfill
    is its own data migration (0010), per the add-model rule.
    """

    dependencies = [
        ("tap_grid", "0007_batchevent_authority_proposed"),
    ]

    operations = [
        migrations.AlterField(
            model_name="entity",
            name="natural_key",
            field=models.TextField(
                blank=True,
                help_text="The row's natural key in the grid's standard form, for cross-type search: a single-field key's value verbatim (an ARN, bare), a multi-field key's field-coerced values joined in declared order with '|'. No type prefix: entity_type is on the row. Derived by the grid on every write, never authored; null for a KEYLESS type or an unobserved constituting value; kept on a tombstone. Output only: no lookup, merge or refusal reads it — a row is found by its model's NATURAL_KEY search. Non-unique by design. Indexed by hash (equality) and by its first characters (prefix), never by a plain btree, which refuses a long value. See req-grid-entity-natural-key.",
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name="entity",
            index=django.contrib.postgres.indexes.HashIndex(fields=["natural_key"], name="idx_entity_natural_key_hash"),
        ),
        migrations.AddIndex(
            model_name="entity",
            index=models.Index(
                django.contrib.postgres.indexes.OpClass(
                    django.db.models.functions.text.Left("natural_key", 600), name="text_pattern_ops"
                ),
                name="idx_entity_natural_key_prefix",
            ),
        ),
    ]
