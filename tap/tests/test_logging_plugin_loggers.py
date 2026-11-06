"""The plugin half of the logging builder (`req-tap-logging-plugin-loggers`).

Plugins install under the PEP 420 namespace ``tap_plugin`` (``tap_plugin.<slug>.apps.<Config>``), so their
``getLogger(__name__)`` loggers are named ``tap_plugin.<slug>.<module>``. A builder that matches any other
prefix configures nothing, the root logger's ``WARNING`` then drops every INFO and DEBUG record, and the
plugin looks like one that does not log.
"""

from __future__ import annotations

import logging
import logging.config

import pytest

from tap.logging import build_logging_config, plugin_logger_config

APPS = [
    "tap_boot",
    "tap_plugins",
    "tap_plugin.aws_core.apps.AwsCoreConfig",
    "tap_plugin.samsite.apps.SamsiteConfig",
]


@pytest.fixture
def restore_logging():
    """dictConfig is process-global: put the loggers it touches back."""
    names = ("tap_plugin", "tap_plugin.aws_core", "tap_plugin.samsite", "plugins", "plugins.legacy_one")
    saved = {n: (logging.getLogger(n).level, logging.getLogger(n).propagate, list(logging.getLogger(n).handlers)) for n in names}
    root = logging.getLogger()
    root_saved = (root.level, list(root.handlers))
    yield
    for n, (level, propagate, handlers) in saved.items():
        lg = logging.getLogger(n)
        lg.setLevel(level)
        lg.propagate = propagate
        lg.handlers[:] = handlers
    root.setLevel(root_saved[0])
    root.handlers[:] = root_saved[1]


@pytest.mark.spec("req-tap-logging-plugin-loggers-1")
def test_wildcard_plugin_logger_is_tap_plugin_at_info() -> None:
    config = plugin_logger_config(APPS)
    assert config["tap_plugin"]["level"] == "INFO"


@pytest.mark.spec("req-tap-logging-plugin-loggers-2")
def test_each_installed_plugin_gets_a_tap_plugin_slug_entry() -> None:
    config = plugin_logger_config(APPS)
    assert {"tap_plugin.aws_core", "tap_plugin.samsite"} <= set(config)
    assert config["tap_plugin.aws_core"]["level"] == "INFO"


@pytest.mark.spec("req-tap-logging-plugin-loggers-2")
def test_a_plugin_listed_twice_or_by_package_only_is_one_entry() -> None:
    config = plugin_logger_config(["tap_plugin.aws_core", "tap_plugin.aws_core.apps.AwsCoreConfig"])
    assert [k for k in config if k.startswith("tap_plugin.")] == ["tap_plugin.aws_core"]


@pytest.mark.spec("req-tap-logging-plugin-loggers-2")
def test_first_party_apps_and_foreign_entries_are_not_plugins() -> None:
    config = plugin_logger_config(["tap_boot", "tap_plugins", "django.contrib.auth", "tap_plugin"])
    assert set(config) == {"tap_plugin", "plugins"}


@pytest.mark.spec("req-tap-logging-plugin-loggers-4")
def test_plugin_loggers_do_not_propagate() -> None:
    config = plugin_logger_config(APPS)
    assert all(entry["propagate"] is False for entry in config.values())


@pytest.mark.spec("req-tap-logging-plugin-loggers-5")
def test_the_retired_plugins_namespace_is_still_recognised() -> None:
    config = plugin_logger_config(["plugins.legacy_one.apps.LegacyConfig"])
    assert {"plugins", "plugins.legacy_one", "tap_plugin"} <= set(config)


@pytest.mark.spec("req-tap-logging-plugin-loggers-5")
def test_an_info_record_from_an_installed_plugin_module_is_emitted(restore_logging) -> None:
    """The regression: with the old prefix this logger fell through to root and INFO was dropped."""
    logging.config.dictConfig(build_logging_config(APPS, env={}))
    collector = logging.getLogger("tap_plugin.aws_core.collectors.boto3_collector.collector")
    assert collector.isEnabledFor(logging.INFO)
    assert collector.getEffectiveLevel() == logging.INFO


@pytest.mark.spec("req-tap-logging-plugin-loggers-5")
def test_env_override_reaches_a_plugin_by_its_tap_plugin_name(restore_logging) -> None:
    logging.config.dictConfig(build_logging_config(APPS, env={"TAP_LOG_LEVELS": "tap_plugin.aws_core=DEBUG"}))
    assert logging.getLogger("tap_plugin.aws_core.x").isEnabledFor(logging.DEBUG)
    assert not logging.getLogger("tap_plugin.samsite.x").isEnabledFor(logging.DEBUG)
