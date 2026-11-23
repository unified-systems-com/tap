"""Spine version 2 (req-grid-entity-spine-version, Issue# 1288 - tap): the base-model release.

- Removes the typed row's ``batch_id`` from every core table. The batch that last changed a row is the
  spine's ``last_changed_batch_id`` (req-grid-entity-batch-pointers); the batch that produced each
  history row stays on the history row's own ``batch_id`` column, which this migration does not touch
  (``tap_grid.history.HistoricalBatchRecord``).
- Adds the spine copies ``spine_deleted_at`` and ``spine_dimensions`` to every core typed table and its
  history table (req-grid-entity-spine-copies). The triggers that keep them, the type map and the
  filling of existing rows are installed after migrate by ``tap_grid.spine_copies.install_after_migrate``,
  for these tables and every plugin's, so this migration carries no SQL.
- Indexes ``Entity.last_observed_at`` (req-grid-entity-batch-pointers rule 12, owner ruling Q49 on
  Issue# 1284 - tap).
- Carries ``batch`` to model version 2: it now declares no event time, where it declared nothing
  (owner ruling, Issue# 1284 - tap). The step is the identity, so no row is written.
"""

from typing import Any

from django.db import migrations, models


def batch_to_version_2(apps: Any, schema_editor: Any) -> None:
    from tap_grid.version_migration import apply_version

    apply_version(apps, schema_editor, "batch", to_version=2)


class Migration(migrations.Migration):

    dependencies = [
        ("tap_grid", "0022_model_and_spine_versions"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="batch",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="dimension",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="edge",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="keystone",
            name="batch_id",
        ),
        migrations.RemoveField(
            model_name="search",
            name="batch_id",
        ),
        migrations.AddField(
            model_name="batch",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="batch",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="dimension",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="dimension",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="edge",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="edge",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalbatch",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalbatch",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicaldimension",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicaldimension",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicaledge",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicaledge",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalkeystone",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalkeystone",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="historicalsearch",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalsearch",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="keystone",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="keystone",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        migrations.AddField(
            model_name="search",
            name="spine_deleted_at",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="Copy of Entity.deleted_at, kept by the database. Empty while the entity is live.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="search",
            name="spine_dimensions",
            field=models.JSONField(
                blank=True,
                default=dict,
                editable=False,
                help_text="Copy of Entity.dimensions in the stored shape, kept by the database.",
            ),
        ),
        # "Not seen since" (req-grid-entity-batch-pointers rule 12), indexed by owner ruling Q49
        # (Issue# 1284 - tap).
        migrations.AddIndex(
            model_name="entity",
            index=models.Index(fields=["last_observed_at"], name="idx_entity_last_observed_at"),
        ),
        migrations.RunPython(batch_to_version_2, migrations.RunPython.noop),
    ]
