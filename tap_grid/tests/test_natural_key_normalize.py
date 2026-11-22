"""A type's own spelling of its natural key, applied wherever core resolves one (unified-systems-com/tap#1265).

``panel`` is the live fixture. It is re-declared here on ``("slug", "config.tenant")`` with a rule
that spans both entries, the shape computing_core's ImageTag needs (``nginx`` on Docker Hub is
``library/nginx``): under tenant ``docker`` a slug without the ``library-`` prefix gains it. A
slug may not carry a ``/``, hence the dash.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap_grid.grift import grift_import
from tap_grid.natural_key import normalized_key_values
from tap_grid.services import create_node
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

DECLARED = ("slug", "config.tenant")


def _docker_rule(cls: type, values: dict[str, object]) -> dict[str, object]:
    slug, tenant = values["slug"], values["config.tenant"]
    if tenant == "docker" and isinstance(slug, str) and not slug.startswith("library-"):
        return {**values, "slug": f"library-{slug}"}
    return values


@pytest.fixture
def ruled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
    monkeypatch.setattr(Panel, "normalize_natural_key", classmethod(_docker_rule))


def _create(slug: str, tenant: str = "docker") -> Panel:
    result = create_node(
        "panel", {"slug": slug, "name": "Identity", "view": "tap_web/panels/identity.html", "config": {"tenant": tenant}}
    )
    assert result.success, result.errors
    panel: Panel = Panel.objects.get(entity_id=result.entity_id)
    return panel


def _bundle(*slugs: str) -> dict[str, Any]:
    nodes = [
        {
            "entity": {"ref": f"p{i}", "entity_type": "panel", "name": "Imported", "dimensions": {"tap.graph": "web"}},
            "node": {
                "name": "Imported",
                "slug": slug,
                "description": "",
                "view": "tap_web/panel_error.html",
                "config": {"tenant": "docker"},
            },
        }
        for i, slug in enumerate(slugs)
    ]
    return _minimal_doc([_batch_container(_batch_entity_id(), nodes=nodes)])


@pytest.mark.spec("req-grid-entity-natural-key-26")
class TestTheHook:
    def test_the_default_is_the_identity(self) -> None:
        values = {"slug": "nginx", "config.tenant": "docker"}
        assert normalized_key_values(Panel, values) == values

    def test_the_rule_is_applied(self, ruled: None) -> None:
        assert normalized_key_values(Panel, {"slug": "nginx", "config.tenant": "docker"}) == {
            "slug": "library-nginx",
            "config.tenant": "docker",
        }

    def test_a_rule_that_changes_the_entries_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
        monkeypatch.setattr(Panel, "normalize_natural_key", classmethod(lambda cls, values: {"slug": values["slug"]}))
        with pytest.raises(ImproperlyConfigured, match="exactly the declared entries"):
            normalized_key_values(Panel, {"slug": "nginx", "config.tenant": "docker"})


@pytest.mark.django_db
@pytest.mark.spec("req-grid-entity-natural-key-27")
class TestWhereItApplies:
    def test_the_row_is_stored_in_the_rules_spelling(self, ruled: None) -> None:
        panel = _create("nginx")
        assert panel.slug == "library-nginx"
        assert panel.config == {"tenant": "docker"}

    def test_the_lookup_finds_the_row_by_either_spelling(self, ruled: None, default_caller_context: Any) -> None:
        from tap_grid.services import find_by_natural_key

        panel = _create("nginx")
        for slug in ("nginx", "library-nginx"):
            found = find_by_natural_key(
                "panel", {"slug": slug, "config.tenant": "docker"}, caller_context=default_caller_context
            )
            assert found == panel.entity_id, slug

    def test_a_second_spelling_imported_later_updates_the_row(self, ruled: None) -> None:
        first = grift_import(_bundle("library-nginx"))
        assert first.success, first.errors
        second = grift_import(_bundle("nginx"))
        assert second.success, second.errors
        assert second.imported_batches[0].resolved_refs["p0"] == first.imported_batches[0].resolved_refs["p0"]
        assert Panel.objects.filter(slug__in=["nginx", "library-nginx"]).count() == 1

    def test_two_spellings_in_one_batch_are_one_object_not_two_rows(self, ruled: None) -> None:
        """Before the hook these were two keys and minted two rows. Now the batch names one object
        twice, which the importer refuses as it refuses any repeated identity, writing nothing."""
        result = grift_import(_bundle("nginx", "library-nginx"))
        assert not result.success
        assert [e.code for e in result.errors] == ["duplicate_entity_id"], result.errors
        assert Panel.objects.filter(slug__in=["nginx", "library-nginx"]).count() == 0

    def test_a_reference_in_the_short_spelling_finds_the_stored_row(self, ruled: None, default_caller_context: Any) -> None:
        """Edge endpoints, removal targets and anchors all resolve a key through one function."""
        from tap_grid.grift.importer import _find_node_by_key

        panel = _create("nginx")
        found = _find_node_by_key("panel", {"slug": "nginx", "config.tenant": "docker"}, {}, default_caller_context)
        assert found == str(panel.entity_id)

    def test_a_reference_missing_an_entry_is_refused_by_the_lookup_not_the_hook(
        self, ruled: None, default_caller_context: Any
    ) -> None:
        """The hook reads only a complete key; an incomplete one keeps the lookup's own refusal (PR 1318 review)."""
        from tap_grid.exceptions import ServiceValidationError
        from tap_grid.grift.importer import _find_node_by_key

        assert normalized_key_values(Panel, {"slug": "nginx"}) == {"slug": "nginx"}
        with pytest.raises(ServiceValidationError, match="is found by exactly"):
            _find_node_by_key("panel", {"slug": "nginx"}, {}, default_caller_context)

    def test_an_override_that_skips_super_is_refused_at_write(self, ruled: None, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "prepare_for_write", lambda self: None)
        try:
            result = create_node(
                "panel",
                {"slug": "nginx", "name": "Identity", "view": "tap_web/panels/identity.html", "config": {"tenant": "docker"}},
            )
        except ImproperlyConfigured as exc:
            assert "super().prepare_for_write()" in str(exc)
            return
        assert not result.success, "a row whose key is not in normalised form was written"
        assert any("super().prepare_for_write()" in str(error) for error in result.errors), result.errors
