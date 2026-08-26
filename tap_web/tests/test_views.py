"""Tests for tap_web views."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from tap.pytest_harness import batch_ctx, make_admin_client
from tap_grid.models import Entity


@pytest.mark.django_db
class TestLandingView:
    """Root / uses setup placeholder when no LandingPage is configured."""

    def test_root_returns_200(self):
        # Authenticated: the landing page sits behind the login wall
        # (req-tap-auth-service-boundary). An anonymous GET "/" is redirected to
        # login — covered separately by the wall tests.
        client = make_admin_client(username="views-admin")
        response = client.get("/")
        assert response.status_code == 200

    def test_root_shows_setup_placeholder_without_landing_page(self):
        client = make_admin_client(username="views-admin")
        response = client.get("/")
        assert "tap_web/setup_placeholder.html" in [t.name for t in response.templates]

    def test_root_placeholder_contains_admin_link(self):
        client = make_admin_client(username="views-admin")
        response = client.get("/")
        assert b"/admin/" in response.content

    def test_anonymous_root_redirected_to_login(self):
        """The login wall fronts the landing page: an anonymous request is a 302
        to login, not a rendered page (req-tap-auth-service-boundary)."""
        response = Client().get("/")
        assert response.status_code == 302
        assert response.url.startswith("/auth/passkey/login/")


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
@pytest.mark.usefixtures("fixture_object_editor")
class TestObjectEditorView:
    """Generic /object/<type>/<slug>--<uuid>/edit/ editor shell for registered entity types.

    Exercised against tap_web's own typed-editor fixture (conftest
    ``fixture_object_editor``) registered over the neutral grid_fixtures
    constrained-source node — no plugin editor dependency.
    """

    def _make_character(self, name: str = "Gandalf") -> tuple[object, str]:
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
        with batch_ctx(source="test:setup"):
            char = ConstrainedSource.objects.create(entity=entity, name=name, description="A wizard.")
        url_id = f"{name.lower().replace(' ', '-')}--{entity.pk}"
        return char, url_id

    def test_get_returns_200(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/"
        )
        assert response.status_code == 200

    def test_get_uses_synthetic_page(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/"
        )
        assert "tap_web/synthetic_page.html" in [t.name for t in response.templates]

    def test_get_includes_editor_panel(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/"
        )
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/editor_panel.html" in template_names

    def test_get_includes_typed_editor_template(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/"
        )
        template_names = [t.name for t in response.templates]
        assert "tap_web/tests/object_editor_fixture.html" in template_names

    def test_get_renders_character_name(self):
        _, url_id = self._make_character(name="Frodo Baggins")
        response = make_admin_client(username="views-admin").get(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/"
        )
        assert b"Frodo Baggins" in response.content

    def test_post_saves_name(self):
        char, url_id = self._make_character(name="Old Name")
        make_admin_client(username="views-admin").post(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/", {"name": "New Name", "description": ""}
        )
        char.entity.refresh_from_db()
        assert char.entity.name == "New Name"

    def test_post_saves_bio(self):
        char, url_id = self._make_character()
        make_admin_client(username="views-admin").post(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/",
            {"name": "Gandalf", "description": "Updated bio."},
        )
        char.refresh_from_db()
        assert char.description == "Updated bio."

    def test_post_redirects_on_success(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").post(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/", {"name": "Gandalf", "description": ""}
        )
        assert response.status_code == 302

    def test_post_empty_name_rerenders_with_errors(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").post(
            f"/object/grid_fixtures__constrained_source/{url_id}/edit/", {"name": "", "description": ""}
        )
        assert response.status_code == 200
        assert "tap_web/synthetic_page.html" in [t.name for t in response.templates]

    def test_unknown_entity_type_returns_404(self):
        response = make_admin_client(username="views-admin").get(
            "/object/unknown-type/some-slug--00000000-0000-0000-0000-000000000000/edit/"
        )
        assert response.status_code == 404

    def test_nonexistent_entity_returns_404(self):
        response = make_admin_client(username="views-admin").get(
            "/object/grid_fixtures__constrained_source/x--00000000-0000-0000-0000-000000000000/edit/"
        )
        assert response.status_code == 404


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
@pytest.mark.usefixtures("fixture_object_editor")
class TestObjectViewerView:
    """Generic /object/<type>/<slug>--<uuid>/ viewer shell."""

    def _make_character(self, name: str = "Aragorn") -> tuple[object, str]:
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
        with batch_ctx(source="test:setup"):
            char = ConstrainedSource.objects.create(entity=entity, name=name, description="Heir of Isildur.")
        url_id = f"{name.lower().replace(' ', '-')}--{entity.pk}"
        return char, url_id

    def test_get_returns_200(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert response.status_code == 200

    def test_get_uses_synthetic_page(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert "tap_web/synthetic_page.html" in [t.name for t in response.templates]

    def test_get_includes_viewer_panel(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/viewer_panel.html" in template_names

    def test_get_renders_character_name(self):
        _, url_id = self._make_character(name="Legolas")
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert b"Legolas" in response.content

    def test_get_shows_edit_link(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert b"/edit/" in response.content

    def test_viewer_includes_graph_panel(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        template_names = [t.name for t in response.templates]
        assert "tap_viz/panels/graph_panel.html" in template_names

    def test_viewer_includes_flip_panel(self):
        _, url_id = self._make_character()
        response = make_admin_client(username="views-admin").get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        template_names = [t.name for t in response.templates]
        assert "tap_web/panels/flip_panel.html" in template_names

    def test_unknown_entity_type_returns_404(self):
        response = make_admin_client(username="views-admin").get(
            "/object/unknown-type/some-slug--00000000-0000-0000-0000-000000000000/"
        )
        assert response.status_code == 404


def _no_cap_client() -> Client:
    """Authenticated client whose user holds no capability bundle."""
    user = get_user_model().objects.create_user(username="views-nocap", password="x")
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestObjectViewReadGate:
    """Graph-backed object views deny unauthorized callers (req-tap-auth-service-boundary).

    The web edge translates an authorization denial to a 403 via
    CallerContextMiddleware.process_exception. Both an anonymous request (no
    actor → MissingActor) and an authenticated-but-no-capability request
    (CapabilityDenied) are denied — passing authentication is not permission. The
    gate runs before the entity is loaded, so a denied caller cannot tell an
    existing object from a missing one.
    """

    def _make_character(self, name: str = "Boromir") -> str:
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
        with batch_ctx(source="test:setup"):
            ConstrainedSource.objects.create(entity=entity, name=name, description="Of Gondor.")
        return f"{name.lower()}--{entity.pk}"

    def test_anonymous_object_view_redirected_to_login(self):
        """Anonymous access is caught by the login wall BEFORE the view's authZ
        runs — a 302 to login, not the view's 403. Defense in depth: the wall
        fronts the service-boundary capability check (req-tap-auth-service-boundary).
        The 403 path is exercised by the no-cap (authenticated) tests below."""
        url_id = self._make_character()
        response = Client().get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert response.status_code == 302
        assert response.url.startswith("/auth/passkey/login/")

    def test_anonymous_object_edit_redirected_to_login(self):
        url_id = self._make_character()
        response = Client().get(f"/object/grid_fixtures__constrained_source/{url_id}/edit/")
        assert response.status_code == 302
        assert response.url.startswith("/auth/passkey/login/")

    def test_no_cap_object_view_denied_403(self):
        url_id = self._make_character()
        response = _no_cap_client().get(f"/object/grid_fixtures__constrained_source/{url_id}/")
        assert response.status_code == 403

    def test_no_cap_object_edit_denied_403(self):
        url_id = self._make_character()
        response = _no_cap_client().get(f"/object/grid_fixtures__constrained_source/{url_id}/edit/")
        assert response.status_code == 403

    def test_denied_before_existence_check_no_leak(self):
        """A no-cap caller gets 403 for a NON-existent object too — same as for an
        existing one — so existence is not leaked through the status code."""
        missing = "ghost--00000000-0000-0000-0000-000000000000"
        response = _no_cap_client().get(f"/object/grid_fixtures__constrained_source/{missing}/")
        assert response.status_code == 403
