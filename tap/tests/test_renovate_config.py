"""Renovate's lock-file-maintenance branch must not be rate-limited (tap#625).

`pyproject.toml` pins RANGES by policy, so a satisfied range needs no manifest edit and every
in-range update for the whole `uv.lock` closure can only arrive through one branch:
`lockFileMaintenance`. `wolfi-base` rotates its digest daily, so the base-image group
regenerates an update every run and takes the PR-creation budget first — the lock refresh was
pushed out every day and the Python closure sat frozen from 2026-08-15 to 2026-09-19, with
Renovate green the whole time.

A limit of `0` inside the `lockFileMaintenance` block makes that branch unlimited (Renovate
merges the block onto the branch's own upgrade before evaluating limits) — the same mechanism
that lets `vulnerabilityAlerts` bypass repo-wide limits by default.

This is config, so nothing else in the repo asserts it; without this test the exemption can be
removed by a tidy-up and the freeze returns silently, which is exactly how it arrived.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from tap.guards.base import REPO_ROOT

RENOVATE_CONFIG = REPO_ROOT / "renovate.json5"


def _load_json5(path: Path) -> dict[str, Any]:
    """Parse the subset of JSON5 this config uses: `//` comments, unquoted keys, trailing commas.

    A dependency for one config file is not worth it; if this ever fails to parse, the
    assertion below says so rather than silently passing on an empty dict.
    """
    raw = path.read_text(encoding="utf-8")
    without_comments = re.sub(r"(?<!:)//[^\n]*", "", raw)
    quoted_keys = re.sub(r"(?m)^(\s*)([A-Za-z_$][\w$]*)\s*:", r'\1"\2":', without_comments)
    no_trailing_commas = re.sub(r",(\s*[}\]])", r"\1", quoted_keys)
    parsed: Any = json.loads(no_trailing_commas)
    assert isinstance(parsed, dict), f"{path.name} did not parse to an object"
    return parsed


@pytest.fixture(scope="module")
def config() -> dict[str, Any]:
    return _load_json5(RENOVATE_CONFIG)


def test_lock_file_maintenance_is_enabled(config) -> None:
    assert config.get("lockFileMaintenance", {}).get("enabled") is True, (
        "lockFileMaintenance is how EVERY in-range update reaches uv.lock under the "
        "major-bound range policy; disabled, the Python closure freezes (tap#625)."
    )


@pytest.mark.parametrize("limit", ["prConcurrentLimit", "prHourlyLimit"])
def test_lock_file_maintenance_is_exempt_from_pr_limits(config, limit) -> None:
    value = config.get("lockFileMaintenance", {}).get(limit)
    assert value == 0, (
        f"lockFileMaintenance.{limit} must be 0 (unlimited for this branch). Without it the "
        f"daily wolfi-base digest rotation takes the PR budget every run and the lock refresh "
        f"is never created — the Python closure was frozen 2026-08-15..2026-09-19 that way "
        f"(tap#625). Renovate uses this same mechanism for vulnerabilityAlerts by default."
    )


def test_the_range_policy_that_makes_this_load_bearing_still_holds() -> None:
    """If deps ever stop being range-pinned, this exemption's rationale changes — say so here."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'"django>=\d', pyproject), (
        "django is no longer range-pinned in pyproject.toml: re-read tap#625 before assuming "
        "lockFileMaintenance is still the only path for in-range updates."
    )
