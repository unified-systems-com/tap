"""Baseline fixture-vocabulary gate (req-dev-validation-baseline-vocabulary).

Core-located tests build their fixtures from a small set of plugin-supplied node/edge
vocabularies (`tap.plugin_testing.BASELINE_PLUGIN_SLUGS`). That requirement used to live
only as prose — a docstring in `tap.plugin_testing` and a sentence in
`boot/core.boot.json`'s description — so a stack booted on a profile that omits them
produced ~30 unexplained collection ImportErrors instead of one actionable message.

These tests cover both halves: the derivation (is the vocabulary here?) and the gate's
disposition (fail loudly, and only for runs that actually collect core tests). The
disposition arms matter as much as the detection arm — the wrong answer here is a *skip*,
which would report green while exercising none of the grid spine.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from tap import plugin_testing
from tap.plugin_testing import BASELINE_PLUGIN_SLUGS, installed_plugin_slugs, missing_baseline_plugins
from tap.pytest_harness import _REPO_ROOT, _is_core_test, pytest_collection_modifyitems


class _FakeItem:
    """The only surface the gate reads off a collected item."""

    def __init__(self, path: Path | None) -> None:
        self.path = path


def _item(path: Path | None) -> pytest.Item:
    """A stand-in collected item. The gate reads `.path` and nothing else."""
    return cast("pytest.Item", _FakeItem(path))


# --------------------------------------------------------------------------- #
# The derivation                                                               #
# --------------------------------------------------------------------------- #


def test_baseline_is_declared_and_non_empty() -> None:
    """The invariant is a value, not prose — something a test can read."""
    assert BASELINE_PLUGIN_SLUGS
    assert "grid_fixtures" in BASELINE_PLUGIN_SLUGS


def test_missing_baseline_derives_from_the_installed_set() -> None:
    """`missing` is exactly baseline-minus-installed — the fact, not a proxy for it."""
    installed = set(installed_plugin_slugs())
    assert missing_baseline_plugins() == sorted(set(BASELINE_PLUGIN_SLUGS) - installed)


# --------------------------------------------------------------------------- #
# Core-vs-plugin item scoping                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("relative", "is_core"),
    [
        ("tap_grid/tests/test_services.py", True),
        ("tap/tests/test_baseline_vocabulary.py", True),
        ("tap_web/tests/test_views.py", True),
        ("plugins/samsite/tap_plugin/samsite/tests/test_x.py", False),
        ("_dev-plugins/github_core/tap_plugin/github_core/tests/test_x.py", False),
    ],
)
def test_core_scoping_by_path(relative: str, is_core: bool) -> None:
    """In-worktree plugin checkouts are other repositories; only the rest is core."""
    assert _is_core_test(_item(_REPO_ROOT / relative)) is is_core


def test_installed_plugin_tests_are_not_core() -> None:
    """A wheel-installed plugin's tests resolve outside the worktree (`--pyargs` runs)."""
    assert _is_core_test(_item(Path("/usr/lib/python3/site-packages/tap_plugin/x/tests/test_y.py"))) is False


def test_item_without_a_path_is_not_core() -> None:
    """Defensive: an item exposing no `path` must not be read as core."""
    assert _is_core_test(_item(None)) is False


# --------------------------------------------------------------------------- #
# The gate's disposition                                                       #
# --------------------------------------------------------------------------- #


def test_gate_fails_loudly_when_core_tests_lack_the_vocabulary(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point: one actionable error, not ~30 ImportErrors and not a silent skip."""
    monkeypatch.setattr(plugin_testing, "missing_baseline_plugins", lambda: ["grid_fixtures"])
    items = [_item(_REPO_ROOT / "tap_grid/tests/test_services.py")]

    with pytest.raises(pytest.UsageError) as excinfo:
        pytest_collection_modifyitems(items)

    message = str(excinfo.value)
    assert "grid_fixtures" in message
    assert "core_dev" in message, "the message must name the fix, not just the fault"


def test_gate_is_silent_for_plugin_only_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pytest --pyargs tap_plugin.<slug>` must not require core's fixture vocabulary."""
    monkeypatch.setattr(plugin_testing, "missing_baseline_plugins", lambda: ["grid_fixtures"])
    items = [_item(Path("/usr/lib/python3/site-packages/tap_plugin/samsite/tests/test_y.py"))]

    pytest_collection_modifyitems(items)


def test_gate_is_silent_when_the_vocabulary_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative control: the gate must be capable of NOT firing, or its passing proves nothing."""
    monkeypatch.setattr(plugin_testing, "missing_baseline_plugins", list)
    items = [_item(_REPO_ROOT / "tap_grid/tests/test_services.py")]

    pytest_collection_modifyitems(items)


def test_gate_is_silent_on_an_empty_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    """No collected core tests means nothing to protect — `-k` filters must not trip it."""
    monkeypatch.setattr(plugin_testing, "missing_baseline_plugins", lambda: ["grid_fixtures"])

    pytest_collection_modifyitems([])
