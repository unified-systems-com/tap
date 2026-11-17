from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tap_auth", "0002_alter_invitation_public_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="capability",
            name="declared_by",
            field=models.CharField(
                default="tap_auth",
                help_text="Who declared this capability: 'tap_auth' for the core registry, else the slug of the "
                "plugin whose <slug>.capabilities.json declares it (req-tap-auth-plugin-declarations).",
                max_length=64,
            ),
        ),
    ]
