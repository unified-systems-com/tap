"""Unit tests for tap.plugin_deps — the plugin dependency scanner + consistency check.

Covers the pure computation (``compute_violations``) exhaustively with synthetic inputs
(no filesystem) and the AST scanner / manifest reader against tmp_path fixtures.
See spec-tap-plugin-architecture.md req-tap-plugin-arch-dependencies-4.
"""

from __future__ import annotations

from pathlib import Path

from tap import plugin_deps
from tap.plugin_deps import DeclaredDep, compute_violations

# --- _tap_plugin_segment -----------------------------------------------------


def test_tap_plugin_segment_extracts_slug() -> None:
    assert plugin_deps._tap_plugin_segment("tap_plugin.sigstore_core.models") == "sigstore_core"
    assert plugin_deps._tap_plugin_segment("tap_plugin.samsite") == "samsite"


def test_tap_plugin_segment_ignores_non_namespace() -> None:
    assert plugin_deps._tap_plugin_segment("tap_plugins.base") is None
    assert plugin_deps._tap_plugin_segment("tap_grid.models") is None
    assert plugin_deps._tap_plugin_segment("tap_plugin") is None  # no slug segment


# --- scan_observed_imports (AST) ---------------------------------------------


def _write(pkg: Path, rel: str, body: str) -> None:
    path = pkg / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_scan_observed_imports_finds_both_import_forms(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "samsite"
    _write(pkg, "a.py", "import tap_plugin.sigstore_core.models\n")
    _write(pkg, "sub/b.py", "from tap_plugin.github_core import panels\nfrom tap_plugin.roscale.workbench import W\n")
    observed = plugin_deps.scan_observed_imports(pkg, own_slug="samsite")
    assert observed == {"sigstore_core", "github_core", "roscale"}


def test_scan_observed_imports_excludes_self_and_non_namespace(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "samsite"
    _write(
        pkg,
        "a.py",
        "from tap_plugin.samsite.models import X\nimport tap_plugins.base\nfrom tap_grid.models import Entity\n",
    )
    assert plugin_deps.scan_observed_imports(pkg, own_slug="samsite") == set()


def test_scan_observed_imports_ignores_relative_imports(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "samsite"
    _write(pkg, "a.py", "from . import models\nfrom .models import X\n")
    assert plugin_deps.scan_observed_imports(pkg, own_slug="samsite") == set()


def test_scan_observed_imports_skips_unparseable(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "samsite"
    _write(pkg, "good.py", "import tap_plugin.github_core\n")
    _write(pkg, "bad.py", "def broken( : this is not python\n")
    assert plugin_deps.scan_observed_imports(pkg, own_slug="samsite") == {"github_core"}


# --- read_declared_depends_on ------------------------------------------------


def test_read_declared_depends_on_parses_entries(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "samsite"
    pkg.mkdir(parents=True)
    (pkg / "tap-plugin.toml").write_text(
        'slug = "samsite"\n'
        "depends_on = [\n"
        '  { slug = "sigstore_core" },\n'
        '  { slug = "github_core", min_version = "0.2.0" },\n'
        '  { slug = "roscale", optional = true },\n'
        "]\n",
        encoding="utf-8",
    )
    deps = plugin_deps.read_declared_depends_on(pkg)
    assert deps == [
        DeclaredDep(slug="sigstore_core", min_version=None, optional=False),
        DeclaredDep(slug="github_core", min_version="0.2.0", optional=False),
        DeclaredDep(slug="roscale", min_version=None, optional=True),
    ]


def test_read_declared_depends_on_absent_returns_empty(tmp_path: Path) -> None:
    pkg = tmp_path / "tap_plugin" / "x"
    pkg.mkdir(parents=True)
    (pkg / "tap-plugin.toml").write_text('slug = "x"\n', encoding="utf-8")
    assert plugin_deps.read_declared_depends_on(pkg) == []
    # No manifest at all → empty, not an error.
    assert plugin_deps.read_declared_depends_on(tmp_path / "nope") == []


def test_read_manifest_slug(tmp_path: Path) -> None:
    pkg = tmp_path / "p"
    pkg.mkdir()
    (pkg / "tap-plugin.toml").write_text('slug = "roscale"\n', encoding="utf-8")
    assert plugin_deps.read_manifest_slug(pkg) == "roscale"
    assert plugin_deps.read_manifest_slug(tmp_path / "absent") is None


# --- compute_violations (pure) -----------------------------------------------


def test_compute_violations_happy() -> None:
    # samsite after its deps, imports exactly what it declares.
    order = ["sigstore_core", "github_core", "roscale", "samsite"]
    declared = {
        "samsite": [
            DeclaredDep("sigstore_core", None, False),
            DeclaredDep("github_core", None, False),
            DeclaredDep("roscale", None, False),
        ]
    }
    observed = {"samsite": {"sigstore_core", "github_core", "roscale"}}
    assert compute_violations(order, declared, observed, versions={}) == []


def test_compute_violations_undeclared_import() -> None:
    order = ["github_core", "samsite"]
    observed = {"samsite": {"github_core"}}  # imports github_core...
    declared = {"samsite": []}  # ...but declares nothing
    result = compute_violations(order, declared, observed, versions={})
    assert len(result) == 1
    assert "imports 'tap_plugin.github_core'" in result[0]
    assert "does not declare" in result[0]


def test_compute_violations_dep_missing_from_install_set() -> None:
    order = ["samsite"]  # sigstore_core not installed
    declared = {"samsite": [DeclaredDep("sigstore_core", None, False)]}
    observed = {"samsite": set()}
    result = compute_violations(order, declared, observed, versions={})
    assert len(result) == 1
    assert "not in the profile install set" in result[0]


def test_compute_violations_optional_dep_absent_is_tolerated() -> None:
    order = ["samsite"]
    declared = {"samsite": [DeclaredDep("sigstore_core", None, optional=True)]}
    observed = {"samsite": set()}
    assert compute_violations(order, declared, observed, versions={}) == []


def test_compute_violations_wrong_order() -> None:
    # samsite installed BEFORE its declared dependency sigstore_core.
    order = ["samsite", "sigstore_core"]
    declared = {"samsite": [DeclaredDep("sigstore_core", None, False)]}
    observed = {"samsite": {"sigstore_core"}}
    result = compute_violations(order, declared, observed, versions={})
    assert any("installed before its declared dependency 'sigstore_core'" in v for v in result)


def test_compute_violations_min_version_unsatisfied() -> None:
    order = ["sigstore_core", "samsite"]
    declared = {"samsite": [DeclaredDep("sigstore_core", "0.5.0", False)]}
    observed = {"samsite": {"sigstore_core"}}
    result = compute_violations(order, declared, observed, versions={"sigstore_core": "0.1.0"})
    assert len(result) == 1
    assert ">=0.5.0" in result[0] and "0.1.0" in result[0]


def test_compute_violations_min_version_satisfied() -> None:
    order = ["sigstore_core", "samsite"]
    declared = {"samsite": [DeclaredDep("sigstore_core", "0.5.0", False)]}
    observed = {"samsite": {"sigstore_core"}}
    assert compute_violations(order, declared, observed, versions={"sigstore_core": "1.2.0"}) == []


def test_compute_violations_unparseable_installed_version_does_not_fail() -> None:
    order = ["sigstore_core", "samsite"]
    declared = {"samsite": [DeclaredDep("sigstore_core", "0.5.0", False)]}
    observed = {"samsite": {"sigstore_core"}}
    # A version string we cannot compare must not trip the gate (fail on missing dist elsewhere).
    assert compute_violations(order, declared, observed, versions={"sigstore_core": "not-a-version"}) == []
