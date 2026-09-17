"""Tests for the synthetic page builder (tap_web/synthetic.py)."""

import pytest

from tap_web.synthetic import (
    SyntheticGraph,
    SyntheticLayout,
    SyntheticPage,
    SyntheticSearch,
    load_subgraph,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def viewer_subgraph():
    return load_subgraph("entity-viewer")


@pytest.fixture()
def editor_subgraph():
    return load_subgraph("entity-editor")


# ---------------------------------------------------------------------------
# SyntheticGraph parsing
# ---------------------------------------------------------------------------


class TestSyntheticGraphParsing:
    """Test that SyntheticGraph correctly parses GRIFT subgraphs."""

    def test_viewer_subgraph_node_count(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        assert len(graph.nodes) == 6  # 1 search + 1 layout + 3 panels + 1 page

    def test_editor_subgraph_node_count(self, editor_subgraph):
        graph = SyntheticGraph(editor_subgraph)
        assert len(graph.nodes) == 5  # 1 search + 1 layout + 2 panels + 1 page

    def test_node_types_are_correct(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        types = {type(n).__name__ for n in graph.nodes.values()}
        assert types == {"SyntheticSearch", "SyntheticLayout", "SyntheticPanel", "SyntheticPage"}

    def test_batched_format_supported(self, viewer_subgraph):
        """SyntheticGraph handles files wrapped in a batches array."""
        batched = {"batches": [{"nodes": viewer_subgraph["nodes"], "edges": viewer_subgraph["edges"]}]}
        graph = SyntheticGraph(batched)
        assert len(graph.nodes) == 6


class TestSyntheticGraphPageLookup:
    """Test page resolution from SyntheticGraph."""

    def test_get_page_returns_page(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        assert isinstance(page, SyntheticPage)
        assert page.name == "Entity Viewer"

    def test_get_page_by_slug(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page(slug="/__entity-viewer")
        assert page is not None
        assert page.slug == "/__entity-viewer"

    def test_get_page_by_wrong_slug(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        assert graph.get_page(slug="/nonexistent") is None


class TestSyntheticGraphPanelResolution:
    """Test panel resolution from page via USES_PANEL edges."""

    def test_viewer_page_has_three_panels(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        assert len(panels) == 3
        assert set(panels.keys()) == {"graph", "viewer", "flip"}

    def test_editor_page_has_two_panels(self, editor_subgraph):
        graph = SyntheticGraph(editor_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        assert len(panels) == 2
        assert set(panels.keys()) == {"graph", "editor"}

    def test_graph_panel_has_correct_view(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        assert panels["graph"].view == "tap_viz/panels/graph_panel.html"

    def test_viewer_panel_has_correct_view(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        assert panels["viewer"].view == "tap_web/panels/viewer_panel.html"


class TestSyntheticGraphCompositionChain:
    """Test Layout→Search resolution via edges."""

    def test_graph_panel_has_layout(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        layout = graph.get_layout_for_panel(panels["graph"])
        assert isinstance(layout, SyntheticLayout)
        assert layout.name == "Entity Neighborhood Layout"

    def test_layout_has_search(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        layout = graph.get_layout_for_panel(panels["graph"])
        searches = graph.get_searches_for_layout(layout)
        assert len(searches) == 1
        assert isinstance(searches[0], SyntheticSearch)
        assert searches[0].search_type == "gryphon"

    def test_viewer_panel_has_no_layout(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        assert graph.get_layout_for_panel(panels["viewer"]) is None


# ---------------------------------------------------------------------------
# SyntheticNode wrapper attributes
# ---------------------------------------------------------------------------


class TestSyntheticNodeAttributes:
    """Test that wrapper classes expose the correct attributes."""

    def test_synthetic_panel_attributes(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        panels = graph.get_panels_for_page(page)
        panel = panels["graph"]
        assert panel.entity_id == "synthetic:panel:entity-graph"
        assert panel.entity_type == "panel"
        assert panel.slug == "entity-neighborhood-graph"
        assert panel.name == "Entity Graph"
        assert panel.view == "tap_viz/panels/graph_panel.html"
        # Static assets come from the panel type (GraphPanelType), not the
        # synthetic instance.

    def test_synthetic_search_attributes(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        search = None
        for node in graph.nodes.values():
            if isinstance(node, SyntheticSearch):
                search = node
                break
        assert search is not None
        assert search.search_type == "gryphon"
        assert search.root == "node"
        assert search.default_limit == 200
        assert search.max_limit == 500
        assert "query" in search.definition

    def test_synthetic_layout_definition(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        layout = None
        for node in graph.nodes.values():
            if isinstance(node, SyntheticLayout):
                layout = node
                break
        assert layout is not None
        assert "presentation" in layout.definition
        assert layout.definition["presentation"]["placement"] == "cytoscape:cose"

    def test_synthetic_page_layout(self, viewer_subgraph):
        graph = SyntheticGraph(viewer_subgraph)
        page = graph.get_page()
        assert "columns" in page.layout
        assert "col-1" in page.layout["columns"]


# ---------------------------------------------------------------------------
# Subgraph loading
# ---------------------------------------------------------------------------


class TestLoadSubgraph:
    """Test loading GRIFT subgraph data files."""

    def test_load_viewer_subgraph(self):
        data = load_subgraph("entity-viewer")
        assert "nodes" in data
        assert "edges" in data

    def test_load_editor_subgraph(self):
        data = load_subgraph("entity-editor")
        assert "nodes" in data
        assert "edges" in data

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_subgraph("nonexistent-subgraph")

    def test_subgraph_caching(self):
        first = load_subgraph("entity-viewer")
        second = load_subgraph("entity-viewer")
        assert first is second


# ---------------------------------------------------------------------------
# Integration: render_synthetic_page
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestRenderSyntheticPage:
    """Integration tests for the full synthetic page rendering pipeline."""

    def test_viewer_page_renders(self):
        from django.test import RequestFactory

        from tap_grid.models import Entity
        from tap_web.synthetic import render_synthetic_page

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Test Entity")

        factory = RequestFactory()
        request = factory.get("/object/grid_fixtures__constrained_source/test--" + str(entity.pk) + "/")

        subgraph = load_subgraph("entity-viewer")
        response = render_synthetic_page(
            request,
            subgraph,
            extra_query_params={
                "entity_id": str(entity.pk),
                "entity_type": "grid_fixtures__constrained_source",
                "subject_entity_id": str(entity.pk),
            },
        )
        assert response.status_code == 200
        assert b"Entity Viewer" in response.content

    def test_editor_page_renders(self):
        from django.test import RequestFactory
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.batch import create_batch
        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity
        from tap_web.synthetic import render_synthetic_page

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Gandalf")
        batch = create_batch(source="test")
        prev = get_caller_context()
        set_caller_context(CallerContext(user=get_caller_context().user, batch_id=str(batch.entity.id)))
        try:
            ConstrainedSource.objects.create(entity=entity, name="Gandalf", description="A wizard.")
        finally:
            set_caller_context(prev)

        factory = RequestFactory()
        request = factory.get("/object/grid_fixtures__constrained_source/gandalf--" + str(entity.pk) + "/edit/")

        subgraph = load_subgraph("entity-editor")
        response = render_synthetic_page(
            request,
            subgraph,
            extra_query_params={
                "entity_id": str(entity.pk),
                "entity_type": "grid_fixtures__constrained_source",
                "subject_entity_id": str(entity.pk),
            },
        )
        assert response.status_code == 200
        assert b"Entity Editor" in response.content

    def test_synthetic_page_includes_graph_assets(self):
        from django.test import RequestFactory

        from tap_grid.models import Entity
        from tap_web.synthetic import render_synthetic_page

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Test")
        factory = RequestFactory()
        request = factory.get("/")

        subgraph = load_subgraph("entity-viewer")
        response = render_synthetic_page(
            request,
            subgraph,
            extra_query_params={
                "entity_id": str(entity.pk),
                "entity_type": "grid_fixtures__constrained_source",
                "subject_entity_id": str(entity.pk),
            },
        )
        assert b"cytoscape.min.js" in response.content
        assert b"panel-graph.css" in response.content

    def test_no_page_in_subgraph_raises_404(self):
        from django.http import Http404
        from django.test import RequestFactory

        from tap_web.synthetic import render_synthetic_page

        factory = RequestFactory()
        request = factory.get("/")

        empty_subgraph = {"nodes": [], "edges": []}
        with pytest.raises(Http404):
            render_synthetic_page(request, empty_subgraph)

    def test_panel_markup_renders_without_the_safe_filter(self):
        """The page template prints rendered_html with plain autoescaping (tap#509)."""
        from pathlib import Path

        from django.test import RequestFactory

        from tap_grid.models import Entity
        from tap_web.synthetic import render_synthetic_page

        template = Path(__file__).resolve().parents[1] / "templates" / "tap_web" / "synthetic_page.html"
        source = template.read_text(encoding="utf-8")
        assert "|safe" not in source

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Test")
        request = RequestFactory().get("/")
        response = render_synthetic_page(
            request,
            load_subgraph("entity-viewer"),
            extra_query_params={
                "entity_id": str(entity.pk),
                "entity_type": "grid_fixtures__constrained_source",
                "subject_entity_id": str(entity.pk),
            },
        )
        assert response.status_code == 200
        # Panel markup arrived as markup, not as escaped text.
        assert b"&lt;div" not in response.content

    def test_a_failing_panel_never_renders_its_exception_text(self, monkeypatch):
        """The error box escapes and omits exception text, which may carry request data (tap#509)."""
        from django.test import RequestFactory

        from tap_grid.models import Entity
        from tap_web import synthetic
        from tap_web.synthetic import render_synthetic_page

        def boom(*_args, **_kwargs):
            raise RuntimeError("<script>alert(1)</script> secret-detail")

        monkeypatch.setattr(synthetic, "render_to_string", boom)
        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Test")
        request = RequestFactory().get("/")
        response = render_synthetic_page(
            request,
            load_subgraph("entity-viewer"),
            extra_query_params={
                "entity_id": str(entity.pk),
                "entity_type": "grid_fixtures__constrained_source",
                "subject_entity_id": str(entity.pk),
            },
        )
        assert response.status_code == 200
        assert b"<script>alert(1)</script>" not in response.content
        assert b"secret-detail" not in response.content
        assert b"failed to render" in response.content
