"""validate_plugin's author-time mirror of tap_grid.E004 (Issue# 583 - tap).

A model's OUTBOUND_EDGES / INBOUND_EDGES / CONTAINMENT_EDGES must name edge types the
plugin's own manifest, core, or a declared dependency defines. The predicate is
`tap.edge_declarations.unresolved`, shared with the boot-time check; here the
declarations are read statically from the plugin's models.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tap_plugins.manifest import load_manifest
from tap_plugins.tests.test_validate_service import _MIN_TOML, _make_plugin, _named_check
from tap_plugins.validate.service import ValidationResult, _check_edge_declarations


def _edge_file(slug: str) -> str:
    return json.dumps({"slug": slug, "name": slug.replace("_", " ").title(), "description": f"fixture edge {slug}"})


def _plugin(
    tmp_path: Path, model_body: str, *, edges: tuple[str, ...] = ("LINKS__test_plugin",), depends_on: str = ""
) -> Path:
    toml = _MIN_TOML + depends_on + "[edges]\n" + "".join(f'{slug} = "edges/{slug}.edge.json"\n' for slug in edges)
    files = {f"edges/{slug}.edge.json": _edge_file(slug) for slug in edges}
    files["models.py"] = model_body
    return _make_plugin(tmp_path, toml=toml, extra_files=files)


def _run(plugin_dir: Path) -> ValidationResult:
    result = ValidationResult(ok=True, level="structure", plugin_path=str(plugin_dir), strict=False)
    _check_edge_declarations(plugin_dir, load_manifest(plugin_dir), result)
    return result


MODEL = """
class Thing:
    ENTITY_TYPE = "test_plugin__thing"
    OUTBOUND_EDGES = [{"nodes": [{"type": "test_plugin__thing"}], "edges": [{"type": "%s"}]}]
    CONTAINMENT_EDGES = ("%s",)
"""


@pytest.mark.spec("req-tap-plugin-validate-codepaths-4")
class TestEdgeDeclarationsCheck:
    def test_declarations_that_resolve_pass(self, tmp_path: Path) -> None:
        result = _run(_plugin(tmp_path, MODEL % ("LINKS__test_plugin", "LINKS__test_plugin")))
        check = _named_check(result, "edge-declarations")
        assert check.status == "pass"
        assert any("resolve" in line.text for line in check.messages)

    def test_a_core_edge_resolves(self, tmp_path: Path) -> None:
        result = _run(_plugin(tmp_path, MODEL % ("PRODUCED_BATCH", "LINKS__test_plugin")))
        assert _named_check(result, "edge-declarations").status == "pass"

    def test_a_renamed_edge_fails_naming_model_attribute_and_slug(self, tmp_path: Path) -> None:
        """The definition was renamed to LINKS; the model still says LINK."""
        result = _run(_plugin(tmp_path, MODEL % ("LINK__test_plugin", "LINK__test_plugin")))
        check = _named_check(result, "edge-declarations")
        assert check.status == "fail"
        texts = [line.text for line in check.messages if line.severity == "error"]
        assert len(texts) == 2
        assert all("test_plugin__thing" in t and "'LINK__test_plugin'" in t for t in texts)
        assert "OUTBOUND_EDGES" in texts[0] and "CONTAINMENT_EDGES" in texts[1]
        assert all(
            line.path and line.path.startswith("models.py:") for line in check.messages if line.severity == "error"
        )

    def test_another_plugins_edge_without_depends_on_fails_as_an_undeclared_dependency(self, tmp_path: Path) -> None:
        result = _run(_plugin(tmp_path, MODEL % ("OWNS_REPO__github_core", "LINKS__test_plugin")))
        check = _named_check(result, "edge-declarations")
        assert check.status == "fail"
        [text] = [line.text for line in check.messages if line.severity == "error"]
        assert "not in depends_on" in text and "github_core" in text

    def test_a_declared_but_uninstalled_dependencys_edge_is_informational(self, tmp_path: Path) -> None:
        deps = 'depends_on = [{ slug = "not_installed_anywhere" }]\n'
        result = _run(
            _plugin(tmp_path, MODEL % ("OWNS_X__not_installed_anywhere", "LINKS__test_plugin"), depends_on=deps)
        )
        check = _named_check(result, "edge-declarations")
        assert check.status == "pass"
        assert any("unverifiable" in line.text for line in check.messages)

    def test_no_tap_plugin_namespace_at_all_reads_as_not_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The conformance lane's tooling venv holds no plugin, so `tap_plugin` itself does not
        import and find_spec on a dotted name raises instead of answering None (Issue# 666 - tap,
        found on PR# 154 - tap-plugin-github-core). That is the not-installed case, not a crash."""
        import importlib.util
        from importlib.machinery import ModuleSpec

        real = importlib.util.find_spec

        def no_namespace(name: str, package: str | None = None) -> ModuleSpec | None:
            if name.startswith("tap_plugin."):
                raise ModuleNotFoundError("No module named 'tap_plugin'", name="tap_plugin")
            return real(name, package)

        monkeypatch.setattr(importlib.util, "find_spec", no_namespace)
        deps = 'depends_on = [{ slug = "git_core" }]\n'
        result = _run(_plugin(tmp_path, MODEL % ("OWNS_REPO__git_core", "LINKS__test_plugin"), depends_on=deps))
        check = _named_check(result, "edge-declarations")
        assert check.status == "pass"
        assert any("unverifiable" in line.text and "git_core" in line.text for line in check.messages)

    def test_a_broken_namespace_still_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Codex on PR# 667 - tap: only the absent `tap_plugin` namespace reads as not-installed;
        an import error from INSIDE an installed namespace is a defect and must surface."""
        import importlib.util
        from importlib.machinery import ModuleSpec

        def broken_inside(name: str, package: str | None = None) -> ModuleSpec | None:
            raise ModuleNotFoundError(
                "No module named 'tap_plugin.git_core.something'", name="tap_plugin.git_core.something"
            )

        monkeypatch.setattr(importlib.util, "find_spec", broken_inside)
        deps = 'depends_on = [{ slug = "git_core" }]\n'
        with pytest.raises(ModuleNotFoundError):
            _run(_plugin(tmp_path, MODEL % ("OWNS_REPO__git_core", "LINKS__test_plugin"), depends_on=deps))

    def test_a_declared_installed_dependencys_edge_resolves(self, tmp_path: Path) -> None:
        """grid_fixtures is installed on every core stack; its wildcard edge resolves through depends_on."""
        deps = 'depends_on = [{ slug = "grid_fixtures" }]\n'
        result = _run(_plugin(tmp_path, MODEL % ("PG_LINKS__grid_fixtures", "LINKS__test_plugin"), depends_on=deps))
        assert _named_check(result, "edge-declarations").status == "pass"

    def test_a_non_literal_declaration_warns_instead_of_passing_silently(self, tmp_path: Path) -> None:
        body = 'class T:\n    ENTITY_TYPE = "test_plugin__t"\n    OUTBOUND_EDGES = build()\n'
        check = _named_check(_run(_plugin(tmp_path, body)), "edge-declarations")
        assert check.status == "warn"
        assert any("not a literal" in line.text for line in check.messages)

    def test_a_plugin_with_no_declarations_gets_no_check(self, tmp_path: Path) -> None:
        result = _run(_plugin(tmp_path, "class T:\n    ENTITY_TYPE = 'test_plugin__t'\n"))
        assert [c.id for c in result.checks] == []
