"""Tests for the reserved top-level URL prefix registry.

Covers:
  req-web-page-slug-sanitize.sec — Page slugs must not shadow real top-level routes
  req-tap-auth-app-4 — /auth is reserved

The registry (tap_web/reserved.py) collects each app's declared
`reserved_url_prefixes` plus project-level mounts. The key drift-prevention test
cross-checks the registry against the actual top-level URLconf, so a newly
mounted top-level route that forgets to declare itself fails here instead of
relying on reviewer memory.
"""

from __future__ import annotations

import pytest

from tap_web.reserved import get_reserved_url_prefixes, normalize_prefix


class TestNormalizePrefix:
    def test_adds_leading_slash(self):
        assert normalize_prefix("api") == "/api"

    def test_strips_trailing_slash(self):
        assert normalize_prefix("/api/") == "/api"

    def test_leaves_clean_prefix(self):
        assert normalize_prefix("/auth") == "/auth"

    def test_root_slash_preserved(self):
        assert normalize_prefix("/") == "/"


class TestReservedRegistry:
    def test_includes_per_app_and_project_prefixes(self):
        reserved = set(get_reserved_url_prefixes())
        # Project-level (tap_web.reserved._PROJECT_RESERVED_PREFIXES)
        assert "/admin" in reserved
        assert "/auth" in reserved  # req-tap-auth-app-4
        # Declared by tap_api / tap_viz / tap_web app configs
        assert "/api" in reserved
        assert "/viz" in reserved
        assert "/panel" in reserved
        assert "/object" in reserved
        assert "/files" in reserved  # req-tap-files-download-7

    def test_result_is_sorted_and_deduped(self):
        result = get_reserved_url_prefixes()
        assert result == sorted(set(result))


class TestUrlconfCoverage:
    """Drift guard: every static top-level URL prefix must be reserved.

    Walks the root URLconf's top-level patterns and asserts each statically
    mounted prefix (e.g. `admin/`, `api/`, `viz/`) is covered by the reserved
    registry. Adding a new top-level include without declaring its prefix
    reserved fails this test.
    """

    def test_all_top_level_static_prefixes_are_reserved(self):
        from tap.urls import urlpatterns

        reserved = set(get_reserved_url_prefixes())
        uncovered: list[str] = []
        for pattern in urlpatterns:
            route = str(getattr(pattern, "pattern", ""))
            # Skip the tap_web catch-all (empty route), dynamic routes, and
            # specific files (e.g. favicon.ico) — only static directory prefixes
            # mounted with a trailing slash define a reservable namespace.
            if not route or "<" in route or not route.endswith("/"):
                continue
            prefix = "/" + route.rstrip("/").split("/")[0]
            if prefix not in reserved:
                uncovered.append(prefix)

        assert not uncovered, (
            f"Top-level URL prefixes mounted in tap/urls.py but not reserved: {uncovered}. "
            "Declare them via `reserved_url_prefixes` on the owning AppConfig (or "
            "tap_web.reserved._PROJECT_RESERVED_PREFIXES for project-level mounts)."
        )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
