"""Plugin-declared capabilities and roles (req-tap-auth-plugin-declarations).

A plugin declares ``<slug>.capabilities.json`` and ``<slug>.roles.json`` in its package root.
These tests drive the real loaders against files written to a temporary directory, standing in
for an installed plugin, then check confinement, enforcement through ``policy``, the hard sync,
and the login-grant path. No real plugin ships these files today, so the import-time registries
are unchanged and each test builds the plugin registry it needs.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured

from tap_auth import boot, plugin_declarations, policy, roles, sync
from tap_auth import capabilities as caps
from tap_auth.boot import AuthBootError
from tap_auth.models import Capability, ProtectedGroup
from tap_auth.plugin_declarations import PluginAuthFiles
from tap_grid.caller_context import CallerContext

User = get_user_model()

SLUG = "widget"


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload))
    return path


def _capability_file(directory: Path, slug: str, names: list[str]) -> Path:
    return _write(
        directory / f"{slug}.capabilities.json",
        {
            "version": 1,
            "description": f"Capabilities the {slug} test plugin declares.",
            "capabilities": [{"name": n, "description": f"Test capability {n}.", "risk": "low"} for n in names],
        },
    )


def _role_file(directory: Path, slug: str, body: dict[str, Any]) -> Path:
    return _write(
        directory / f"{slug}.roles.json",
        {"version": 1, "description": f"Roles the {slug} test plugin declares.", "roles": body},
    )


def _role(capabilities: list[str] | str, assignable_to: tuple[str, ...] = ("human",)) -> dict[str, Any]:
    return {"description": "A test role.", "capabilities": capabilities, "assignable_to": list(assignable_to)}


def _load_capabilities_with(
    monkeypatch: pytest.MonkeyPatch, *files: PluginAuthFiles
) -> tuple[caps.CapabilitySpec, ...]:
    monkeypatch.setattr(caps, "plugin_auth_files", lambda: files)
    return caps._load_capabilities()


def _load_registry(
    monkeypatch: pytest.MonkeyPatch, files: PluginAuthFiles
) -> tuple[tuple[caps.CapabilitySpec, ...], dict[str, roles.RoleSpec]]:
    """Load capabilities then roles with one fake plugin installed, as import would."""
    specs = _load_capabilities_with(monkeypatch, files)
    by_name = {s.name: s for s in specs}
    monkeypatch.setattr(roles, "ALL_CAPABILITY_NAMES", tuple(by_name))
    monkeypatch.setattr(roles, "get_capability", by_name.get)
    monkeypatch.setattr(roles, "plugin_auth_files", lambda: (files,))
    return specs, roles._load_roles()


def _install_registry(
    monkeypatch: pytest.MonkeyPatch, specs: tuple[caps.CapabilitySpec, ...], role_map: dict[str, roles.RoleSpec]
) -> None:
    """Make the loaded registry the live one for policy and sync, for this test only."""
    monkeypatch.setattr(caps, "CAPABILITIES", specs)
    monkeypatch.setattr(caps, "ALL_CAPABILITY_NAMES", tuple(s.name for s in specs))
    monkeypatch.setattr(caps, "_BY_NAME", {s.name: s for s in specs})
    monkeypatch.setattr(roles, "ROLES", role_map)
    monkeypatch.setattr(sync, "_GROUP_BUNDLES", {k: r.capabilities for k, r in role_map.items()})


@pytest.fixture
def widget_files(tmp_path: Path) -> PluginAuthFiles:
    return PluginAuthFiles(
        slug=SLUG,
        capabilities_path=_capability_file(tmp_path, SLUG, ["widget.read", "widget.export"]),
        roles_path=_role_file(
            tmp_path,
            SLUG,
            {
                "widget.viewer": _role(["widget.read"]),
                "widget.operator": _role(["widget.read", "widget.export"]),
            },
        ),
    )


# --- discovery -------------------------------------------------------------------------


class TestDiscovery:
    @pytest.mark.spec("req-tap-auth-plugin-declarations-1")
    def test_slugs_come_from_installed_plugin_apps(self, monkeypatch):
        fake = SimpleNamespace(
            INSTALLED_APPS=[
                "django.contrib.auth",
                "tap_auth",
                "tap_plugin.alpha",
                "tap_plugin.beta.apps.BetaConfig",
                "tap_plugin.alpha.apps.AlphaConfig",
            ]
        )
        monkeypatch.setattr(plugin_declarations, "settings", fake)
        assert plugin_declarations.installed_plugin_slugs() == ("alpha", "beta")

    @pytest.mark.spec("req-tap-auth-plugin-declarations-1")
    def test_files_found_by_convention_and_absent_files_contribute_nothing(self, monkeypatch, tmp_path):
        alpha = tmp_path / "alpha"
        beta = tmp_path / "beta"
        alpha.mkdir()
        beta.mkdir()
        _capability_file(alpha, "alpha", ["alpha.read"])
        monkeypatch.setattr(plugin_declarations, "installed_plugin_slugs", lambda: ("alpha", "beta"))
        monkeypatch.setattr(plugin_declarations, "_package_dir", lambda slug: tmp_path / slug)
        found = plugin_declarations.plugin_auth_files()
        assert found == (PluginAuthFiles("alpha", alpha / "alpha.capabilities.json", None),)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-1")
    def test_an_installed_plugin_package_is_located(self):
        slugs = plugin_declarations.installed_plugin_slugs()
        if not slugs:
            pytest.skip("no tap_plugin app installed in this test configuration")
        assert plugin_declarations._package_dir(slugs[0]).is_dir()


# --- capability confinement --------------------------------------------------------------


class TestCapabilityConfinement:
    @pytest.mark.spec("req-tap-auth-plugin-declarations-2")
    def test_plugin_capabilities_join_the_registry_attributed_to_the_plugin(self, monkeypatch, widget_files):
        specs = _load_capabilities_with(monkeypatch, widget_files)
        declared = {s.name: s.declared_by for s in specs if s.declared_by != caps.CORE_DECLARER}
        assert declared == {"widget.read": SLUG, "widget.export": SLUG}
        assert {s.name for s in specs} >= set(caps.ALL_CAPABILITY_NAMES)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-2")
    def test_malformed_file_fails_loud(self, monkeypatch, tmp_path):
        path = _write(tmp_path / "widget.capabilities.json", {"version": 1, "capabilities": []})
        with pytest.raises(ImproperlyConfigured, match="widget.capabilities.json"):
            _load_capabilities_with(monkeypatch, PluginAuthFiles(SLUG, path, None))

    @pytest.mark.spec("req-tap-auth-plugin-declarations-3")
    def test_capability_outside_own_namespace_is_refused(self, monkeypatch, tmp_path):
        path = _capability_file(tmp_path, SLUG, ["widget.read", "other.read"])
        with pytest.raises(ImproperlyConfigured, match="other.read"):
            _load_capabilities_with(monkeypatch, PluginAuthFiles(SLUG, path, None))

    @pytest.mark.spec("req-tap-auth-plugin-declarations-3")
    def test_plugin_cannot_declare_in_a_core_namespace(self, monkeypatch, tmp_path):
        path = _capability_file(tmp_path, "grid", ["grid.export"])
        with pytest.raises(ImproperlyConfigured, match="core capability namespace"):
            _load_capabilities_with(monkeypatch, PluginAuthFiles("grid", path, None))

    @pytest.mark.spec("req-tap-auth-plugin-declarations-3")
    def test_plugin_cannot_redeclare_a_core_capability(self, monkeypatch, tmp_path):
        path = _capability_file(tmp_path, "auth", ["auth.manage_users"])
        with pytest.raises(ImproperlyConfigured):
            _load_capabilities_with(monkeypatch, PluginAuthFiles("auth", path, None))

    @pytest.mark.spec("req-tap-auth-plugin-declarations-3")
    def test_name_projecting_to_a_core_permission_codename_is_refused(self, monkeypatch, tmp_path):
        # 'cares_run.collectors' and core 'cares.run_collectors' are both 'cares_run_collectors'.
        assert "cares.run_collectors" in caps.ALL_CAPABILITY_NAMES
        path = _capability_file(tmp_path, "cares_run", ["cares_run.collectors"])
        with pytest.raises(ImproperlyConfigured, match="same permission codename"):
            _load_capabilities_with(monkeypatch, PluginAuthFiles("cares_run", path, None))


# --- role confinement --------------------------------------------------------------------


class TestRoleConfinement:
    @pytest.mark.spec("req-tap-auth-plugin-declarations-4")
    def test_plugin_roles_load_human_only_and_attributed(self, monkeypatch, widget_files):
        _, role_map = _load_registry(monkeypatch, widget_files)
        operator = role_map["widget.operator"]
        assert operator.capabilities == ("widget.read", "widget.export")
        assert operator.assignable_to == frozenset({"human"})
        assert operator.declared_by == SLUG
        assert not operator.is_wildcard

    @pytest.mark.spec("req-tap-auth-plugin-declarations-5")
    def test_admin_wildcard_includes_plugin_capabilities(self, monkeypatch, widget_files):
        _, role_map = _load_registry(monkeypatch, widget_files)
        assert {"widget.read", "widget.export"} <= set(role_map[roles.ADMIN_ROLE].capabilities)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-4")
    @pytest.mark.parametrize(
        ("body", "match"),
        [
            ({"other.viewer": _role(["widget.read"])}, "roles named 'widget.<role>'"),
            ({"widget": _role(["widget.read"])}, "roles named 'widget.<role>'"),
            ({"widget.reader": _role(["widget.read", "grid.read"])}, "grid.read"),
            ({"widget.reader": _role(["widget.read"], ("program",))}, "assignable_to"),
            ({"widget.reader": _role(["widget.read"], ("human", "program"))}, "assignable_to"),
            ({"widget.reader": _role("*")}, "admin-only"),
            ({"tap_admin": _role("*")}, "admin-only"),
        ],
        ids=["foreign-key", "undotted-key", "core-capability", "program", "human-and-program", "wildcard", "admin"],
    )
    def test_role_reaching_past_the_plugin_is_refused(self, monkeypatch, tmp_path, body, match):
        files = PluginAuthFiles(
            SLUG,
            _capability_file(tmp_path, SLUG, ["widget.read"]),
            _role_file(tmp_path, SLUG, body),
        )
        with pytest.raises(ImproperlyConfigured, match=match):
            _load_registry(monkeypatch, files)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-4")
    def test_role_naming_an_undeclared_capability_is_refused(self, monkeypatch, tmp_path):
        files = PluginAuthFiles(
            SLUG,
            _capability_file(tmp_path, SLUG, ["widget.read"]),
            _role_file(tmp_path, SLUG, {"widget.reader": _role(["widget.write"])}),
        )
        with pytest.raises(ImproperlyConfigured, match="undefined capabilities"):
            _load_registry(monkeypatch, files)


# --- enforcement and sync ----------------------------------------------------------------


@pytest.mark.django_db
class TestEnforcementAndSync:
    @pytest.mark.spec("req-tap-auth-plugin-declarations-6")
    def test_sync_records_the_declarer_and_hard_syncs_plugin_role_groups(self, monkeypatch, widget_files):
        specs, role_map = _load_registry(monkeypatch, widget_files)
        _install_registry(monkeypatch, specs, role_map)
        sync.sync_capabilities()
        sync.sync_protected_groups()

        assert Capability.objects.get(name="widget.export").declared_by == SLUG
        assert Capability.objects.get(name="grid.read").declared_by == caps.CORE_DECLARER
        assert ProtectedGroup.objects.filter(builtin_key="widget.operator", is_protected=True).exists()
        held = set(Group.objects.get(name="widget.operator").permissions.values_list("codename", flat=True))
        assert held == {"widget_read", "widget_export"}

    @pytest.mark.spec("req-tap-auth-plugin-declarations-5")
    def test_plugin_role_grants_its_capabilities_and_nothing_more(self, monkeypatch, widget_files):
        specs, role_map = _load_registry(monkeypatch, widget_files)
        _install_registry(monkeypatch, specs, role_map)
        sync.sync_capabilities()
        sync.sync_protected_groups()

        operator = User.objects.create_user(username="widget-operator", password="x")
        operator.groups.add(Group.objects.get(name="widget.operator"))
        viewer = User.objects.create_user(username="widget-viewer", password="x")
        viewer.groups.add(Group.objects.get(name="widget.viewer"))
        outsider = User.objects.create_user(username="outsider", password="x")

        assert policy.can(CallerContext(user=operator), "widget.export")
        assert not policy.can(CallerContext(user=operator), "grid.read")
        assert policy.can(CallerContext(user=viewer), "widget.read")
        assert not policy.can(CallerContext(user=viewer), "widget.export")
        assert not policy.can(CallerContext(user=outsider), "widget.read")

    @pytest.mark.spec("req-tap-auth-plugin-declarations-7")
    def test_group_whose_role_is_gone_loses_every_permission(self, monkeypatch, tmp_path, widget_files, caplog):
        specs, role_map = _load_registry(monkeypatch, widget_files)
        _install_registry(monkeypatch, specs, role_map)
        sync.sync_capabilities()
        sync.sync_protected_groups()
        member = User.objects.create_user(username="widget-member", password="x")
        member.groups.add(Group.objects.get(name="widget.operator"))
        assert policy.can(CallerContext(user=member), "widget.export")

        # The plugin keeps its capabilities but drops its roles file.
        without_roles = PluginAuthFiles(SLUG, widget_files.capabilities_path, None)
        specs, role_map = _load_registry(monkeypatch, without_roles)
        _install_registry(monkeypatch, specs, role_map)
        sync.sync_capabilities()
        sync.sync_protected_groups()

        group = Group.objects.get(name="widget.operator")
        assert not group.permissions.exists()
        assert member.groups.filter(pk=group.pk).exists(), "membership is kept; removing it is an operator act"
        assert not policy.can(CallerContext(user=member), "widget.export")
        assert "widget.operator" in caplog.text

    @pytest.mark.spec("req-tap-auth-plugin-declarations-7")
    def test_uninstalled_plugin_capabilities_need_a_declared_prune(self, monkeypatch, widget_files):
        specs, role_map = _load_registry(monkeypatch, widget_files)
        _install_registry(monkeypatch, specs, role_map)
        sync.sync_capabilities()

        core_only = tuple(s for s in specs if s.declared_by == caps.CORE_DECLARER)
        monkeypatch.setattr(caps, "CAPABILITIES", core_only)
        monkeypatch.setattr(caps, "ALL_CAPABILITY_NAMES", tuple(s.name for s in core_only))
        with pytest.raises(sync.AuthSyncError, match="undeclared capability drift"):
            sync.sync_capabilities()
        sync.sync_capabilities(declared_prune=("widget.read", "widget.export"))
        assert not Capability.objects.filter(declared_by=SLUG).exists()


# --- login grants -------------------------------------------------------------------------


class TestLoginGrants:
    @pytest.mark.spec("req-tap-auth-plugin-declarations-8")
    def test_plugin_human_role_is_grantable_at_login(self, monkeypatch, widget_files):
        _, role_map = _load_registry(monkeypatch, widget_files)
        human = frozenset(k for k, r in role_map.items() if r.grantable_to("human"))
        monkeypatch.setattr(roles, "HUMAN_ASSIGNABLE_ROLES", human)
        section = {"description": "t", "initial_grants": {"a@example.com": ["tap_viewer", "widget.operator"]}}
        boot.validate_auth_section(section)
        boot._validate_initial_grants(section)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-8")
    def test_dotted_program_role_passes_the_shape_but_not_boot(self):
        section = {"description": "t", "initial_grants": {"a@example.com": ["tap_cares.collector"]}}
        boot.validate_auth_section(section)
        with pytest.raises(AuthBootError, match="tap_cares.collector"):
            boot._validate_initial_grants(section)

    @pytest.mark.spec("req-tap-auth-plugin-declarations-8")
    def test_role_of_a_plugin_not_installed_aborts_boot(self):
        section = {"description": "t", "initial_grants": {"a@example.com": ["widget.operator"]}}
        with pytest.raises(AuthBootError, match="widget.operator"):
            boot._validate_initial_grants(section)
