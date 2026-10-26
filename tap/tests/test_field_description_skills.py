"""The add-model and add-edge skills require a field description (req-grid-node-field-description-3).

The skills are the author-time gate: a new type is not born without descriptions because the
procedure that creates it says so in the worked example, in the rules and as a named mistake.
These tests check that the written procedure carries all three. They cannot show an agent follows it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADD_MODEL = REPO_ROOT / "tap_grid" / "skills" / "add-model" / "SKILL.md"
ADD_EDGE = REPO_ROOT / "tap_grid" / "skills" / "add-edge" / "SKILL.md"


def _mistakes(text: str) -> str:
    return text.split("## Common Mistakes", 1)[1]


@pytest.mark.spec("req-grid-node-field-description-3")
def test_add_model_has_the_description_in_its_example_its_rules_and_its_mistakes() -> None:
    text = ADD_MODEL.read_text(encoding="utf-8")
    example = text.split("FIELD_CRUD_SCHEMA: ClassVar", 1)[1].split("}", 1)[0]
    assert '"description":' in example, "the worked FIELD_CRUD_SCHEMA example must show a description"
    assert re.search(r"Every `FIELD_CRUD_SCHEMA` entry needs a `description`", text)
    assert "means in the domain" in text and "not its type" in text.lower() or "Do not restate the type" in text
    assert re.search(r"no `description`", _mistakes(text))


@pytest.mark.spec("req-grid-node-field-description-3")
def test_add_edge_has_the_description_in_its_example_its_rules_and_its_mistakes() -> None:
    text = ADD_EDGE.read_text(encoding="utf-8")
    example = text.split('"property_schema": {', 1)[1].split("default_dimensions", 1)[0]
    assert '"description":' in example, "the worked property_schema example must show a description"
    assert re.search(r"Every `property_schema` property carries a `description`", text)
    assert re.search(r"no `description`", _mistakes(text))
