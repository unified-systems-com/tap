"""History rows carry the event time (req-grid-history-event-time, Issue# 1374 - tap).

Adds ``event_start`` (indexed), ``event_end`` and ``event_precision`` to each ``tap_cares`` history
table: history-only columns declared on ``tap_grid.history.HistoricalBatchRecord`` and set when a
history row is written (``tap_grid.spine_copies.fill_history_row``). No typed table changes. A row
written before this holds no event time, which reads as not recorded.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tap_cares", "0003_spine_copies"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalcollectionjob",
            name="event_end",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When it stopped holding, at this version. Exclusive. Equal to `event_start` for an exact moment; empty when no end was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollectionjob",
            name="event_precision",
            field=models.CharField(
                blank=True,
                choices=[("year", "year"), ("month", "month"), ("day", "day"), ("second", "second")],
                editable=False,
                help_text="How exact the source value was at this version: year, month, day or second. Coarser than second means the stored pair is the interval the unit covers.",
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollectionjob",
            name="event_start",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                editable=False,
                help_text="When the thing happened, or began to hold, at this version. Inclusive. Empty when no time was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollector",
            name="event_end",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When it stopped holding, at this version. Exclusive. Equal to `event_start` for an exact moment; empty when no end was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollector",
            name="event_precision",
            field=models.CharField(
                blank=True,
                choices=[("year", "year"), ("month", "month"), ("day", "day"), ("second", "second")],
                editable=False,
                help_text="How exact the source value was at this version: year, month, day or second. Coarser than second means the stored pair is the interval the unit covers.",
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalcollector",
            name="event_start",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                editable=False,
                help_text="When the thing happened, or began to hold, at this version. Inclusive. Empty when no time was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedule",
            name="event_end",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When it stopped holding, at this version. Exclusive. Equal to `event_start` for an exact moment; empty when no end was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedule",
            name="event_precision",
            field=models.CharField(
                blank=True,
                choices=[("year", "year"), ("month", "month"), ("day", "day"), ("second", "second")],
                editable=False,
                help_text="How exact the source value was at this version: year, month, day or second. Coarser than second means the stored pair is the interval the unit covers.",
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedule",
            name="event_start",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                editable=False,
                help_text="When the thing happened, or began to hold, at this version. Inclusive. Empty when no time was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedulefire",
            name="event_end",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="When it stopped holding, at this version. Exclusive. Equal to `event_start` for an exact moment; empty when no end was derived.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedulefire",
            name="event_precision",
            field=models.CharField(
                blank=True,
                choices=[("year", "year"), ("month", "month"), ("day", "day"), ("second", "second")],
                editable=False,
                help_text="How exact the source value was at this version: year, month, day or second. Coarser than second means the stored pair is the interval the unit covers.",
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="historicalschedulefire",
            name="event_start",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                editable=False,
                help_text="When the thing happened, or began to hold, at this version. Inclusive. Empty when no time was derived.",
                null=True,
            ),
        ),
    ]
