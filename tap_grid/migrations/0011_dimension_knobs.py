from django.db import migrations, models


class Migration(migrations.Migration):
    """The Dimension node's first two knobs (req-grid-dimension-knobs; George, 2026-11-12, aws-build Q47,
    Q51, Q52a): ``values`` (a list makes the dimension bounded, null leaves it open) and ``usable_in_keys``
    (whether a type may name it in a NATURAL_KEY). Schema only; existing nodes stay open and not usable
    in keys until their seed says otherwise."""

    dependencies = [
        ('tap_grid', '0010_entity_natural_key_backfill'),
    ]

    operations = [
        migrations.AddField(
            model_name='dimension',
            name='usable_in_keys',
            field=models.BooleanField(default=False, help_text='Whether a type may name this dimension in its NATURAL_KEY (req-grid-dimension-knobs, aws-build Q52a). Declares eligibility only; immutability on rows is a separate rule (tap#1186).'),
        ),
        migrations.AddField(
            model_name='dimension',
            name='values',
            field=models.JSONField(blank=True, default=None, help_text="The dimension's allowed values. A list makes the dimension bounded: only these values are accepted. Null makes it open: any string is accepted (req-grid-dimension-knobs, aws-build Q47).", null=True),
        ),
        migrations.AddField(
            model_name='historicaldimension',
            name='usable_in_keys',
            field=models.BooleanField(default=False, help_text='Whether a type may name this dimension in its NATURAL_KEY (req-grid-dimension-knobs, aws-build Q52a). Declares eligibility only; immutability on rows is a separate rule (tap#1186).'),
        ),
        migrations.AddField(
            model_name='historicaldimension',
            name='values',
            field=models.JSONField(blank=True, default=None, help_text="The dimension's allowed values. A list makes the dimension bounded: only these values are accepted. Null makes it open: any string is accepted (req-grid-dimension-knobs, aws-build Q47).", null=True),
        ),
    ]
