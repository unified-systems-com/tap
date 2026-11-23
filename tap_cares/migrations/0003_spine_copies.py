"""The base-model release for ``tap_cares`` (Issue# 1288 - tap).

Removes the typed row's ``batch_id`` and adds the spine copies (req-grid-entity-spine-copies) to each
table, and carries ``collection_job``, ``schedule`` and ``schedule_fire`` to model version 2: each now
declares no event time, where it declared nothing (owner ruling, Issue# 1284 - tap). The steps are the
identity, so no row is written.
"""

from typing import Any

from django.db import migrations, models


def to_version_2(apps: Any, schema_editor: Any) -> None:
    from tap_grid.version_migration import apply_version

    for type_slug in ("collection_job", "schedule", "schedule_fire"):
        apply_version(apps, schema_editor, type_slug, to_version=2)


class Migration(migrations.Migration):

    dependencies = [
        ("tap_grid", "0023_spine_copies"),
        ("tap_cares", "0002_collector_reconcile_authority"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="collectionjob",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="collector",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="schedule",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="schedulefire",
            name="batch_id",
        ),
        migrations.AddField(
            model_name="collectionjob",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="collectionjob",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="collector",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="collector",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalcollectionjob",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollectionjob",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalcollector",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollector",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalschedule",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedule",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalschedulefire",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedulefire",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="schedule",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="schedule",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="schedulefire",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="schedulefire",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.RunPython(to_version_2, migrations.RunPython.noop),
    ]
