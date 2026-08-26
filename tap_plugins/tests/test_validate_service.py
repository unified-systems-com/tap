"""Tests for the plugin validation service.

Tests validate_plugin() against real plugin directories (administrivia, aws_core)
and synthetic fixtures to cover error paths.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from tap.plugin_testing import requires_plugins
from tap_plugins.validate.service import (
    CheckResult,
    ValidationResult,
    validate_plugin,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "validation_sample"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(tmp_path: Path, *, toml: str, extra_files: dict[str, str] | None = None) -> Path:
    """Create a minimal plugin directory from a TOML string."""
    plugin_dir = tmp_path / "test_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "tap-plugin.toml").write_text(textwrap.dedent(toml))
    (plugin_dir / "__init__.py").write_text("")
    (plugin_dir / "apps.py").write_text(
        "from tap_plugins.base import TapPluginConfig\n\n\nclass TestPluginConfig(TapPluginConfig):\n    pass\n"
    )
    if extra_files:
        for rel_path, content in extra_files.items():
            full = plugin_dir / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
    return plugin_dir


def _named_check(result: ValidationResult, check_id: str) -> CheckResult:
    """Return the single check with the given id (raises if absent/duplicated)."""
    matches = [c for c in result.checks if c.id == check_id]
    assert len(matches) == 1, f"expected exactly one {check_id!r} check, got {len(matches)}"
    return matches[0]


_MIN_TOML = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "test_plugin"\nname = "T"\n'


class TestRequiresTapCheck:
    """The compatibility-floor structure check (req-tap-plugin-extdev-compat-floor)."""

    def test_absent_is_informational_not_fatal(self, tmp_path: Path) -> None:
        # requires_tap is optional in v0: absence must not fail, not even under --strict
        # (the reusable-CI conformance gate runs strict). Info, not warn.
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML)
        check = _named_check(validate_plugin(plugin, strict=True), "requires-tap")
        assert check.status == "pass"
        assert any("optional in v0" in m.text for m in check.messages)

    def test_satisfied_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tap.core_version.core_tap_version", lambda: "0.1.0")
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML + 'requires_tap = ">=0.1,<0.2"\n')
        check = _named_check(validate_plugin(plugin), "requires-tap")
        assert check.status == "pass", check.messages

    def test_unsatisfied_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("tap.core_version.core_tap_version", lambda: "0.1.0")
        plugin = _make_plugin(tmp_path, toml=_MIN_TOML + 'requires_tap = ">=0.5"\n')
        result = validate_plugin(plugin)
        assert not result.ok
        assert _named_check(result, "requires-tap").status == "fail"


# ---------------------------------------------------------------------------
# Real plugin tests
# ---------------------------------------------------------------------------


class TestRealPlugins:
    """Validate existing plugins in the repo to confirm the service works end-to-end."""

    def test_administrivia_passes(self):
        result = validate_plugin(FIXTURE_ROOT)
        assert result.ok, result.to_human()
        assert result.level == "structure"
        assert not result.strict

    def test_administrivia_json_output_validates(self):
        result = validate_plugin(FIXTURE_ROOT)
        json_str = result.to_json()
        doc = json.loads(json_str)
        assert doc["ok"] is True
        assert doc["level"] == "structure"
        assert isinstance(doc["checks"], list)
        assert len(doc["checks"]) > 0

    def test_administrivia_human_output(self):
        result = validate_plugin(FIXTURE_ROOT)
        human = result.to_human()
        assert "PASS" in human
        assert "validation_sample" in human.lower()


# ---------------------------------------------------------------------------
# Level handling
# ---------------------------------------------------------------------------


class TestLevels:
    def test_default_level_is_structure(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
        """,
        )
        result = validate_plugin(plugin_dir)
        assert result.level == "structure"

    def test_unknown_level_raises_value_error(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
        """,
        )
        with pytest.raises(ValueError, match="Unknown validation level"):
            validate_plugin(plugin_dir, level="bogus")

    @requires_plugins("validation_sample")  # loads level imports tap_plugin.administrivia
    def test_loads_level_accepted(self):
        result = validate_plugin(FIXTURE_ROOT, level="loads")
        assert result.ok, result.to_human()
        assert result.level == "loads"

    @pytest.mark.django_db
    @requires_plugins("validation_sample")  # runs level imports tap_plugin.administrivia
    def test_runs_level_accepted(self):
        result = validate_plugin(FIXTURE_ROOT, level="runs")
        assert result.ok, result.to_human()
        assert result.level == "runs"


# ---------------------------------------------------------------------------
# Strict mode
# ---------------------------------------------------------------------------


class TestStrictMode:
    def test_strict_promotes_warnings(self, tmp_path):
        """An undeclared edge file causes a warning; strict promotes it to failure."""
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
                manifest_version = "0"
                plugin_version = "0.1.0"
                slug = "test"
                name = "Test"
            """,
            extra_files={
                "edges/STRAY.edge.json": json.dumps(
                    {
                        "slug": "STRAY",
                        "name": "Stray",
                        "description": "An undeclared edge.",
                    }
                ),
            },
        )
        # Non-strict: passes with warning
        result_normal = validate_plugin(plugin_dir, strict=False)
        assert result_normal.ok
        undeclared = [c for c in result_normal.checks if c.id == "undeclared-files"]
        assert len(undeclared) == 1
        assert undeclared[0].status == "warn"

        # Strict: warning promoted to failure
        result_strict = validate_plugin(plugin_dir, strict=True)
        assert not result_strict.ok
        undeclared_strict = [c for c in result_strict.checks if c.id == "undeclared-files"]
        assert undeclared_strict[0].status == "fail"


# ---------------------------------------------------------------------------
# Tests directory — existence is not coverage
# ---------------------------------------------------------------------------


class TestTestsDirIsNotEmpty:
    """A `tests/` holding no test files gates nothing — it must not read as covered.

    This is the exact shape of the two evicted plugins whose suites were dead for two
    weeks: the directory satisfied "tests/ exists" while `pytest --pyargs` collected
    zero tests, so the plugin looked gated and was not.
    """

    def test_absent_tests_dir_warns(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin(tmp_path, toml=_MIN_TOML)
        check = _named_check(validate_plugin(plugin_dir), "tests-dir")
        assert check.status == "warn"

    def test_tests_dir_with_no_test_files_warns(self, tmp_path: Path) -> None:
        """The regression that matters: present but empty is NOT a pass."""
        plugin_dir = _make_plugin(tmp_path, toml=_MIN_TOML, extra_files={"tests/__init__.py": ""})
        check = _named_check(validate_plugin(plugin_dir), "tests-dir")
        assert check.status == "warn", "an empty tests/ must not report as covered"

    def test_tests_dir_with_a_test_file_passes(self, tmp_path: Path) -> None:
        plugin_dir = _make_plugin(
            tmp_path,
            toml=_MIN_TOML,
            extra_files={"tests/__init__.py": "", "tests/test_thing.py": "def test_thing():\n    assert True\n"},
        )
        check = _named_check(validate_plugin(plugin_dir), "tests-dir")
        assert check.status == "pass"

    def test_suffix_pattern_also_counts(self, tmp_path: Path) -> None:
        """`*_test.py` is one of pytest's two default patterns — agree with what runs."""
        plugin_dir = _make_plugin(
            tmp_path,
            toml=_MIN_TOML,
            extra_files={"tests/__init__.py": "", "tests/thing_test.py": "def test_thing():\n    assert True\n"},
        )
        assert _named_check(validate_plugin(plugin_dir), "tests-dir").status == "pass"

    def test_strict_makes_an_empty_tests_dir_fatal(self, tmp_path: Path) -> None:
        """--strict is what release-plugin.sh and the per-repo CI admission gate run."""
        plugin_dir = _make_plugin(tmp_path, toml=_MIN_TOML, extra_files={"tests/__init__.py": ""})
        result = validate_plugin(plugin_dir, strict=True)
        assert not result.ok
        assert _named_check(result, "tests-dir").status == "fail"


# ---------------------------------------------------------------------------
# Structural failure cases
# ---------------------------------------------------------------------------


class TestStructuralFailures:
    def test_nonexistent_plugin_root(self, tmp_path):
        result = validate_plugin(tmp_path / "nope")
        assert not result.ok
        failed = [c for c in result.checks if c.status == "fail"]
        assert len(failed) >= 1

    def test_missing_manifest(self, tmp_path):
        plugin_dir = tmp_path / "empty_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        (plugin_dir / "apps.py").write_text("")
        result = validate_plugin(plugin_dir)
        assert not result.ok

    def test_invalid_toml(self, tmp_path):
        plugin_dir = tmp_path / "bad_toml"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("")
        (plugin_dir / "apps.py").write_text("")
        (plugin_dir / "tap-plugin.toml").write_text("this is not [valid toml")
        result = validate_plugin(plugin_dir)
        assert not result.ok

    def test_missing_required_field(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
        """,
        )
        result = validate_plugin(plugin_dir)
        assert not result.ok

    def test_unknown_top_level_key(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
            bogus = "surprise"
        """,
        )
        result = validate_plugin(plugin_dir)
        assert not result.ok

    def test_missing_models_dir_when_models_declared(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
                manifest_version = "0"
                plugin_version = "0.1.0"
                slug = "test"
                name = "Test"

                [models]
                widget = "test_plugin.models.widget.Widget"
            """,
        )
        result = validate_plugin(plugin_dir)
        assert not result.ok
        # May fail at manifest-parse (load_manifest checks dirs) or convention-dirs
        failed = [c for c in result.checks if c.status == "fail"]
        assert len(failed) >= 1

    def test_no_models_dir_ok_when_no_models_declared(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
        """,
        )
        result = validate_plugin(plugin_dir)
        assert result.ok, result.to_human()

    def test_missing_grift_dir_when_grift_declared(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
                manifest_version = "0"
                plugin_version = "0.1.0"
                slug = "test"
                name = "Test"

                [grift]
                seed = "grift/seed.grift.json"
            """,
        )
        # No grift/ directory — manifest parse should fail
        result = validate_plugin(plugin_dir)
        assert not result.ok


# ---------------------------------------------------------------------------
# Summary and output
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summary_counts(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
        """,
        )
        result = validate_plugin(plugin_dir)
        s = result.summary
        assert s["checks_total"] == len(result.checks)
        assert s["checks_total"] > 0
        assert s["checks_passed"] + s["checks_warned"] + s["checks_failed"] == s["checks_total"]

    def test_json_round_trips(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
        """,
        )
        result = validate_plugin(plugin_dir)
        doc = json.loads(result.to_json())
        assert doc["ok"] is True
        assert doc["level"] == "structure"
        assert "checks" in doc
        assert "summary" in doc


# ---------------------------------------------------------------------------
# Loads-level tests (require Django app registry)
# ---------------------------------------------------------------------------


class TestLoadsLevel:
    # The editor-classes / search-callables loads checks only fire for a plugin
    # that DECLARES editors + searches — lotr is the only such plugin, so that
    # path is covered by lotr's own manifest self-test
    # (plugins/lotr/tap_plugin/lotr/tests/test_lotr_manifest.py). Here we cover the model path
    # with aws_core + administrivia.

    @requires_plugins("validation_sample")
    def test_aws_core_loads_passes(self):
        result = validate_plugin(FIXTURE_ROOT, level="loads")
        assert result.ok, result.to_human()
        model_check = next(c for c in result.checks if c.id == "model-classes")
        assert model_check.status == "pass"
        # One info per registered model. Count is NOT pinned: aws_core grows
        # toward the full set (task #23), so a hardcoded literal is brittle
        # by construction (it was `== 37`; aws_core is already at 40). Presence,
        # not a pinned count, is the invariant.
        info_msgs = [m for m in model_check.messages if m.severity == "info"]
        assert info_msgs
        assert all(m.text.startswith("Model ") for m in info_msgs)

    @requires_plugins("validation_sample")
    def test_administrivia_loads_passes(self):
        result = validate_plugin(FIXTURE_ROOT, level="loads")
        assert result.ok, result.to_human()

    @requires_plugins("validation_sample")
    def test_loads_includes_structure_checks(self):
        result = validate_plugin(FIXTURE_ROOT, level="loads")
        check_ids = {c.id for c in result.checks}
        # Structure checks should still be present
        assert "plugin-root" in check_ids
        assert "core-files" in check_ids
        assert "manifest-parse" in check_ids


# ---------------------------------------------------------------------------
# Runs-level tests (require Django + database)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@requires_plugins("validation_sample")  # every test here runs level="runs" on aws_core (imports the package)
class TestRunsLevel:
    # grift-import runs coverage against a real grift lives in lotr's manifest
    # self-test (plugins/lotr/tap_plugin/lotr/tests/test_lotr_manifest.py); aws_core covers the
    # create-nodes / create-edges runs path here.

    def test_aws_core_runs_passes(self):
        result = validate_plugin(FIXTURE_ROOT, level="runs")
        assert result.ok, result.to_human()
        node_check = next(c for c in result.checks if c.id == "create-nodes")
        assert node_check.status == "pass"
        # Every model's create_node succeeds. Presence, not a pinned count
        # (aws_core grows — task #23; this was `== 37`, already 40). The
        # check status == "pass" is the real invariant.
        ok_msgs = [m for m in node_check.messages if "OK" in m.text]
        assert ok_msgs
        assert all(m.text.startswith("create_node(") for m in ok_msgs)

    def test_runs_includes_loads_and_structure(self):
        result = validate_plugin(FIXTURE_ROOT, level="runs")
        check_ids = {c.id for c in result.checks}
        # Structure checks
        assert "plugin-root" in check_ids
        assert "manifest-parse" in check_ids
        # Loads checks
        assert "model-classes" in check_ids
        # Runs checks
        assert "create-nodes" in check_ids

    def test_runs_rollback_leaves_no_data(self):
        """Verify that runs-level validation doesn't persist any entities."""
        from tap_grid.models import Entity

        count_before = Entity.objects.count()
        result = validate_plugin(FIXTURE_ROOT, level="runs")
        assert result.ok, result.to_human()
        count_after = Entity.objects.count()
        assert count_after == count_before

    def test_runs_json_output(self):
        result = validate_plugin(FIXTURE_ROOT, level="runs")
        doc = json.loads(result.to_json())
        assert doc["ok"] is True
        assert doc["level"] == "runs"


# ---------------------------------------------------------------------------
# Identity-coherence + declared-dependencies checks (package-mode)
# ---------------------------------------------------------------------------


def _make_package_mode_plugin(
    tmp_path: Path,
    *,
    slug: str = "widget",
    dist_name: str | None = None,
    ep_key: str | None = None,
    ep_target: str | None = None,
    segment: str | None = None,
    include_pyproject: bool = True,
    package_files: dict[str, str] | None = None,
    depends_on: str = "",
) -> Path:
    """Create a package-mode plugin tree: ``<root>/tap_plugin/<segment>/`` + ``pyproject.toml``.

    Defaults produce a coherent plugin; override the ``dist_name``/``ep_key``/``ep_target``/
    ``segment`` args to inject a specific identity-chain break.
    """
    dist_name = dist_name if dist_name is not None else f"tap-plugin-{slug.replace('_', '-')}"
    ep_key = ep_key if ep_key is not None else slug
    ep_target = ep_target if ep_target is not None else f"tap_plugin.{slug}.apps:WidgetConfig"
    segment = segment if segment is not None else slug

    root = tmp_path / f"pkg_{slug}"
    pkg = root / "tap_plugin" / segment
    pkg.mkdir(parents=True)
    (pkg / "tap-plugin.toml").write_text(textwrap.dedent(f"""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "{slug}"
            name = "Widget"
            {depends_on}
            """))
    (pkg / "__init__.py").write_text("")
    (pkg / "apps.py").write_text(
        "from tap_plugins.base import TapPluginConfig\n\n\nclass WidgetConfig(TapPluginConfig):\n    pass\n"
    )
    if package_files:
        for rel_path, content in package_files.items():
            full = pkg / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
    if include_pyproject:
        (root / "pyproject.toml").write_text(textwrap.dedent(f"""\
                [project]
                name = "{dist_name}"
                version = "0.1.0"

                [project.entry-points."tap.plugins"]
                {ep_key} = "{ep_target}"
                """))
    return root


def _check(result, check_id):
    return next(c for c in result.checks if c.id == check_id)


class TestIdentityCoherence:
    def test_coherent_package_mode_passes(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path)
        result = validate_plugin(root)
        assert _check(result, "identity-coherence").status == "pass", result.to_human()

    def test_real_plugin_has_identity_check(self):
        result = validate_plugin(FIXTURE_ROOT)
        assert _check(result, "identity-coherence").status == "pass", result.to_human()

    def test_legacy_flat_layout_is_inapplicable_not_failed(self, tmp_path):
        plugin_dir = _make_plugin(
            tmp_path,
            toml="""\
            manifest_version = "0"
            plugin_version = "0.1.0"
            slug = "test"
            name = "Test"
            """,
        )
        check = _check(validate_plugin(plugin_dir), "identity-coherence")
        assert check.status == "pass"
        assert any("not applicable" in m.text for m in check.messages)

    def test_wrong_distribution_name_fails(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path, slug="widget", dist_name="widget")
        result = validate_plugin(root)
        assert result.ok is False
        assert _check(result, "identity-coherence").status == "fail"

    def test_entry_point_key_not_slug_fails(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path, slug="widget", ep_key="gadget")
        assert _check(validate_plugin(root), "identity-coherence").status == "fail"

    def test_entry_point_target_wrong_namespace_fails(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path, slug="widget", ep_target="tap_plugin.gadget.apps:WidgetConfig")
        assert _check(validate_plugin(root), "identity-coherence").status == "fail"

    def test_namespace_segment_mismatch_fails(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path, slug="widget", segment="gadget")
        assert _check(validate_plugin(root), "identity-coherence").status == "fail"

    def test_missing_pyproject_fails(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path, include_pyproject=False)
        assert _check(validate_plugin(root), "identity-coherence").status == "fail"


class TestDeclaredDependencies:
    def test_no_dependencies_passes(self, tmp_path):
        root = _make_package_mode_plugin(tmp_path)
        assert _check(validate_plugin(root), "declared-dependencies").status == "pass"

    def test_real_plugin_deps_pass(self):
        result = validate_plugin(FIXTURE_ROOT)
        assert _check(result, "declared-dependencies").status == "pass", result.to_human()

    def test_undeclared_import_fails(self, tmp_path):
        root = _make_package_mode_plugin(
            tmp_path,
            slug="widget",
            package_files={"collector.py": "from tap_plugin.gadget.models import Thing\n"},
        )
        result = validate_plugin(root)
        assert result.ok is False
        check = _check(result, "declared-dependencies")
        assert check.status == "fail"
        assert any("gadget" in m.text for m in check.messages)

    def test_declared_import_passes(self, tmp_path):
        root = _make_package_mode_plugin(
            tmp_path,
            slug="widget",
            depends_on='depends_on = [{ slug = "gadget" }]',
            package_files={"collector.py": "from tap_plugin.gadget.models import Thing\n"},
        )
        assert _check(validate_plugin(root), "declared-dependencies").status == "pass"

    def test_declared_but_unimported_is_pass(self, tmp_path):
        # Pure data/vocabulary dependency: declared, never imported. Legitimate.
        root = _make_package_mode_plugin(
            tmp_path,
            slug="widget",
            depends_on='depends_on = [{ slug = "grid_fixtures" }]',
        )
        check = _check(validate_plugin(root), "declared-dependencies")
        assert check.status == "pass"
        assert any("not imported" in m.text for m in check.messages)
