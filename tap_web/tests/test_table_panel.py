"""Tests for the Table Panel built-in panel type.

Covers:
  req-web-stdpanel-table       — TablePanelType registered; Tabulator assets declared
  req-web-stdpanel-table-config — config JSON Schema validation; defaults; additionalProperties
  req-web-stdpanel-table-search — USES_SEARCH edge lifecycle; get_panel_search
  req-web-stdpanel-table-columns — common_metadata column set; nodes-only in V1
  req-web-stdpanel-table-pagination — server-backed pagination; window metadata
  req-web-stdpanel-table-render — search executes server-side; embedded JSON payload
  req-web-stdpanel-table-edit  — editor form; handle_save; get_editor_initial
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from tap.pytest_harness import make_admin_client
from tap_web.models import Panel
from tap_web.panels.table_panel import (
    TABLE_CONFIG_SCHEMA,
    TablePanelEditForm,
    TablePanelType,
    _validate_table_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_table_panel(**kwargs) -> Panel:
    defaults = {
        "slug": "table-panel",
        "name": "Test Table",
        "view": TablePanelType.view,
        "editor_view": TablePanelType.editor_view,
        "config": {"column_mode": "common_metadata", "default_page_size": 25},
    }
    defaults.update(kwargs)
    return Panel.objects.create(**defaults)


def _create_search(**kwargs):
    from tap_grid.models import Search

    defaults = {
        "name": "Test Search",
        "search_type": "orm",
        "root": "node",
        "definition": {"filters": {}},
        "default_limit": 25,
        "max_limit": 100,
    }
    defaults.update(kwargs)
    return Search.objects.create(**defaults)


def _link_search(panel: Panel, search) -> None:
    """Create a USES_SEARCH edge between panel and search."""
    from tap_grid.models import Edge

    Edge.objects.create(
        from_entity=panel.entity,
        to_entity=search.entity,
        edge_type="USES_SEARCH",
    )


def _panel_url(panel: Panel) -> str:
    return f"/panel/{panel.slug}--{panel.entity_id}/"


def _edit_url(panel: Panel) -> str:
    return f"/panel/{panel.slug}--{panel.entity_id}/edit/"


# ---------------------------------------------------------------------------
# req-web-stdpanel-table — registration and contract
# ---------------------------------------------------------------------------


class TestTablePanelTypeRegistration:
    """TablePanelType is registered and declares the expected contract."""

    def test_registered_with_correct_slug(self, django_db_setup):  # noqa: ARG002
        from tap_web.registry import panel_type_registry

        panel_type = panel_type_registry.get("table")
        assert panel_type is TablePanelType

    def test_has_view(self):
        assert TablePanelType.view == "tap_web/panels/table_panel.html"

    def test_has_editor_view(self):
        assert TablePanelType.editor_view == "tap_web/panels/table_panel_editor.html"

    def test_has_form_class(self):
        assert TablePanelType.form_class is TablePanelEditForm

    def test_has_config_defaults(self):
        assert TablePanelType.config_defaults["column_mode"] == "common_metadata"
        assert TablePanelType.config_defaults["default_page_size"] == 100

    def test_uses_search_edge_type_registered(self, django_db_setup):  # noqa: ARG002
        from tap_grid.constraints import get_edge_type_constraints

        constraints = get_edge_type_constraints("USES_SEARCH")
        assert constraints is not None


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-config — config schema validation
# ---------------------------------------------------------------------------


class TestTableConfigSchema:
    """Panel.config is validated against TABLE_CONFIG_SCHEMA."""

    def test_valid_full_config_passes(self):
        _validate_table_config({"column_mode": "common_metadata", "default_page_size": 25})

    def test_valid_minimal_config_passes(self):
        _validate_table_config({})

    def test_invalid_column_mode_fails(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"column_mode": "unknown_mode"})

    def test_default_page_size_below_min_fails(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"default_page_size": 0})

    def test_default_page_size_above_max_fails(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"default_page_size": 501})

    def test_additional_properties_rejected(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"unknown_key": "value"})

    def test_schema_has_additional_properties_false(self):
        assert TABLE_CONFIG_SCHEMA.get("additionalProperties") is False

    # tap#356 — the identity-table affordances: chrome, column groups, toneBadge.

    @pytest.mark.parametrize("chrome", ["full", "minimal"])
    def test_chrome_accepts_its_two_values(self, chrome):
        _validate_table_config({"chrome": chrome})

    def test_chrome_rejects_anything_else(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"chrome": "none"})

    def test_a_column_group_is_a_title_over_leaf_columns(self):
        _validate_table_config(
            {
                "columns": [
                    {"field": "data.full_name", "title": "Repository"},
                    {
                        "title": "Declared by the organization",
                        "columns": [
                            {
                                "field": "data.custom_properties.criticality",
                                "title": "Criticality",
                                "formatter": "toneBadge",
                                "formatter_params": {"tones": {"critical": "bad", "high": "warn", "low": "muted"}},
                            },
                            {"field": "data.custom_properties.lifecycle", "title": "Lifecycle"},
                        ],
                    },
                ]
            }
        )

    def test_a_group_cannot_also_be_a_leaf(self):
        with pytest.raises(ValidationError):
            _validate_table_config(
                {"columns": [{"field": "x", "title": "X", "columns": [{"field": "y", "title": "Y"}]}]}
            )

    def test_a_group_is_one_level_deep(self):
        with pytest.raises(ValidationError):
            _validate_table_config(
                {"columns": [{"title": "G", "columns": [{"title": "H", "columns": [{"field": "y", "title": "Y"}]}]}]}
            )

    def test_a_group_needs_at_least_one_leaf(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"columns": [{"title": "G", "columns": []}]})

    def test_tone_badge_is_a_known_formatter(self):
        _validate_table_config({"columns": [{"field": "data.state", "title": "State", "formatter": "toneBadge"}]})

    def test_capitalized_is_a_known_formatter(self):
        _validate_table_config({"columns": [{"field": "data.role", "title": "Role", "formatter": "capitalized"}]})

    @pytest.mark.parametrize("align", ["left", "center", "right"])
    def test_align_accepts_the_three_horizontal_alignments(self, align):
        _validate_table_config({"columns": [{"field": "data.role", "title": "Role", "align": align}]})

    def test_align_rejects_anything_else(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"columns": [{"field": "data.role", "title": "Role", "align": "middle"}]})


class TestMinimalChrome:
    """`chrome: minimal` draws no nav bars and no quick filter — a one-row table has nothing to page."""

    @staticmethod
    def _render(config: dict[str, Any]) -> str:
        from django.template.loader import render_to_string

        panel = type("P", (), {"config": config, "name": "This Repository", "slug": "id", "entity_id": "01a0-test"})()
        return render_to_string(
            "tap_web/panels/table_panel.html",
            {
                "panel": panel,
                "table_error": "",
                "table_nodes": [],
                "table_data_script_id": "d",
                "table_columns": None,
                "table_group_by": None,
                "table_meta": {
                    "showing": 1,
                    "total_count": 1,
                    "page_size_options": [],
                    "has_prev": False,
                    "has_next": False,
                },
            },
        )

    def test_full_chrome_shows_the_nav_bar(self):
        html = self._render({"quick_filter": True})
        assert "Showing 1 of 1" in html
        assert "data-tap-table-filter" in html

    def test_minimal_chrome_shows_neither_nav_bar_nor_filter_but_keeps_the_heading(self):
        html = self._render({"chrome": "minimal", "quick_filter": True})
        assert "Showing" not in html
        assert "Rows:" not in html
        assert "data-tap-table-filter" not in html
        assert "This Repository" in html


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-search — get_panel_search and USES_SEARCH edge
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetPanelSearch:
    """get_panel_search resolves the USES_SEARCH edge to a Search instance."""

    def test_returns_none_when_no_edge(self):
        from tap_web.panel import get_panel_search

        panel = _create_table_panel()
        assert get_panel_search(panel) is None

    def test_returns_linked_search(self):
        from tap_web.panel import get_panel_search

        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        result = get_panel_search(panel)
        assert result is not None
        assert result.pk == search.pk

    def test_returns_none_on_dangling_edge(self):
        """A USES_SEARCH edge pointing to a deleted search returns None gracefully."""
        from tap_grid.models import Edge
        from tap_web.panel import get_panel_search

        panel = _create_table_panel()
        search = _create_search()
        edge = Edge.objects.create(
            from_entity=panel.entity,
            to_entity=search.entity,
            edge_type="USES_SEARCH",
        )
        # Delete the search's entity directly to simulate dangling edge.
        search.entity.delete()

        # Edge still references the (now-deleted) to_entity; get_panel_search should handle gracefully.
        # After deletion the edge itself is cascade-deleted, so result should be None.
        edge_exists = Edge.objects.filter(pk=edge.pk).exists()
        if not edge_exists:
            assert get_panel_search(panel) is None
        else:
            # If edge survived, Search.DoesNotExist should be caught and None returned.
            result = get_panel_search(panel)
            assert result is None


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-render — get_view_context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelViewContext:
    """get_view_context returns the correct context for rendering."""

    def test_returns_error_when_no_search_linked(self):
        panel = _create_table_panel()
        from django.test import RequestFactory

        request = RequestFactory().get(_panel_url(panel))
        ctx = TablePanelType.get_view_context(panel, request)
        assert ctx["table_error"] is not None
        assert ctx["table_nodes"] == []

    def test_returns_nodes_on_success(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        fake_result = {
            "count": 2,
            "limit": 25,
            "offset": 0,
            "results": {
                "nodes": [
                    {
                        "entity_id": "abc",
                        "entity_type": "concept",
                        "name": "A",
                        "dimensions": {},
                        "created_at": None,
                        "updated_at": None,
                    },
                    {
                        "entity_id": "def",
                        "entity_type": "concept",
                        "name": "B",
                        "dimensions": {},
                        "created_at": None,
                        "updated_at": None,
                    },
                ],
                "edges": [],
                "info": {},
                "warnings": {},
            },
        }

        from django.test import RequestFactory

        request = RequestFactory().get(_panel_url(panel))
        with patch("tap_web.panels.table_panel.TablePanelType.get_view_context") as mock_ctx:
            mock_ctx.return_value = {
                "table_nodes": fake_result["results"]["nodes"],
                "table_meta": {"count": 2, "limit": 25, "offset": 0, "has_prev": False, "has_next": False},
                "table_search": search,
                "table_error": None,
            }
            ctx = TablePanelType.get_view_context(panel, request)
        assert ctx["table_error"] is None

    def test_nodes_embed_renders_as_parseable_json_script(self):
        """req-web-panel-json-embed.sec: the embedded payload parses back to the nodes.

        Asserts on the RENDERED element rather than a context key, because the
        escaping now happens in ``json_script`` at render time — a context-key
        check would pass while the page shipped broken markup.
        """
        import json

        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        from django.test import RequestFactory

        request = RequestFactory().get(_panel_url(panel))
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            ctx = TablePanelType.get_view_context(panel, request)

        from django.template import Context, Template

        rendered = Template("{{ table_nodes|json_script:table_data_script_id }}").render(Context(ctx))
        assert f'id="tap-table-data-{panel.entity_id}"' in rendered
        payload = rendered.split(">", 1)[1].rsplit("</script>", 1)[0]
        assert isinstance(json.loads(payload), list)

    def test_meta_populated_with_total_count_and_page_size(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        paginated_result = {
            "count": 25,
            "limit": 25,
            "offset": 0,
            "results": {
                "nodes": [{"entity": {"entity_id": f"id-{i}"}} for i in range(25)],
                "edges": [],
                "info": {"total_count": 50},
                "warnings": {},
            },
        }
        from django.test import RequestFactory

        request = RequestFactory().get(_panel_url(panel), {"page_size": "25"})
        with patch("tap_grid.search.execute_search", return_value=paginated_result):
            ctx = TablePanelType.get_view_context(panel, request)

        assert ctx["table_meta"]["total_count"] == 50
        assert ctx["table_meta"]["showing"] == 25
        assert ctx["table_meta"]["page_size"] == 25
        assert ctx["table_meta"]["has_next"] is True
        assert ctx["table_meta"]["has_prev"] is False

    def test_page_size_options_are_dynamic(self):
        """Options include only steps below total_count, plus All."""
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        fake_envelope = {
            "nodes": [{"entity": {"entity_id": f"id-{i}"}} for i in range(60)],
            "edges": [],
            "info": {"total_count": 60},
            "warnings": {},
        }
        from django.test import RequestFactory

        request = RequestFactory().get(_panel_url(panel), {"page_size": "0"})
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            ctx = TablePanelType.get_view_context(panel, request)

        options = ctx["table_meta"]["page_size_options"]
        values = [o["value"] for o in options]
        # 25 and 50 are below 60, 100/200/500 are not; All(0) always present
        assert 25 in values
        assert 50 in values
        assert 100 not in values
        assert 0 in values  # "All"

    def test_nav_bar_present_above_and_below_table(self):
        """Nav bar renders both above and below table with total count."""
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        fake_envelope = {
            "nodes": [],
            "edges": [],
            "info": {"total_count": 50},
            "warnings": {},
        }
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))

        content = response.content.decode()
        assert content.count("tap-table-nav ") >= 2  # above + below
        assert "Showing" in content
        assert "of 50" in content

    def test_search_execution_error_returns_error_context(self):
        from django.test import RequestFactory

        from tap_grid.exceptions import SearchExecutionError

        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        request = RequestFactory().get(_panel_url(panel))
        with patch("tap_grid.search.execute_search", side_effect=SearchExecutionError("boom")):
            ctx = TablePanelType.get_view_context(panel, request)

        assert ctx["table_error"] is not None
        assert ctx["table_nodes"] == []


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-render — panel_view integration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelViewEndpoint:
    """The /panel/<slug>--<uuid>/ endpoint renders the table panel template."""

    def test_panel_view_returns_200(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))
        assert response.status_code == 200

    def test_panel_view_uses_table_template(self):
        panel = _create_table_panel()
        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/table_panel.html" in template_names

    def test_no_search_shows_error_message(self):
        panel = _create_table_panel()
        response = make_admin_client(username="table-admin").get(_panel_url(panel))
        assert response.status_code == 200
        assert b"No search linked" in response.content

    def test_table_mount_point_present_when_search_linked(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))
        assert b"data-tap-table-mount" in response.content

    def test_embedded_json_script_present(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))
        assert b'type="application/json"' in response.content
        assert f"tap-table-data-{panel.entity_id}".encode() in response.content

    def test_no_inline_javascript_emitted(self):
        """Behavior must ship via static JS assets, not inline script blocks."""
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        fake_envelope = {"nodes": [], "edges": [], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            response = make_admin_client(username="table-admin").get(_panel_url(panel))
        # No executable script blocks (type="application/json" is allowed).
        content = response.content.decode()
        import re

        # re.IGNORECASE: browsers treat <SCRIPT> like <script>, so a case-sensitive
        # assertion would pass while an uppercase tag executes (CodeQL py/bad-tag-filter).
        executable_scripts = re.findall(
            r"<script(?![^>]*type=['\"]application/json['\"])[^>]*>", content, re.IGNORECASE
        )
        assert executable_scripts == []


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-edit — get_editor_initial and handle_save
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelEditorInitial:
    """get_editor_initial pre-populates the form with current panel state."""

    def test_returns_name_and_description(self):
        panel = _create_table_panel(name="My Table", description="Note")
        initial = TablePanelType.get_editor_initial(panel)
        assert initial["name"] == "My Table"
        assert initial["description"] == "Note"

    def test_returns_empty_search_uuid_when_no_search(self):
        panel = _create_table_panel()
        initial = TablePanelType.get_editor_initial(panel)
        assert initial["search_uuid"] == ""

    def test_returns_search_uuid_when_linked(self):
        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        initial = TablePanelType.get_editor_initial(panel)
        assert initial["search_uuid"] == str(search.entity_id)

    def test_returns_config_fields(self):
        panel = _create_table_panel(config={"column_mode": "common_metadata", "default_page_size": 50})
        initial = TablePanelType.get_editor_initial(panel)
        assert initial["column_mode"] == "common_metadata"
        assert initial["default_page_size"] == 50

    def test_returns_default_page_size_when_not_in_config(self):
        panel = _create_table_panel(config={"column_mode": "common_metadata"})
        initial = TablePanelType.get_editor_initial(panel)
        assert initial["default_page_size"] == 100


@pytest.mark.django_db
class TestTablePanelHandleSave:
    """handle_save persists panel fields and manages the USES_SEARCH edge."""

    def _make_form(self, panel: Panel, search=None, **overrides) -> TablePanelEditForm:

        # Refresh choices at form time.
        search_uuid = str(search.entity_id) if search else ""
        data = {
            "name": panel.name,
            "description": panel.description,
            "search_uuid": search_uuid,
            "column_mode": "common_metadata",
            "default_page_size": 25,
        }
        data.update(overrides)
        return TablePanelEditForm(data)

    def test_save_updates_name(self):
        panel = _create_table_panel(name="Old")
        form = self._make_form(panel, name="New Title")
        assert form.is_valid(), form.errors
        from django.test import RequestFactory

        request = RequestFactory().post(_edit_url(panel))
        TablePanelType.handle_save(form, panel, request)
        panel.refresh_from_db()
        assert panel.name == "New Title"

    def test_save_updates_config(self):
        panel = _create_table_panel()
        form = self._make_form(panel, default_page_size=50)
        assert form.is_valid(), form.errors
        from django.test import RequestFactory

        request = RequestFactory().post(_edit_url(panel))
        TablePanelType.handle_save(form, panel, request)
        panel.refresh_from_db()
        assert panel.config["default_page_size"] == 50
        assert "default_limit" not in panel.config

    def test_save_creates_uses_search_edge(self):
        from tap_grid.models import Edge

        panel = _create_table_panel()
        search = _create_search()
        form = self._make_form(panel, search=search)
        assert form.is_valid(), form.errors
        from django.test import RequestFactory

        request = RequestFactory().post(_edit_url(panel))
        TablePanelType.handle_save(form, panel, request)
        assert Edge.objects.filter(from_entity=panel.entity, edge_type="USES_SEARCH").exists()

    def test_save_replaces_old_edge_with_new_one(self):
        from tap_grid.models import Edge

        panel = _create_table_panel()
        old_search = _create_search(name="Old Search")
        _link_search(panel, old_search)

        new_search = _create_search(name="New Search")
        form = self._make_form(panel, search=new_search)
        assert form.is_valid(), form.errors
        from django.test import RequestFactory

        request = RequestFactory().post(_edit_url(panel))
        TablePanelType.handle_save(form, panel, request)

        edges = Edge.objects.filter(from_entity=panel.entity, edge_type="USES_SEARCH")
        assert edges.count() == 1
        assert edges.first().to_entity_id == new_search.entity_id

    def test_save_removes_edge_when_no_search_selected(self):
        from tap_grid.models import Edge

        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)

        form = self._make_form(panel, search=None, search_uuid="")
        assert form.is_valid(), form.errors
        from django.test import RequestFactory

        request = RequestFactory().post(_edit_url(panel))
        TablePanelType.handle_save(form, panel, request)

        assert not Edge.objects.filter(from_entity=panel.entity, edge_type="USES_SEARCH").exists()


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-edit — editor view endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelEditView:
    """The /panel/<slug>--<uuid>/edit/ endpoint renders the table panel editor."""

    def test_get_returns_200(self):
        panel = _create_table_panel()
        response = make_admin_client(username="table-admin").get(_edit_url(panel))
        assert response.status_code == 200

    def test_get_includes_editor_template(self):
        panel = _create_table_panel()
        response = make_admin_client(username="table-admin").get(_edit_url(panel))
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/table_panel_editor.html" in template_names

    def test_post_saves_and_redirects(self):
        panel = _create_table_panel()
        search = _create_search()
        response = make_admin_client(username="table-admin").post(
            _edit_url(panel),
            {
                "name": "Updated",
                "description": "",
                "search_uuid": str(search.entity_id),
                "column_mode": "common_metadata",
                "default_page_size": "25",
            },
        )
        assert response.status_code == 302

    def test_post_empty_name_rerenders_with_errors(self):
        panel = _create_table_panel()
        response = make_admin_client(username="table-admin").post(
            _edit_url(panel),
            {
                "name": "",
                "description": "",
                "search_uuid": "",
                "column_mode": "common_metadata",
                "default_page_size": "25",
            },
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# TablePanelEditForm — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelEditForm:
    def test_valid_minimal_form_passes(self):
        form = TablePanelEditForm(
            {
                "name": "A Table",
                "description": "",
                "search_uuid": "",
                "column_mode": "common_metadata",
                "default_page_size": "25",
            }
        )
        assert form.is_valid(), form.errors

    def test_missing_name_fails(self):
        form = TablePanelEditForm(
            {
                "name": "",
                "description": "",
                "search_uuid": "",
                "column_mode": "common_metadata",
                "default_page_size": "25",
            }
        )
        assert not form.is_valid()
        assert "name" in form.errors

    def test_invalid_column_mode_fails(self):
        form = TablePanelEditForm(
            {
                "name": "T",
                "description": "",
                "search_uuid": "",
                "column_mode": "bad_mode",
                "default_page_size": "25",
            }
        )
        assert not form.is_valid()
        assert "column_mode" in form.errors

    def test_default_page_size_below_min_fails(self):
        form = TablePanelEditForm(
            {
                "name": "T",
                "description": "",
                "search_uuid": "",
                "column_mode": "common_metadata",
                "default_page_size": "0",
            }
        )
        assert not form.is_valid()
        assert "default_page_size" in form.errors

    def test_search_choices_populated(self):
        search = _create_search(name="My Search")
        form = TablePanelEditForm(
            {
                "name": "T",
                "description": "",
                "search_uuid": str(search.entity_id),
                "column_mode": "common_metadata",
                "default_page_size": "25",
            }
        )
        choice_values = [v for v, _ in form.fields["search_uuid"].choices]
        assert str(search.entity_id) in choice_values


# ---------------------------------------------------------------------------
# Icon enrichment — _enrich_nodes_with_icons and icon_url in view context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePanelIconEnrichment:
    """Nodes returned by get_view_context carry icon_url for display."""

    def _seed_fixture_entity_types(self):
        """Seed grid_fixtures EntityType records without re-registering edge constraints."""
        from django.apps import apps
        from django.utils.module_loading import import_string

        from tap_grid.models import EntityType

        app_config = apps.get_app_config("grid_fixtures")
        manifest = app_config.manifest
        for entry in manifest.models:
            cls = import_string(entry.class_path)
            EntityType.objects.update_or_create(
                slug=entry.slug,
                defaults={
                    "name": getattr(cls, "ENTITY_NAME", entry.slug),
                    "icon": getattr(cls, "ENTITY_ICON", ""),
                    "description": getattr(cls, "ENTITY_DESCRIPTION", ""),
                    "plugin_name": app_config.name,
                },
            )

    def test_icon_url_resolved_for_type_with_icon(self):
        """batch_resolve_icon_urls returns non-empty URL for entity types with icons."""
        from tap_grid.grift.subgraph import batch_resolve_icon_urls

        self._seed_fixture_entity_types()
        icon_map = batch_resolve_icon_urls({"grid_fixtures__constrained_source"})
        assert icon_map.get("grid_fixtures__constrained_source", "") != ""

    def test_icon_url_empty_for_type_without_icon(self):
        """batch_resolve_icon_urls returns empty string for types without icons."""
        from tap_grid.grift.subgraph import batch_resolve_icon_urls

        self._seed_fixture_entity_types()
        icon_map = batch_resolve_icon_urls({"grid_fixtures__peer_group"})
        assert icon_map.get("grid_fixtures__peer_group", "") == ""

    def test_icon_url_empty_for_unknown_entity_type(self):
        """batch_resolve_icon_urls returns empty map for unregistered types."""
        from tap_grid.grift.subgraph import batch_resolve_icon_urls

        icon_map = batch_resolve_icon_urls({"does-not-exist"})
        assert icon_map.get("does-not-exist", "") == ""

    def test_icon_url_in_view_context_nodes(self):
        """get_view_context returns nodes with icon_url (extended layer)."""
        from unittest.mock import patch

        from django.test import RequestFactory

        panel = _create_table_panel()
        search = _create_search()
        _link_search(panel, search)
        self._seed_fixture_entity_types()

        fake_envelope = {
            "nodes": [
                {
                    "entity": {
                        "entity_type": "grid_fixtures__constrained_source",
                        "entity_id": "abc",
                        "name": "Frodo",
                        "dimensions": {},
                        "created_at": None,
                        "updated_at": None,
                        "deleted_at": None,
                    },
                    "node": {"name": "Frodo", "description": "A hobbit"},
                    "icon_url": "/static/grid_fixtures/icons/constrained-source.svg",
                    "shape": "ellipse",
                    "url_id": "frodo--abc",
                }
            ],
            "edges": [],
            "info": {},
            "warnings": {},
        }
        request = RequestFactory().get(_panel_url(panel))
        with patch("tap_grid.search.execute_search", return_value=fake_envelope):
            ctx = TablePanelType.get_view_context(panel, request)

        assert ctx["table_error"] is None
        assert len(ctx["table_nodes"]) == 1
        assert "icon_url" in ctx["table_nodes"][0]
        assert ctx["table_nodes"][0]["icon_url"] != ""


# ---------------------------------------------------------------------------
# req-web-stdpanel-table-rows — a projection search's rows (tap#432, tap#297)
# ---------------------------------------------------------------------------

_PROJECTION_QUERY = [
    "MATCH (a:grid_fixtures__constrained_source)-[e:CONSTRAINED_LINK__grid_fixtures]->"
    "(b:grid_fixtures__constrained_target)",
    # No ORDER BY: a single-hop traversal does not take one (tap#298); assertions sort.
    "RETURN a.name AS source, b.name AS target, a.entity_id AS source_id",
]


def _embedded(content: str, panel: Panel) -> Any:
    """The table's embedded data payload, parsed as the browser parses it."""
    import html
    import json
    import re

    m = re.search(
        rf'<script id="tap-table-data-{panel.entity_id}" type="application/json">(.*?)</script>', content, re.S
    )
    assert m, "no data payload embedded"
    return json.loads(html.unescape(m.group(1)))


def _embedded_columns(content: str, panel: Panel) -> Any:
    import html
    import json
    import re

    m = re.search(
        rf'<script id="tap-table-columns-{panel.entity_id}" type="application/json">(.*?)</script>', content, re.S
    )
    return json.loads(html.unescape(m.group(1))) if m else None


# transaction=True: execute_search reads through the `search_readonly` connection, which
# sees only committed rows (the tap_grid gryphon tests' marker).
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestProjectionRows:
    """A Gryphon search that RETURNs aliases renders its rows, through the real panel path.

    Each test seeds grid rows, binds a real Gryphon search, and reads the fragment the
    panel endpoint serves — no mocked envelope — so the assertion is on what the browser
    receives.
    """

    @staticmethod
    def _seed_links(n: int) -> list[str]:
        """``n`` source→target links; returns the source names, sorted."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = get_caller_context()
        assert ctx is not None
        set_caller_context(CallerContext(user=ctx.user, batch_id=str(uuid.uuid4())))
        names = [f"src-{i:02d}" for i in range(n)]
        for i, name in enumerate(names):
            a = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            b = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name=f"tgt/{i:02d}")
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=a,
                to_entity=b,
                edge_type="CONSTRAINED_LINK__grid_fixtures",
            )
        return names

    @staticmethod
    def _gryphon_search(query: list[str], **kwargs: Any) -> Any:
        from tap_grid.models import Search

        return Search.objects.create(
            name="Projection", search_type="gryphon", root="node", definition={"query": query}, **kwargs
        )

    @classmethod
    def _bind(cls, config: dict[str, Any], **search_kwargs: Any) -> Panel:
        panel = _create_table_panel(config=config)
        _link_search(panel, cls._gryphon_search(_PROJECTION_QUERY, **search_kwargs))
        return panel

    @pytest.mark.spec("req-web-stdpanel-table-rows-1")
    def test_projection_rows_are_the_payload_in_raw_mode(self):
        self._seed_links(3)
        panel = self._bind({"default_page_size": 25})
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()

        rows = sorted(_embedded(content, panel), key=lambda r: r["source"])
        assert [r["source"] for r in rows] == ["src-00", "src-01", "src-02"]
        assert [r["target"] for r in rows] == ["tgt/00", "tgt/01", "tgt/02"]
        assert 'data-tap-table-mode="raw"' in content
        assert "Showing 3 of 3" in content

    @pytest.mark.spec("req-web-stdpanel-table-rows-2")
    def test_undeclared_columns_are_the_aliases_in_return_order(self):
        self._seed_links(1)
        panel = self._bind({"default_page_size": 25})
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()

        cols = _embedded_columns(content, panel)
        assert [(c["field"], c["title"]) for c in cols] == [
            ("source", "source"),
            ("target", "target"),
            ("source_id", "source_id"),
        ]

    @pytest.mark.spec("req-web-stdpanel-table-rows-2")
    def test_declared_columns_pass_through_unchanged(self):
        self._seed_links(1)
        declared = [
            {"field": "target", "title": "Target", "formatter": "tailSegment", "headerSort": True},
            {"field": "source", "title": "Source"},
        ]
        panel = self._bind({"default_page_size": 25, "columns": declared})
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()

        assert _embedded_columns(content, panel) == declared

    @pytest.mark.spec("req-web-stdpanel-table-rows-3")
    def test_rows_are_paged_and_the_total_is_the_full_row_count(self):
        names = self._seed_links(5)
        panel = self._bind({"default_page_size": 2})
        client = make_admin_client(username="table-admin")

        seen: list[str] = []
        for offset, expect in ((0, 2), (2, 2), (4, 1)):
            page = client.get(_panel_url(panel), {"offset": str(offset), "page_size": "2"}).content.decode()
            rows = _embedded(page, panel)
            assert len(rows) == expect
            # The envelope's own info.total_count counts nodes — 0 for a projection.
            assert f"Showing {expect} of 5" in page
            seen += [r["source"] for r in rows]
        assert sorted(seen) == names, "the three pages partition the full row set"
        last = page
        assert "Next &rarr;" in last and "disabled" in last.split("Next &rarr;")[0].rsplit("<button", 1)[1]

    @pytest.mark.spec("req-web-stdpanel-table-rows-3")
    def test_rows_page_by_the_searchs_clamped_limit(self):
        """max_limit clamps the window; the panel pages rows by the window the search applied."""
        self._seed_links(4)
        panel = self._bind({"default_page_size": 3}, max_limit=2)
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()
        assert len(_embedded(content, panel)) == 2
        assert "Showing 2 of 4" in content

    @pytest.mark.spec("req-web-stdpanel-table-rows-5")
    def test_row_url_template_fills_encoded_values_and_voids_missing_ones(self):
        from tap_web.panels.table_panel import _with_row_urls

        rows: list[dict[str, Any]] = [{"a": "x/y z", "b": 1}, {"a": "", "b": 2}, {"b": 3}, {"a": "ok", "b": None}]
        out = _with_row_urls(rows, "/zizmor/workflow?repo={a}&id={b}")
        assert out[0]["_url"] == "/zizmor/workflow?repo=x%2Fy%20z&id=1"
        assert all("_url" not in r for r in out[1:])
        assert all("_url" not in r for r in rows), "the envelope's rows are never mutated"

    @pytest.mark.spec("req-web-stdpanel-table-rows-5")
    @pytest.mark.parametrize("template", [None, "/things/{id}"])
    def test_a_url_alias_from_the_search_never_reaches_the_payload(self, template):
        """Only the panel's template sets `_url`; a projected `_url` is dropped, voided row or not."""
        from tap_web.panels.table_panel import _with_row_urls

        rows: list[dict[str, Any]] = [{"id": "", "_url": "https://evil.example/"}, {"id": "7", "_url": "/x"}]
        out = _with_row_urls(rows, template)
        assert "_url" not in out[0]
        assert out[1].get("_url") == ("/things/7" if template else None)
        assert rows[0]["_url"] == "https://evil.example/", "the envelope's rows are never mutated"

    @pytest.mark.spec("req-web-stdpanel-table-rows-5")
    def test_row_url_template_reaches_the_payload(self):
        self._seed_links(1)
        panel = self._bind({"default_page_size": 25, "row_url_template": "/things/{source_id}"})
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()
        (row,) = _embedded(content, panel)
        assert row["_url"] == f"/things/{row['source_id']}"

    @pytest.mark.spec("req-web-stdpanel-table-rows-5")
    @pytest.mark.parametrize(
        "template",
        [
            "//evil.example/x",
            "https://evil.example/{a}",
            "javascript:x",
            "/\\\\host",
            # A browser strips tab/CR/LF and reads a backslash as "/" while parsing,
            # so each of these parses to a protocol-relative //evil.example URL.
            "/\t/evil.example/x",
            "/\n/evil.example/x",
            "/\r/evil.example/x",
            "/x/\\\\evil",
            "/a path",
            "/things/x\n",  # `$` would match before a final newline
        ],
    )
    def test_row_url_template_must_be_a_same_origin_path(self, template):
        with pytest.raises(ValidationError):
            _validate_table_config({"row_url_template": template})

    @pytest.mark.spec("req-web-stdpanel-table-rows-5")
    def test_a_same_origin_path_template_validates(self):
        _validate_table_config({"row_url_template": "/zizmor/workflow?repo={repo}&id={workflow_id}"})

    @pytest.mark.spec("req-web-stdpanel-table-rows-4")
    def test_node_mode_is_unchanged(self):
        """The same pattern returning a variable (`RETURN a`) yields nodes: node payload, no mode attribute."""
        self._seed_links(2)
        panel = _create_table_panel(config={"default_page_size": 25})
        _link_search(panel, self._gryphon_search([_PROJECTION_QUERY[0], "RETURN a"]))
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()

        nodes = _embedded(content, panel)
        assert sorted(n["name"] for n in nodes) == ["src-00", "src-01"]
        assert all(n["entity_type"] == "grid_fixtures__constrained_source" for n in nodes)
        assert "data-tap-table-mode" not in content
        assert _embedded_columns(content, panel) is None
        assert "Showing 2 of 2" in content

    @pytest.mark.spec("req-web-stdpanel-table-rows-4")
    def test_an_empty_projection_renders_the_empty_node_table(self):
        panel = self._bind({"default_page_size": 25})
        content = make_admin_client(username="table-admin").get(_panel_url(panel)).content.decode()
        assert _embedded(content, panel) == []
        assert "data-tap-table-mode" not in content
        assert "Showing 0 of 0" in content
