from django.db import migrations, models


class Migration(migrations.Migration):
    """The Dimension node's third knob, ``empty_is_meaningful`` (req-grid-dimension-knobs-4; George,
    2026-11-13, aws-build Q59 D5): an empty value is refused on write unless the dimension declares
    that empty means something. Schema only; every existing node starts false."""

    dependencies = [
        ("tap_grid", "0012_dimensions_keyed_by_node"),
    ]

    operations = [
        migrations.AddField(
            model_name="dimension",
            name="empty_is_meaningful",
            field=models.BooleanField(
                default=False,
                help_text="Whether an empty value means something for this dimension (observed empty). When false, an empty value is refused on write (req-grid-dimension-knobs-4, aws-build Q59 D5).",
            ),
        ),
        migrations.AddField(
            model_name="historicaldimension",
            name="empty_is_meaningful",
            field=models.BooleanField(
                default=False,
                help_text="Whether an empty value means something for this dimension (observed empty). When false, an empty value is refused on write (req-grid-dimension-knobs-4, aws-build Q59 D5).",
            ),
        ),
    ]
