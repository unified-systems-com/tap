from django.db import migrations, models


class Migration(migrations.Migration):
    """``Entity.dimensions``' help text names the stored shape that ``Entity.save`` now enforces
    (PR 1196 round 3). Help text only; no schema or data change."""

    dependencies = [
        ("tap_grid", "0013_dimension_empty_is_meaningful"),
    ]

    operations = [
        migrations.AlterField(
            model_name="entity",
            name="dimensions",
            field=models.JSONField(
                default=dict,
                help_text='The entity\'s dimensions, keyed by Dimension node uuid, each value {"v": <string>, "src": declared|default|derived} (req-grid-dimension-reference). Written through tap_grid.dimension_map; Entity.save refuses any other shape.',
            ),
        ),
    ]
