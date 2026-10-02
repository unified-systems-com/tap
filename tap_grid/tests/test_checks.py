"""tap_grid.E001 refuses the dev-default search-readonly password outside DEBUG.

req-grid-search-readonly-role.sec. `tap_boot.orchestrator` provisions the Postgres
role with `settings.SEARCH_READONLY_PASSWORD` on every boot, so a deployment that
never sets `TAP_SEARCH_READONLY_PASSWORD` would stand up a live database login
whose password is a literal in a public repository.

The check is an `Error`, not a `Warning`, on purpose: every management command
aborts, including `manage.py boot`, whose grid-infra phase is what actually
provisions the role. A warning would scroll past in boot output, which is exactly
how the value would reach production.
"""

from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings

from tap_grid.checks import check_search_readonly_password_is_not_the_dev_default as _check

DEV_DEFAULT = settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD
REAL_SECRET = "a-generated-deployment-secret"


def _ids() -> list[str | None]:
    return [e.id for e in _check(None)]


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_errors_when_deployed_with_the_dev_default() -> None:
    """The case this exists for: DEBUG off, nobody set the env var."""
    assert _ids() == ["tap_grid.E001"]


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=REAL_SECRET)
def test_silent_when_a_real_secret_is_configured() -> None:
    """Positive control: a correctly configured deployment must boot.

    Without this, a check that errored unconditionally would satisfy the test
    above while making TAP unbootable."""
    assert _ids() == []


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD="")
def test_errors_when_the_password_is_explicitly_empty() -> None:
    """Empty is not "not the default".

    `TAP_SEARCH_READONLY_PASSWORD=""` satisfies a bare inequality against the dev
    default while provisioning the role with NO password — strictly worse than the
    published one. The first version of this check tested only inequality and let
    this through; it was caught in review, not by these tests, which is why the case
    is pinned explicitly rather than folded into the default test.
    """
    assert _ids() == ["tap_grid.E002"]


@override_settings(DEBUG=True, SEARCH_READONLY_PASSWORD="")
def test_empty_password_is_still_silent_under_debug() -> None:
    """The DEBUG carve-out applies to both refusals, not just the default one."""
    assert _ids() == []


@override_settings(DEBUG=True, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_silent_under_debug() -> None:
    """`docker compose up` works out of the box; that convenience is deliberate."""
    assert _ids() == []


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_the_error_is_fail_closed_not_advisory() -> None:
    """Django aborts management commands on Error and continues on Warning, so the
    severity IS the control here — a Warning would let `manage.py boot` reach its
    grid-infra phase and provision the role with the published password, merely
    mentioning it on the way past."""
    from django.core.checks import Error

    errors = _check(None)
    assert len(errors) == 1
    assert isinstance(errors[0], Error)


def test_the_guard_compares_against_the_settings_constant() -> None:
    """The check must read the same constant settings.py defaults to, not a copy.

    A re-typed literal here would drift the day the default changes, and the guard
    would silently stop guarding — the exact failure this whole class of finding
    keeps taking."""
    import inspect

    import tap_grid.checks as mod

    source = inspect.getsource(mod)
    assert "settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD" in source
    assert DEV_DEFAULT not in source, "the dev default is re-typed here instead of referenced"


def test_the_check_is_registered_with_django() -> None:
    """Registration is what makes it run; the function alone guards nothing."""
    from django.core.checks import registry

    assert any(c is _check for c in registry.registry.get_checks())


# ---------------------------------------------------------------------------
# tap_grid.E004 — every declared edge type resolves (Issue# 583 - tap)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-delete-cascade-17")
class TestEdgeDeclarationsResolve:
    def test_this_stack_is_clean(self) -> None:
        """Positive control on the real registry: every model's declarations resolve."""
        from tap_grid.checks import check_edge_declarations_resolve, declared_edge_types

        assert declared_edge_types(), "the scan read no declarations at all"
        assert check_edge_declarations_resolve(None) == []

    def test_defined_includes_core_wildcard_and_constrained_edges(self) -> None:
        from tap_grid.checks import defined_edge_types

        defined = defined_edge_types()
        assert "PRODUCED_BATCH" in defined, "a core edge"
        assert (
            "PG_LINKS__grid_fixtures" in defined
        ), "a wildcard edge registers no constraint; it comes from the manifest"
        assert "CONSTRAINED_LINK__grid_fixtures" in defined, "a constrained edge"

    def test_a_renamed_containment_edge_is_an_error_naming_model_attribute_and_slug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rename the definition, leave the declaration: the exact shape nothing else catches."""
        from tap_grid.checks import check_edge_declarations_resolve
        from tap_grid.registry import get_model_class

        model = get_model_class("grid_fixtures__constrained_source")
        monkeypatch.setattr(model, "CONTAINMENT_EDGES", ("CONSTRAINED_LINK_RENAMED__grid_fixtures",), raising=False)
        errors = check_edge_declarations_resolve(None)
        assert [e.id for e in errors] == ["tap_grid.E004"]
        message = errors[0].msg
        assert "grid_fixtures__constrained_source.CONTAINMENT_EDGES" in message
        assert "'CONSTRAINED_LINK_RENAMED__grid_fixtures'" in message
        assert "validate_plugin" in (errors[0].hint or "")

    def test_a_renamed_outbound_edge_is_an_error_too(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.checks import check_edge_declarations_resolve
        from tap_grid.registry import get_model_class

        model = get_model_class("grid_fixtures__constrained_target")
        monkeypatch.setattr(
            model,
            "OUTBOUND_EDGES",
            [{"nodes": [{"type": "x"}], "edges": [{"type": "GONE__grid_fixtures"}]}],
            raising=False,
        )
        errors = check_edge_declarations_resolve(None)
        assert [(e.id, "OUTBOUND_EDGES" in e.msg, "'GONE__grid_fixtures'" in e.msg) for e in errors] == [
            ("tap_grid.E004", True, True)
        ]

    def test_the_error_is_fail_closed_not_advisory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from django.core.checks import Error

        from tap_grid.checks import check_edge_declarations_resolve
        from tap_grid.registry import get_model_class

        model = get_model_class("grid_fixtures__constrained_source")
        monkeypatch.setattr(model, "CONTAINMENT_EDGES", ("NOPE__grid_fixtures",), raising=False)
        [error] = check_edge_declarations_resolve(None)
        assert isinstance(error, Error)

    def test_a_models_declaration_never_defines_an_edge_type(self) -> None:
        """Grok on PR# 589 - tap asked whether the defined set is tautological — whether a model's
        OUTBOUND_EDGES feeds the edge-type registry so a renamed slug would define itself. It
        does not: declaration registration writes the NODE registry only. This is the settling
        evidence, as a test, so the answer cannot rot."""
        from tap_grid.constraints import list_registered_edge_types, register_constraints

        register_constraints(
            "grid_fixtures__phantom_probe",
            outbound=[
                {
                    "nodes": [{"type": "grid_fixtures__constrained_target"}],
                    "edges": [{"type": "PHANTOM__grid_fixtures"}],
                }
            ],
            inbound=None,
        )
        assert "PHANTOM__grid_fixtures" not in list_registered_edge_types()

    def test_a_renamed_constrained_edge_definition_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The exact threat: the DEFINITION of a constrained edge is renamed, the model untouched.
        Simulated by removing the definition from the defined set the check consults."""
        from tap_grid import checks
        from tap_grid.constraints import get_edge_type_constraints

        assert get_edge_type_constraints("CONSTRAINED_LINK__grid_fixtures") is not None, "a constrained edge"
        original = checks.defined_edge_types
        monkeypatch.setattr(checks, "defined_edge_types", lambda: original() - {"CONSTRAINED_LINK__grid_fixtures"})
        errors = checks.check_edge_declarations_resolve(None)
        assert errors and all(e.id == "tap_grid.E004" and "'CONSTRAINED_LINK__grid_fixtures'" in e.msg for e in errors)
        assert any("grid_fixtures__constrained_source.OUTBOUND_EDGES" in e.msg for e in errors)


# ---------------------------------------------------------------------------
# tap_grid.E004 for hotlinks — a hotlink's edge_type is a defined edge (Issue# 910 - tap)
# ---------------------------------------------------------------------------

_VIZ_EDGE_TYPES = {
    "USES_ARRANGEMENT": ({"layout"}, {"arrangement"}),
    "USES_LAYOUT": ({"elevation", "panel"}, {"layout"}),
    "USES_ELEVATION": ({"projection"}, {"elevation"}),
    "USES_DEFAULT_ELEVATION": ({"projection"}, {"elevation"}),
    "NAVIGATES_TO": ({"elevation"}, {"elevation"}),
    "USES_PROJECTION": ({"panel"}, {"projection"}),
}


@pytest.mark.spec("req-grid-hotlink-model-5")
class TestHotlinkEdgeTypesResolve:
    def test_every_hotlink_on_this_stack_is_read_and_resolves(self) -> None:
        """Positive control: the scan reads every real hotlink, and each names a defined edge."""
        from tap_grid.checks import declared_edge_types, defined_edge_types

        hotlinks = {(d.owner, d.edge_type) for d in declared_edge_types() if d.attribute == "HOTLINKS"}
        assert {
            ("page", "USES_PANEL"),
            ("layout", "USES_ARRANGEMENT"),
            ("elevation", "USES_LAYOUT"),
            ("elevation", "NAVIGATES_TO"),
            ("projection", "USES_ELEVATION"),
            ("projection", "USES_DEFAULT_ELEVATION"),
        } <= hotlinks
        defined = defined_edge_types()
        assert {edge_type for _, edge_type in hotlinks} <= defined

    def test_the_viz_edge_types_are_registered_with_sources_and_targets(self) -> None:
        from django.apps import apps

        from tap_grid.constraints import get_edge_type_constraints

        for slug, (sources, targets) in _VIZ_EDGE_TYPES.items():
            constraints = get_edge_type_constraints(slug)
            assert constraints is not None, slug
            assert (constraints.sources, constraints.targets) == (sources, targets), slug
        declared = {et["slug"]: et for et in apps.get_app_config("tap_viz").edge_types}
        assert set(declared) == set(_VIZ_EDGE_TYPES)
        assert all(et["description"] and et["name"] for et in declared.values())

    def test_a_hotlink_naming_an_undefined_edge_type_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plant a hotlink whose edge_type nothing defines: the boot-time check fails closed."""
        from django.core.checks import Error

        from tap_grid.checks import check_edge_declarations_resolve
        from tap_grid.registry import get_model_class

        model = get_model_class("layout")
        planted = [{**model.HOTLINKS[0], "edge_type": "UNDEFINED_HOTLINK_EDGE"}]
        monkeypatch.setattr(model, "HOTLINKS", planted)
        [error] = check_edge_declarations_resolve(None)
        assert isinstance(error, Error) and error.id == "tap_grid.E004"
        assert "layout.HOTLINKS" in error.msg and "'UNDEFINED_HOTLINK_EDGE'" in error.msg

    def test_unregistering_a_viz_definition_is_caught(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The pre-#910 state: the hotlink is declared, the edge type is not defined."""
        from tap_grid import checks

        original = checks.defined_edge_types
        monkeypatch.setattr(checks, "defined_edge_types", lambda: original() - {"NAVIGATES_TO"})
        [error] = checks.check_edge_declarations_resolve(None)
        assert "elevation.HOTLINKS" in error.msg and "'NAVIGATES_TO'" in error.msg


# ---------------------------------------------------------------------------
# tap_grid.E005 — every registered grid model defaults to LiveManager
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-traversal-exec-read-scope-14")
class TestGridModelsDefaultToLiveManager:
    """A grid model that overrode its default manager would return tombstones with no error."""

    def test_this_stack_is_clean(self) -> None:
        """Positive control on the real registry: every registered model defaults to LiveManager."""
        from tap_grid.checks import check_grid_models_default_to_live_manager, registered_grid_models

        assert len(registered_grid_models()) > 1, "the check read no models at all"
        assert check_grid_models_default_to_live_manager(None) == []

    def test_the_check_is_registered(self) -> None:
        """It runs as a Django system check on every management command, not only here."""
        from django.core.checks import registry

        from tap_grid.checks import check_grid_models_default_to_live_manager

        assert any(c is check_grid_models_default_to_live_manager for c in registry.registry.get_checks())

    def test_an_overridden_default_manager_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`Meta.default_manager_name = "all_objects"` — or any non-live default — is refused."""
        from django.core.checks import Error

        from tap_grid.checks import check_grid_models_default_to_live_manager
        from tap_grid.registry import get_model_class

        model: Any = get_model_class("grid_fixtures__node")
        monkeypatch.setattr(model._meta, "default_manager", model.all_objects)
        errors = check_grid_models_default_to_live_manager(None)
        assert [e.id for e in errors] == ["tap_grid.E005"]
        assert isinstance(errors[0], Error)
        assert "default manager is AllObjectsManager" in errors[0].msg
        assert "PgNode" in errors[0].msg

    def test_an_overridden_objects_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`objects = models.Manager()` on a subclass is refused even if the default is untouched."""
        from django.db import models

        from tap_grid.checks import check_grid_models_default_to_live_manager
        from tap_grid.registry import get_model_class

        model = get_model_class("grid_fixtures__node")
        monkeypatch.setattr(model, "objects", models.Manager())
        errors = check_grid_models_default_to_live_manager(None)
        assert [(e.id, "`objects` is Manager" in e.msg) for e in errors] == [("tap_grid.E005", True)]

    def test_a_livemanager_subclass_is_not_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exact type, so a subclass cannot redefine what `live` means by overriding get_queryset."""
        from tap_grid.checks import grid_models_not_defaulting_to_live
        from tap_grid.models import LiveManager
        from tap_grid.registry import get_model_class

        class WiderManager(LiveManager):
            def get_queryset(self) -> Any:
                return super(LiveManager, self).get_queryset()  # skips the live filter

        model: Any = get_model_class("grid_fixtures__node")
        monkeypatch.setattr(model._meta, "default_manager", WiderManager())
        assert grid_models_not_defaulting_to_live([model]) == [
            f"{model.__module__}.{model.__qualname__}: default manager is WiderManager, not LiveManager"
        ]
