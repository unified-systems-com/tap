"""A plugin's own views mount at /plugins/<slug>/ under the plugin's namespace."""

from __future__ import annotations

import importlib.util
import sys
import types

import pytest
from django.apps import apps
from django.http import HttpResponse
from django.urls import path

from tap_plugins.base import TapPluginConfig
from tap_web import urls as web_urls
from tap_web.reserved import get_reserved_url_prefixes


class _ProbeConfig(TapPluginConfig):
    pass


def _config(name: str, label: str) -> TapPluginConfig:
    config = object.__new__(_ProbeConfig)
    config.name = name
    config.label = label
    return config


@pytest.fixture
def probe_plugin(monkeypatch: pytest.MonkeyPatch) -> str:
    package = types.ModuleType("tap_plugin.urlprobe")
    package.__dict__["__path__"] = []
    module = types.ModuleType("tap_plugin.urlprobe.urls")
    module.__dict__["urlpatterns"] = [path("ping", lambda request: HttpResponse("pong"), name="ping")]
    monkeypatch.setitem(sys.modules, "tap_plugin.urlprobe", package)
    monkeypatch.setitem(sys.modules, "tap_plugin.urlprobe.urls", module)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == module.__name__ else None)
    monkeypatch.setattr(
        apps,
        "get_app_configs",
        lambda: [_config("tap_plugin.urlprobe", "urlprobe"), _config("tap_plugin.nourls", "nourls")],
    )
    return "urlprobe"


@pytest.mark.spec("req-web-page-plugin-urls-1")
def test_a_plugin_urls_module_mounts_under_its_slug(probe_plugin: str):
    mounted = web_urls.plugin_urlpatterns()
    assert len(mounted) == 1
    resolver = mounted[0]
    assert str(resolver.pattern) == "plugins/urlprobe/"
    assert resolver.namespace == "urlprobe"
    match = resolver.resolve("plugins/urlprobe/ping")
    assert match is not None and match.url_name == "ping"


@pytest.mark.spec("req-web-page-plugin-urls-2")
def test_a_plugin_without_a_urls_module_mounts_nothing(probe_plugin: str):
    namespaces = [resolver.namespace for resolver in web_urls.plugin_urlpatterns()]
    assert "nourls" not in namespaces


def test_plugin_routes_come_before_the_page_catch_all():
    names = [getattr(p, "name", None) or getattr(p, "namespace", None) for p in web_urls.urlpatterns]
    assert names[-1] == "page"


@pytest.mark.spec("req-web-page-plugin-urls-3")
def test_the_plugins_prefix_is_reserved_against_page_slugs():
    assert "/plugins" in get_reserved_url_prefixes()
