from django.db import migrations, models


class Migration(migrations.Migration):
    """Where the spine natural-key sync records each type's recipe fingerprint (req-grid-entity-natural-key-25)."""

    dependencies = [
        ("tap_grid", "0008_entity_natural_key_published"),
    ]

    operations = [
        migrations.CreateModel(
            name="NaturalKeyRecipe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("entity_type", models.CharField(max_length=255, unique=True)),
                ("fingerprint", models.CharField(max_length=64)),
                ("synced_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "tap_natural_key_recipe",
            },
        ),
    ]
