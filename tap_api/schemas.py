"""TAP API schemas — ModelSchema outputs (stay in sync with models), hand-written inputs."""

from ninja import ModelSchema, Schema

from tap_grid.models import EntityType

# --- Common ---


class ErrorOut(Schema):
    """Error response."""

    detail: str


# --- EntityType ---


class EntityTypeOut(ModelSchema):
    class Meta:
        model = EntityType
        fields = ["id", "slug", "name", "icon", "description", "plugin_name", "kind"]
