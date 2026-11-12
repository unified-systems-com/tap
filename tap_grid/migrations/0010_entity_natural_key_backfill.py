"""Publish every keyed row's natural key on the spine, for every plugin (req-grid-entity-natural-key-23, -25).

One core pass over every registered type, core and plugin — no plugin ships a migration for this.
Each type's recipe fingerprint is recorded once its rows are in step. A type whose table does not
exist yet (a plugin installed later, or whose own migrations run after this one) is skipped and gets
no fingerprint, so ``manage.py sync_spine_natural_keys --changed``, run at deploy, derives it.
It reads the declaration from the registered model classes, because the historical models a
migration is handed carry no ``NATURAL_KEY``; see ``tap_grid.spine_natural_key``.

Reverse clears the column and the recorded fingerprints.
"""

from django.db import migrations


def publish(apps, schema_editor):  # type: ignore[no-untyped-def]
    from tap_grid.spine_natural_key import sync

    sync(using=schema_editor.connection.alias)


def clear(apps, schema_editor):  # type: ignore[no-untyped-def]
    alias = schema_editor.connection.alias
    apps.get_model("tap_grid", "Entity").objects.using(alias).filter(natural_key__isnull=False).update(natural_key=None)
    apps.get_model("tap_grid", "NaturalKeyRecipe").objects.using(alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tap_grid", "0009_naturalkeyrecipe"),
    ]

    operations = [
        migrations.RunPython(publish, clear),
    ]
