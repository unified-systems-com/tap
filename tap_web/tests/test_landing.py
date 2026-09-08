"""The root URL is the operator's decision (req-web-page-landing, tap#340).

Covers the resolver's states, the 302 with query string, the loud placeholder, the
structured probe, the retired-type strip that keeps older seeds bootable, and the
migration's row cleanup on the upgrade path.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tap.pytest_harness import make_admin_client
from tap_grid.grift.retired import strip_retired_types
from tap_grid.models import Entity
from tap_grid.registry import retired_entity_reason
from tap_health.results import ProbeStatus
from tap_web.health import probe_web_landing
from tap_web.models import Page
from tap_web.page import resolve_landing

_LAYOUT = {
    "full_bleed": True,
    "columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "main", "height": "auto"}}}},
}


def _page(slug: str, name: str = "Landing target") -> Page:
    return cast(Page, Page.objects.create(slug=slug, name=name, layout=_LAYOUT))


def _rename(page: Page, slug: str) -> None:
    """Model-level rename (below the service layer, deliberately): simulates a page moving."""
    Page.objects.filter(pk=page.pk).update(slug=slug)  # type: ignore[misc]  # django-stubs sees BaseModel's manager
    page.refresh_from_db()


def _config(page: Page, slug: str | None = None) -> dict[str, Any]:
    return {
        "entity_id": str(page.entity_id),
        "slug": page.slug if slug is None else slug,
        "source": {"entity_id": "profile", "slug": "profile"},
    }


@pytest.mark.django_db
class TestResolveLanding:
    def test_ok(self):
        page = _page("/landing-ok")
        res = resolve_landing(_config(page))
        assert res.ok and res.page == page and res.live_slug == "/landing-ok"
        assert res.context()["source"] == {"entity_id": "profile", "slug": "profile"}

    def test_undeclared(self):
        assert resolve_landing(None).state == "undeclared"

    def test_malformed_uuid_is_distinct_from_missing(self):
        res = resolve_landing({"entity_id": "not-a-uuid", "slug": "/x", "source": None})
        assert res.state == "malformed"
        res = resolve_landing({"entity_id": str(uuid.uuid4()), "slug": "/x", "source": None})
        assert res.state == "missing" and res.found_entity_type is None

    def test_malformed_slug(self):
        page = _page("/landing-slugless")
        assert resolve_landing(_config(page, slug="no-leading-slash")).state == "malformed"

    def test_wrong_type_is_missing_and_names_the_type(self):
        page = _page("/landing-wrong-type")
        res = resolve_landing({"entity_id": str(page.entity_id), "slug": "/x", "source": None})
        assert res.state == "slug_mismatch"  # a page, wrong slug
        other = Entity.objects.create(entity_type="search", name="not a page")
        res = resolve_landing({"entity_id": str(other.pk), "slug": "/x", "source": None})
        assert res.state == "missing" and res.found_entity_type == "search"

    @pytest.mark.spec("req-web-page-landing-10")
    def test_identity_fixed_content_not(self):
        """req-web-page-landing-10: rename follows, deletion is loud, a replacement never inherits."""
        page = _page("/landing-original")
        cfg = _config(page)
        _rename(page, "/landing-renamed")
        res = resolve_landing(cfg)
        assert res.state == "slug_mismatch" and res.page == page and res.live_slug == "/landing-renamed"

        squatter = _page("/landing-original", name="squatter")
        res = resolve_landing(cfg)
        assert res.page == page and res.page != squatter, "the old slug must never select the landing page"

        page.entity.delete()
        assert resolve_landing(cfg).state == "missing"


@pytest.mark.django_db
class TestLandingView:
    @pytest.mark.spec("req-web-render-landing-1")
    @pytest.mark.spec("req-web-render-landing-2")
    @pytest.mark.spec("req-web-page-landing-9")
    def test_root_redirects_302_with_query_string(self, settings):
        page = _page("/landing-view")
        settings.TAP_WEB_LANDING = _config(page)
        client = make_admin_client(username="landing-admin")
        response = client.get("/?limit=5&x=y")
        assert response.status_code == 302
        assert response.url == "/landing-view?limit=5&x=y"

    def test_root_redirects_to_live_slug_after_rename(self, settings):
        page = _page("/landing-before")
        settings.TAP_WEB_LANDING = _config(page)
        _rename(page, "/landing-after")
        # A renamed page is a slug_mismatch: loud, not a redirect — the operator's
        # assertion no longer holds (req-web-page-landing-11).
        response = make_admin_client(username="landing-admin").get("/")
        assert response.status_code == 200
        assert b'data-landing-state="slug_mismatch"' in response.content

    @pytest.mark.parametrize(
        ("config", "state"),
        [
            (None, "undeclared"),
            ({"entity_id": "nope", "slug": "/x", "source": None}, "malformed"),
            ({"entity_id": str(uuid.uuid4()), "slug": "/x", "source": None}, "missing"),
        ],
    )
    @pytest.mark.spec("req-web-render-landing-4")
    @pytest.mark.spec("req-web-page-landing-11")
    def test_every_non_ok_state_renders_the_placeholder_naming_it(self, settings, config, state):
        settings.TAP_WEB_LANDING = config
        response = make_admin_client(username="landing-admin").get("/")
        assert response.status_code == 200
        assert "tap_web/setup_placeholder.html" in [t.name for t in response.templates]
        assert f'data-landing-state="{state}"'.encode() in response.content

    @pytest.mark.spec("req-web-page-landing-10")
    def test_replacement_page_at_old_slug_does_not_inherit_root(self, settings):
        page = _page("/landing-taken")
        settings.TAP_WEB_LANDING = _config(page)
        page.entity.delete()
        _page("/landing-taken", name="replacement")
        response = make_admin_client(username="landing-admin").get("/")
        assert response.status_code == 200
        assert b'data-landing-state="missing"' in response.content


@pytest.mark.django_db
class TestLandingProbe:
    @pytest.mark.spec("req-web-page-landing-13")
    def test_healthy_carries_context(self, settings):
        page = _page("/landing-probe")
        settings.TAP_WEB_LANDING = _config(page)
        result = probe_web_landing()
        assert result.status is ProbeStatus.HEALTHY and result.code is None
        assert result.context["entity_id"] == str(page.entity_id)
        assert result.context["live_slug"] == "/landing-probe" and result.context["page_name"] == "Landing target"
        assert result.context["source"] == {"entity_id": "profile", "slug": "profile"}

    @pytest.mark.parametrize(
        ("config", "code"),
        [
            (None, "web.landing.undeclared"),
            ({"entity_id": "nope", "slug": "/x", "source": None}, "web.landing.malformed"),
            ({"entity_id": str(uuid.uuid4()), "slug": "/x", "source": None}, "web.landing.missing"),
        ],
    )
    @pytest.mark.spec("req-web-page-landing-13")
    def test_non_ok_states_are_coded(self, settings, config, code):
        settings.TAP_WEB_LANDING = config
        result = probe_web_landing()
        assert result.status is ProbeStatus.UNHEALTHY and result.code == code
        assert set(result.context) >= {"entity_id", "asserted_slug", "live_slug", "page_name", "source"}

    def test_slug_mismatch_is_coded(self, settings):
        page = _page("/landing-drift")
        settings.TAP_WEB_LANDING = _config(page, slug="/landing-asserted")
        result = probe_web_landing()
        assert result.code == "web.landing.slug_mismatch"
        assert result.context["live_slug"] == "/landing-drift"
        assert result.context["asserted_slug"] == "/landing-asserted"

    def test_registered_in_readiness_non_critical(self):
        from tap_health.registry import health_probe_registry
        from tap_health.selection import READINESS

        probe = health_probe_registry.get("web.landing")
        assert probe.group == "tap_web" and probe.critical is False and READINESS in probe.sets


class TestRetiredStrip:
    def test_landing_page_is_retired_with_a_reason(self):
        assert "tap#340" in (retired_entity_reason("landing_page") or "")

    def test_strip_drops_retired_nodes_and_their_edges_only(self):
        page_id, landing_id = str(uuid.uuid4()), str(uuid.uuid4())
        doc: dict[str, Any] = {
            "metadata": {"grift_version": "0"},
            "batches": [
                {
                    "batch_entity": {"entity_id": str(uuid.uuid4()), "entity_type": "batch", "name": "b"},
                    "nodes": [
                        {"entity": {"entity_id": page_id, "entity_type": "page"}, "node": {"slug": "/p"}},
                        {"entity": {"entity_id": landing_id, "entity_type": "landing_page"}, "node": {"name": "L"}},
                    ],
                    "edges": [
                        {
                            "entity": {"entity_id": str(uuid.uuid4()), "entity_type": "edge"},
                            "edge": {
                                "from_entity_id": landing_id,
                                "to_entity_id": page_id,
                                "edge_type": "USES_LANDING_PAGE",
                            },
                        },
                        {
                            "entity": {"entity_id": str(uuid.uuid4()), "entity_type": "edge"},
                            "edge": {"from_entity_id": page_id, "to_entity_id": page_id, "edge_type": "USES_PANEL"},
                        },
                    ],
                }
            ],
        }
        stripped_doc, report = strip_retired_types(doc)
        assert report.stripped and report.nodes == (("landing_page", landing_id),) and report.edges == 1
        batch: dict[str, Any] = stripped_doc["batches"][0]
        assert [n["entity"]["entity_id"] for n in batch["nodes"]] == [page_id]
        assert [e["edge"]["edge_type"] for e in batch["edges"]] == ["USES_PANEL"]
        # The input is not mutated.
        assert len(doc["batches"][0]["nodes"]) == 2 and len(doc["batches"][0]["edges"]) == 2

    def test_clean_document_passes_through_untouched(self):
        doc = {"batches": [{"nodes": [{"entity": {"entity_id": "x", "entity_type": "page"}, "node": {}}], "edges": []}]}
        out, report = strip_retired_types(doc)
        assert out is doc and not report.stripped


@pytest.mark.django_db(transaction=True)
class TestDropLandingPageMigration:
    """req-web-page-landing-14: the upgrade path cleans every obsolete spine row and keeps the page."""

    @pytest.mark.spec("req-web-page-landing-14")
    def test_upgrade_path_cleans_rows_and_preserves_target_page(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("tap_web", "0002_strip_uses_search_binding_key")])
        old_apps = executor.loader.project_state([("tap_web", "0002_strip_uses_search_binding_key")]).apps
        OldEntity = old_apps.get_model("tap_grid", "Entity")
        OldEdge = old_apps.get_model("tap_grid", "Edge")
        OldLanding = old_apps.get_model("tap_web", "LandingPage")
        OldPage = old_apps.get_model("tap_web", "Page")

        page_entity = OldEntity.objects.create(entity_type="page", name="kept page")
        OldPage.objects.create(entity=page_entity, slug="/migration-kept", name="kept page", layout=_LAYOUT)
        landing_entity = OldEntity.objects.create(entity_type="landing_page", name="old landing")
        OldLanding.objects.create(entity=landing_entity, name="old landing")
        edge_entity = OldEntity.objects.create(entity_type="edge", name="old edge")
        OldEdge.objects.create(
            entity=edge_entity, from_entity=landing_entity, to_entity=page_entity, edge_type="USES_LANDING_PAGE"
        )

        executor = MigrationExecutor(connection)
        executor.migrate([("tap_web", "0003_drop_landing_page")])

        assert not Entity.objects.filter(entity_type="landing_page").exists()
        assert not Entity.objects.filter(pk=edge_entity.pk).exists()
        assert Page.objects.filter(slug="/migration-kept").exists()
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('web_landing_page')")
            assert cur.fetchone()[0] is None
