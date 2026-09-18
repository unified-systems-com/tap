"""Clear any hashed keys a pre-withdrawal backfill may have stored (req-grid-entity-natural-key-11).

0004 changed the column's type and kept its values. On a grid that ran the now-deleted
``backfill_natural_keys --apply``, those values are UUIDv8 digests of a withdrawn recipe —
well-formed text that means nothing, in a column specified as inert. A placeholder that
holds leftovers reads as populated (Codex on #564). Data migration, kept separate from the
schema change per the add-model rule. Irreversible by design: the digests are not recoverable
and would not be wanted.
"""

from django.db import migrations


def clear_natural_keys(apps, schema_editor):  # type: ignore[no-untyped-def]
    entity = apps.get_model("tap_grid", "Entity")
    entity.objects.filter(natural_key__isnull=False).update(natural_key=None)


class Migration(migrations.Migration):
    dependencies = [
        ("tap_grid", "0004_entity_natural_key_placeholder"),
    ]

    operations = [
        migrations.RunPython(clear_natural_keys, migrations.RunPython.noop),
    ]
