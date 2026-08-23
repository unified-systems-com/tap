"""Plugin-system machinery guard: the TapPluginConfig.ready() load contract.

The base ``TapPluginConfig.ready()`` is the sole carrier of the v0 plugin
load contract's startup phase: it loads/validates ``tap-plugin.toml`` and
performs edge/type/editor/search registration. A subclass that overrides
``ready()`` and forgets ``super().ready()`` silently severs the plugin from
its manifest — ``config.manifest`` stays ``None``, no registration runs, and
``import_plugin_grift`` skips the plugin with "No manifest loaded", which in
turn aborts ``scripts/spawn-session.sh`` mid-spawn.

This regressed once already (aws_core steampipe-collector shell, 2026-05-17).
These two tests are the guard. See req-tap-plugin-load-v0-ready-chain in
tap_plugins/specs/spec-tap-plugin-load-lifecycle-v0.md. Per spec-tap-testing.md
this is plugin-system machinery, so it lives in tap_plugins/tests/, not in
individual plugins.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest
from django.apps import apps

from tap_plugins.base import TapPluginConfig


def _tap_plugin_configs() -> list[TapPluginConfig]:
    """Every loaded app config that participates in the TAP plugin contract.

    This is the exact set ``import_plugin_grift`` resolves over
    (tap_plugins/management/commands/import_plugin_grift.py), so the guard
    tracks the command that surfaced the original regression.
    """
    return [c for c in apps.get_app_configs() if isinstance(c, TapPluginConfig)]


_CONFIGS = _tap_plugin_configs()
_CONFIG_IDS = [c.label for c in _CONFIGS]


@pytest.mark.spec("req-tap-plugin-load-v0-ready-chain-2")
@pytest.mark.parametrize("config", _CONFIGS, ids=_CONFIG_IDS)
def test_plugin_manifest_loaded(config: TapPluginConfig) -> None:
    """Behavioral invariant: every loaded TAP plugin has a manifest.

    ``manifest`` is populated only by the base ``ready()``'s
    ``_load_and_validate_manifest``. ``None`` here means the load contract's
    startup phase did not run for this plugin — from any cause, not only a
    missing ``super().ready()``.
    """
    assert config.manifest is not None, (
        f"{type(config).__name__} ({config.label}) has no loaded manifest. "
        f"Its ready() almost certainly overrides the base without calling "
        f"super().ready(), severing the plugin from tap-plugin.toml. See "
        f"req-tap-plugin-load-v0-ready-chain."
    )


def _calls_super_ready(method: object) -> bool:
    """True if ``method``'s source contains a ``super().ready()`` call."""
    source = textwrap.dedent(inspect.getsource(method))  # type: ignore[arg-type]
    tree = ast.parse(source)
    for node in ast.walk(tree):
        # Match ``<expr>.ready(...)`` where <expr> is a ``super(...)`` call.
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ready"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        ):
            return True
    return False


@pytest.mark.spec("req-tap-plugin-load-v0-ready-chain-1")
@pytest.mark.parametrize("config", _CONFIGS, ids=_CONFIG_IDS)
def test_ready_override_chains_to_super(config: TapPluginConfig) -> None:
    """Structural diagnostic: a self-defined ready() must chain to super.

    Sharper than the behavioral check — it names the offending class even if
    app-loading order ever masked the missing-manifest symptom.
    """
    cls = type(config)
    if "ready" not in cls.__dict__:
        pytest.skip(f"{cls.__name__} does not override ready(); base contract applies.")

    assert _calls_super_ready(cls.ready), (
        f"{cls.__name__}.ready() overrides the base but never calls "
        f"super().ready(). The base ready() is the only thing that loads "
        f"tap-plugin.toml and registers edges/types/editors/searches; omit "
        f"it and the plugin loads with no manifest. Make super().ready() the "
        f"first statement of the override. See req-tap-plugin-load-v0-ready-chain."
    )
