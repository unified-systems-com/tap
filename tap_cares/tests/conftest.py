"""Shared tap_cares test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tap.pytest_harness import isolated_registry
from tap_cares.registry import collector_registry


@pytest.fixture
def isolate_collector_registry() -> Iterator[None]:
    """Snapshot + empty the collector registry for the test, restore on exit.

    Formerly copied in four test modules; the body is the harness's
    ``isolated_registry`` idiom applied to ``collector_registry``.
    """
    with isolated_registry(collector_registry):
        yield
