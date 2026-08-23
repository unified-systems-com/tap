"""Tests for the plugin registry/report service + `manage.py plugins` command.

The report reads the live app registry, so these are integration-style (django_db).
They assert the facts that do NOT depend on EntityType seeding in the test DB — schema
validity, identity, and the bidirectional dependency graph — which is where the value
(and the risk of drift) lives. See req-tap-plugin-arch-install-registry -3/-5.
"""

from __future__ import annotations

import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from tap.plugin_testing import requires_plugins
from tap_auth.errors import AuthzError
from tap_grid.caller_context import CallerContext, set_caller_context
from tap_plugins.report import build_report, get_plugin_report

pytestmark = pytest.mark.django_db


def test_build_report_validates_and_is_self_consistent() -> None:
    # build_report() validates against plugin-report.schema.json internally — a bad shape
    # would raise here. Then check the count invariant.
    report = build_report()
    assert report["schema_version"] == 1
    assert report["plugin_count"] == len(report["plugins"])
    assert report["plugin_count"] >= 1


@requires_plugins("gryphon_playground", "samsite")
def test_report_includes_migrated_gryphon_playground() -> None:
    slugs = {p["slug"] for p in build_report()["plugins"]}
    # The package-mode migration target must appear (identity via its tap.plugins entry point).
    assert "gryphon_playground" in slugs
    assert "samsite" in slugs


@requires_plugins("samsite", "compliance_core", "github_core", "identity_core", "roscale", "sigstore_core")
def test_report_dependency_edges_are_bidirectional() -> None:
    by_slug = {p["slug"]: p for p in build_report()["plugins"]}
    samsite = by_slug["samsite"]
    assert samsite["dependencies"]["depends_on"] == [
        "compliance_core",
        "github_core",
        "identity_core",
        "roscale",
        "sigstore_core",
    ]
    # Every declared out-edge appears as a required_by in-edge on the target row.
    for dep in ("compliance_core", "github_core", "identity_core", "roscale", "sigstore_core"):
        assert "samsite" in by_slug[dep]["dependencies"]["required_by"]


def test_report_has_no_undeclared_imports() -> None:
    # The pre-boot consistency gate fails closed on any undeclared cross-plugin import, so
    # a healthy instance's report shows none. This test would light up if a plugin gained
    # an undeclared import without declaring it (drift the gate would also catch at boot).
    for p in build_report()["plugins"]:
        assert p["dependencies"]["undeclared_imports"] == [], p["slug"]


def test_report_provenance_is_captured() -> None:
    # Post-eviction the plugins are git-installed from their own repos (the in-tree
    # validate_plugin fixture is the lone editable install); the report captures each
    # plugin's install provenance (source + mode), whatever it is.
    for p in build_report()["plugins"]:
        assert p["source"], p
        assert p["mode"], p


def test_plugins_command_json_smoke() -> None:
    out = io.StringIO()
    call_command("plugins", "--json", stdout=out)
    data = json.loads(out.getvalue())
    assert data["schema_version"] == 1
    assert {"slug", "dependencies", "surfaces", "load_health"} <= set(data["plugins"][0])


def test_plugins_command_human_smoke() -> None:
    out = io.StringIO()
    call_command("plugins", stdout=out)
    text = out.getvalue()
    assert "plugin(s):" in text
    assert "depends_on:" in text and "required_by:" in text


# --- Service-layer capability gate (get_plugin_report) ------------------------


def _set_caller(group_name: str | None) -> None:
    user = get_user_model().objects.create_user(username=f"u_{group_name or 'nogroup'}", password="x")
    if group_name:
        user.groups.add(Group.objects.get(name=group_name))
    set_caller_context(CallerContext(user=user))


def test_get_plugin_report_allows_plugins_read_holder() -> None:
    # tap_admin holds "*" (every capability, incl. plugins.read).
    _set_caller("tap_admin")
    report = get_plugin_report()
    assert report["schema_version"] == 1
    assert report["plugin_count"] >= 1


def test_get_plugin_report_denies_caller_without_plugins_read() -> None:
    # tap_viewer holds only grid.read — enough to see pages, NOT the plugin registry.
    _set_caller("tap_viewer")
    with pytest.raises(AuthzError):
        get_plugin_report()


def test_get_plugin_report_denies_capabilityless_caller() -> None:
    _set_caller(None)
    with pytest.raises(AuthzError):
        get_plugin_report()
