"""Shared pytest configuration for tap/tests."""

from __future__ import annotations

# The throwaway-repo fixture (`repo`) used by the commit-trailer gate tests; registered here so the
# test modules need no fixture import (pyflakes reads an imported fixture as unused).
from tap.tests.throwaway_repo import throwaway_repo  # noqa: E402

__all__ = ["throwaway_repo"]
