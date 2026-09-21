"""Addopts-ignore ledger guard — `req-dev-validation-collection-complete`.

Every `--ignore=` in pyproject `addopts` must be registered in the `_IGNORED_DIRS`
ledger, so the completeness guard can't be fooled into believing a skipped dir is
covered.
"""

from __future__ import annotations

import re
import tomllib

from tap.guards._collection_scan import _IGNORED_DIRS
from tap.guards.base import REPO_ROOT, Guard


class AddoptsIgnoresRegisteredGuard(Guard):
    slug = "collection-addopts-registered"
    map_row = "Collection completeness"
    rid = "req-dev-validation-collection-complete"
    description = (
        "A `--ignore=` added to pyproject addopts but not registered in the _IGNORED_DIRS ledger would "
        "let the gate skip a dir the completeness check still believes is covered — a silent coverage "
        "hole. This asserts every real ignore is an accounted-for, justified ledger entry."
    )

    def check(self) -> None:
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        addopts = pyproject["tool"]["pytest"]["ini_options"].get("addopts", "")
        ignored_in_addopts = set(re.findall(r"--ignore=(\S+)", addopts))
        unregistered = sorted(ignored_in_addopts - _IGNORED_DIRS)
        assert not unregistered, (
            "These dirs are `--ignore`d in pyproject `addopts` but not registered in `_IGNORED_DIRS` "
            f"(so the completeness guard wrongly believes they are covered): {unregistered}. Add them to "
            "`_IGNORED_DIRS` with justification."
        )
