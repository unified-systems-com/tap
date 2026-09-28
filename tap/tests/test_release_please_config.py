"""The release PR bumps tap's own version in uv.lock itself.

No spec marker: req-cicd-product-releases is traced `non-python` (the release-please workflow and
its config are the implementation), so these guard its config rather than claim evidence for it.

uv.lock records core's OWN version (`[[package]] name = "tap"`), so a release PR that bumps only
pyproject.toml leaves the lock stale and `uv lock --check` fails. release-please updates it as an
extra file, in the same commit as the pyproject bump, so no second writer is needed on the
release PR (the org-bots fork bot has no write access to push one).

The jsonpath reads `name.value` because release-please's TOML updater parses with position
wrappers: every scalar is `{start, end, value}`, so `@.name=='tap'` matches nothing. Verified
2026-09-27 against the release-please CLI pinned in org-bots: the path changes exactly one line
of uv.lock, tap's version, and nothing else.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOCK_JSONPATH = "$.package[?(@.name.value==='tap')].version"


def test_the_release_config_bumps_taps_own_version_in_uv_lock() -> None:
    config = json.loads((REPO_ROOT / "release-please-config.json").read_text())
    extras = config["packages"]["."]["extra-files"]
    assert {"type": "toml", "path": "uv.lock", "jsonpath": LOCK_JSONPATH} in extras


def test_uv_lock_names_exactly_one_tap_package_at_the_pyproject_version() -> None:
    """The jsonpath selects by name, so there must be exactly one `tap` entry, and today it must
    already agree with pyproject: the release PR moves both together from a coherent start."""
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text())
    taps = [p for p in lock["package"] if p["name"] == "tap"]
    assert len(taps) == 1
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    assert taps[0]["version"] == project["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", project["version"])
