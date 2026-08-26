"""Collection-completeness guard — `req-dev-validation-collection-complete`.

TAP-IMPLEMENTS: req-dev-validation-collection-complete@c8ac403907d1/8048024a53c6 (enforcement)
    — the guard that validates the validator: every on-disk test file collects or is
    ledger-justified. (`collection_addopts` is its sub-guard defending the ledger.)

Every `test_*.py`/`*_test.py` on disk (minus the justified `_IGNORED_DIRS` ledger)
must be collected by a full-repo run — validate the validator, so "green" cannot
mean "the subset pytest happened to collect passed" (the hole that shipped the
2026-07-01 login regression). This guard forks `pytest --collect-only`, so it is
the slowest one (still per-commit by design).
"""

from __future__ import annotations

from tap.guards._collection_scan import collected_test_files, filesystem_test_files
from tap.guards.base import Guard


class CollectionCompletenessGuard(Guard):
    slug = "collection-completeness"
    map_row = "Collection completeness"
    rid = "req-dev-validation-collection-complete"
    description = (
        "A test file on disk that the default pytest run doesn't collect silently gates nothing — the "
        "2026-07-01 login regression shipped green exactly this way. This asserts every on-disk test "
        "file (minus the justified ledger) is collected by a full-repo run, so the scope can't narrow "
        "unnoticed."
    )

    def check(self) -> None:
        orphans = sorted(filesystem_test_files() - collected_test_files())
        assert not orphans, (
            "These test files exist on disk but are NOT collected by the default pytest run — they will "
            "silently never gate:\n  "
            + "\n  ".join(orphans)
            + "\n\nEither bring them into discovery scope (do not add a `testpaths` allow-list) or, if the "
            "exclusion is intentional, add the dir to `_IGNORED_DIRS` in tap/guards/_collection_scan.py "
            "WITH justification and a matching `--ignore=` in pyproject `addopts`."
        )
