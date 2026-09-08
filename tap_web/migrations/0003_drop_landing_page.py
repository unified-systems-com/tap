"""Drop the retired `landing_page` node type and clean its spine rows (req-web-page-landing-14).

The root URL is the operator's decision in the boot profile (tap#340,
tap_web/specs/spec-web-page.md `req-web-page-landing`); the `LandingPage`
pointer node and its `USES_LANDING_PAGE` edge no longer decide anything. This
migration removes the model and its (historical) table AND deletes the
obsolete spine rows — every `USES_LANDING_PAGE` edge with its edge entity, and
every `landing_page` entity — while leaving the target Pages untouched. Both the
upgrade path (a grid holding the old rows) and a clean boot (none) are covered
by tap_web/tests/test_landing.py.

Direct ORM access is the sanctioned path in migrations.
"""

from typing import Any

from django.db import migrations


def delete_landing_rows(apps: Any, schema_editor: Any) -> None:
    Edge = apps.get_model("tap_grid", "Edge")
    Entity = apps.get_model("tap_grid", "Entity")
    LandingPage = apps.get_model("tap_web", "LandingPage")

    # Edge rows cascade off the landing entity, but each edge's OWN spine row
    # (entity_type="edge") would be orphaned — delete those explicitly first.
    edge_entity_ids = list(Edge.objects.filter(edge_type="USES_LANDING_PAGE").values_list("entity_id", flat=True))
    Edge.objects.filter(edge_type="USES_LANDING_PAGE").delete()
    Entity.objects.filter(pk__in=edge_entity_ids).delete()

    LandingPage.objects.all().delete()
    Entity.objects.filter(entity_type="landing_page").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tap_web", "0002_strip_uses_search_binding_key"),
        ("tap_grid", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(delete_landing_rows, migrations.RunPython.noop),
        migrations.DeleteModel(name="HistoricalLandingPage"),
        migrations.DeleteModel(name="LandingPage"),
    ]
