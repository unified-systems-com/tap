"""TAP API schemas — ModelSchema outputs (stay in sync with models), hand-written inputs."""

import uuid
from typing import Any

from ninja import ModelSchema, Schema
from pydantic import Field, field_validator

from tap_grid.models import Edge, Entity, EntityType

# --- Common ---


class ErrorOut(Schema):
    """Error response."""

    detail: str


# --- Entity ---


class EntityIn(Schema):
    """Create an entity."""

    entity_type: str
    name: str = ""


class EntityUpdate(Schema):
    """Partial update. All fields optional — omitted means untouched, but an
    EXPLICIT null is rejected (422): both columns are non-nullable, so letting
    null through surfaces as an IntegrityError 500 at save time (found by the
    authenticated api-fuzz pass). Validators do not run for defaulted (absent)
    fields, so this only fires on nulls the caller actually sent."""

    name: str | None = None
    entity_type: str | None = None

    @field_validator("name", "entity_type")
    @classmethod
    def _reject_explicit_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("may be omitted, but not null (the field is non-nullable)")
        return value


class EntityOut(ModelSchema):
    class Meta:
        model = Entity
        fields = ["id", "entity_type", "name", "originating_grid_id", "created_at", "updated_at"]


# --- Edge ---


class EdgeIn(Schema):
    """Create an edge."""

    from_entity_id: uuid.UUID
    to_entity_id: uuid.UUID
    edge_type: str
    name: str = ""
    properties: dict[str, Any] = {}
    # What the change is (req-grid-service-batch-label-required): the request mints
    # its own batch, and a minted batch must be named and described. Required, so a
    # request without them is refused before anything is looked up.
    batch_name: str = Field(..., min_length=1)
    batch_description: str = Field(..., min_length=1)


class EdgeOut(ModelSchema):
    entity_id: uuid.UUID

    class Meta:
        model = Edge
        fields = ["id", "from_entity", "to_entity", "edge_type", "properties"]


# --- EntityType ---


class EntityTypeOut(ModelSchema):
    class Meta:
        model = EntityType
        fields = ["id", "slug", "name", "icon", "description", "plugin_name", "kind"]
