"""Tests for the Text Panel built-in panel type.

Covers:
  req-web-stdpanel-base  — TextPanelType registered in panel_type_registry
  req-web-stdpanel-text  — renders title + config.text; description not rendered
  req-web-stdpanel-text-edit — Django Form editor; save/validation/sanitization
  req-web-panel-edit-form.sec  — server-side sanitization; CSRF via middleware
  req-web-panel-render-content.sec — auto-escaping; HTML in text not rendered as markup
"""

import pytest

from tap.pytest_harness import make_admin_client
from tap_web.models import Panel
from tap_web.panels.text_panel import TextPanelEditForm, TextPanelType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_text_panel(**kwargs) -> Panel:
    defaults = {
        "slug": "text-panel",
        "name": "Test Panel",
        "view": TextPanelType.view,
        "editor_view": TextPanelType.editor_view,
        "config": {"text": "Hello world"},
    }
    defaults.update(kwargs)
    return Panel.objects.create(**defaults)


def _panel_url(panel: Panel) -> str:
    return f"/panel/{panel.slug}--{panel.entity_id}/"


def _edit_url(panel: Panel) -> str:
    return f"/panel/{panel.slug}--{panel.entity_id}/edit/"


# ---------------------------------------------------------------------------
# req-web-stdpanel-base — registry
# ---------------------------------------------------------------------------


class TestTextPanelTypeRegistration:
    """TextPanelType is registered in panel_type_registry at startup."""

    def test_registered_with_correct_slug(self, django_db_setup):  # noqa: ARG002
        from tap_web.registry import panel_type_registry

        panel_type = panel_type_registry.get("text")
        assert panel_type is TextPanelType

    def test_has_view(self):
        assert TextPanelType.view == "tap_web/panels/text_panel.html"

    def test_has_editor_view(self):
        assert TextPanelType.editor_view == "tap_web/panels/text_panel_editor.html"

    def test_has_config_defaults(self):
        assert "text" in TextPanelType.config_defaults

    def test_has_form_class(self):
        assert TextPanelType.form_class is TextPanelEditForm


# ---------------------------------------------------------------------------
# req-web-stdpanel-text — rendering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTextPanelView:
    """Text Panel renders title and config.text; description is not displayed."""

    def test_panel_view_returns_200(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert response.status_code == 200

    def test_panel_view_renders_title(self):
        panel = _create_text_panel(name="My Heading")
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert b"My Heading" in response.content

    def test_panel_view_renders_body_text(self):
        panel = _create_text_panel(config={"text": "Body content here."})
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert b"Body content here." in response.content

    def test_panel_view_does_not_render_description(self):
        panel = _create_text_panel(description="Admin note only.")
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert b"Admin note only." not in response.content

    # req-web-panel-render-content.sec — HTML in text is escaped, not rendered
    def test_html_in_text_is_escaped(self):
        panel = _create_text_panel(config={"text": "<script>alert('xss')</script>"})
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert b"<script>" not in response.content
        assert b"&lt;script&gt;" in response.content

    def test_angle_brackets_in_title_escaped(self):
        panel = _create_text_panel(name="<b>Bold</b>")
        response = make_admin_client(username="textadmin").get(_panel_url(panel))
        assert b"<b>Bold</b>" not in response.content
        assert b"&lt;b&gt;" in response.content


# ---------------------------------------------------------------------------
# req-web-stdpanel-text-edit — editor form behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTextPanelEditView:
    """Text Panel editor uses Django Form; saves title/description/config.text."""

    def test_get_returns_200(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").get(_edit_url(panel))
        assert response.status_code == 200

    def test_get_uses_panel_edit_template(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").get(_edit_url(panel))
        assert "tap_web/editor.html" in [t.name for t in response.templates]

    def test_get_includes_text_panel_editor_template(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").get(_edit_url(panel))
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/text_panel_editor.html" in template_names

    def test_get_shows_current_body_text(self):
        panel = _create_text_panel(config={"text": "Current content."})
        response = make_admin_client(username="textadmin").get(_edit_url(panel))
        assert b"Current content." in response.content

    def test_post_saves_title(self):
        panel = _create_text_panel(name="Old")
        make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": "New Title", "description": "", "text": "body"}
        )
        panel.refresh_from_db()
        assert panel.name == "New Title"

    def test_post_saves_description(self):
        panel = _create_text_panel()
        make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": panel.name, "description": "Meta note.", "text": "body"}
        )
        panel.refresh_from_db()
        assert panel.description == "Meta note."

    def test_post_saves_text_to_config(self):
        panel = _create_text_panel(config={"text": "old"})
        make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": panel.name, "description": "", "text": "Updated body."}
        )
        panel.refresh_from_db()
        assert panel.config["text"] == "Updated body."

    # req-web-panel-edit-form.sec-2 — server-side sanitization via Django Form strip
    def test_post_strips_whitespace_from_title(self):
        panel = _create_text_panel()
        make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": "  Trimmed  ", "description": "", "text": "body"}
        )
        panel.refresh_from_db()
        assert panel.name == "Trimmed"

    def test_post_strips_whitespace_from_text(self):
        panel = _create_text_panel()
        make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": panel.name, "description": "", "text": "  content  "}
        )
        panel.refresh_from_db()
        assert panel.config["text"] == "content"

    def test_post_empty_title_rerenders_with_errors(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": "", "description": "", "text": "body"}
        )
        assert response.status_code == 200
        assert b"tap_web/editor.html" in bytes(str([t.name for t in response.templates]), "utf-8")

    def test_post_redirects_to_edit_page_on_success(self):
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").post(
            _edit_url(panel), {"name": "Title", "description": "", "text": "body"}
        )
        assert response.status_code == 302
        assert response["Location"] == _edit_url(panel)

    def test_generic_json_editor_not_shown_for_text_panel(self):
        # The typed editor replaces the generic JSON config editor.
        panel = _create_text_panel()
        response = make_admin_client(username="textadmin").get(_edit_url(panel))
        assert b'name="config"' not in response.content


# ---------------------------------------------------------------------------
# TextPanelEditForm — unit tests
# ---------------------------------------------------------------------------


class TestTextPanelEditForm:
    def test_valid_data_passes(self):
        form = TextPanelEditForm({"name": "A title", "description": "", "text": "body"})
        assert form.is_valid()

    def test_missing_title_fails(self):
        form = TextPanelEditForm({"name": "", "description": "", "text": "body"})
        assert not form.is_valid()
        assert "name" in form.errors

    def test_title_max_length_enforced(self):
        form = TextPanelEditForm({"name": "x" * 256, "description": "", "text": ""})
        assert not form.is_valid()
        assert "name" in form.errors

    def test_title_stripped(self):
        form = TextPanelEditForm({"name": "  hi  ", "description": "", "text": ""})
        assert form.is_valid()
        assert form.cleaned_data["name"] == "hi"

    def test_text_optional(self):
        form = TextPanelEditForm({"name": "Title", "description": "", "text": ""})
        assert form.is_valid()

    def test_text_stripped(self):
        form = TextPanelEditForm({"name": "Title", "description": "", "text": "  body  "})
        assert form.is_valid()
        assert form.cleaned_data["text"] == "body"
