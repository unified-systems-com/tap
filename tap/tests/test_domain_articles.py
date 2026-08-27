"""Unit tests for the domain-article scanner (`specs/spec-domain-articles.md`).

The guard itself is exercised by `tap/tests/test_guards.py::test_guard_holds`, but on the
core repository it runs over zero in-repo plugins and so proves nothing about the
measurement. These tests build synthetic owner roots so every tooth — missing article,
missing section, unpinned source, undocumented field — is shown to bite.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tap.domain_articles import (
    DIMENSION_SECTIONS,
    EDGE_SECTIONS,
    NODE_SECTIONS,
    SOURCE_KEYS,
    article_path,
    baseline_path_for,
    edge_subjects,
    finding_key,
    findings_for_root,
    node_subjects,
    plugin_roots,
    subjects_for_root,
)

_MODEL = '''\
"""A fixture model."""

from typing import Any, ClassVar

_SCHEMA: dict[str, Any] = {"full_name": {"type": "string"}, "state": {"type": "string"}}


class Widget:
    ENTITY_TYPE: ClassVar[str] = "acme__widget"
    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = _SCHEMA
'''

_INLINE_MODEL = """\
from typing import Any, ClassVar


class Gadget:
    ENTITY_TYPE: ClassVar[str] = "acme__gadget"
    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {"serial": {"type": "string"}}
"""


def _article(
    sections: tuple[str, ...], *, fields: str = "", prior_art: str = "- Example, v2.1 — https://example.test/spec"
) -> str:
    """A minimal conforming article body over `sections`."""
    out = ["# Fixture\n"]
    for name in sections:
        out.append(f"## {name}\n")
        if name == "Authoritative Source":
            out.extend(f"- **{key}:** placeholder\n" for key in SOURCE_KEYS)
        elif name == "Prior Art":
            out.append(prior_art + "\n")
        elif name == "Fields":
            out.append(fields + "\n")
        else:
            out.append("Body.\n")
    return "\n".join(out)


@pytest.fixture
def owner(tmp_path: Path) -> Path:
    """An owner root declaring one node type (schema by module constant) and one edge."""
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "widget.py").write_text(_MODEL, encoding="utf-8")
    (root / "edges").mkdir()
    (root / "edges" / "USES.edge.json").write_text(json.dumps({"slug": "USES__acme", "name": "Uses"}), encoding="utf-8")
    return root


@pytest.mark.spec("req-domain-articles-layer-1")
def test_subjects_are_named_by_their_owner_local_stem(owner: Path):
    """A node drops its `<owner>__` prefix, an edge its `__<owner>` suffix."""
    by_slug = {s.slug: s for s in subjects_for_root(owner)}
    assert by_slug["acme__widget"].stem == "widget"
    assert by_slug["USES__acme"].stem == "USES"
    assert article_path(owner, by_slug["acme__widget"]) == owner / "domain" / "widget.md"


@pytest.mark.spec("req-domain-articles-coverage-2")
def test_field_set_resolves_through_a_module_level_constant(owner: Path):
    """A schema hoisted to a module constant must not read as zero fields (a false green)."""
    (node,) = node_subjects(owner)
    assert node.fields == {"full_name", "state"}


@pytest.mark.spec("req-domain-articles-coverage-2")
def test_field_set_reads_an_inline_schema(tmp_path: Path):
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gadget.py").write_text(_INLINE_MODEL, encoding="utf-8")
    (node,) = node_subjects(root)
    assert node.fields == {"serial"}


@pytest.mark.spec("req-domain-articles-coverage-1")
def test_missing_article_is_a_finding_per_subject(owner: Path):
    problems = {(f.subject.slug, f.problem) for f in findings_for_root(owner)}
    assert problems == {("acme__widget", "missing-article"), ("USES__acme", "missing-article")}


@pytest.mark.spec("req-domain-articles-coverage-1")
def test_conforming_articles_leave_no_findings(owner: Path):
    domain = owner / "domain"
    domain.mkdir()
    (domain / "widget.md").write_text(
        _article(NODE_SECTIONS, fields="- `full_name` — the owner/name pair.\n- `state` — active or disabled."),
        encoding="utf-8",
    )
    (domain / "USES.md").write_text(_article(EDGE_SECTIONS), encoding="utf-8")
    assert findings_for_root(owner) == []


@pytest.mark.spec("req-domain-articles-coverage-2")
def test_an_undocumented_field_is_a_finding(owner: Path):
    """The load-bearing tooth: a field with no paragraph reds, one field at a time."""
    domain = owner / "domain"
    domain.mkdir()
    (domain / "widget.md").write_text(_article(NODE_SECTIONS, fields="- `full_name` — explained."), encoding="utf-8")
    (domain / "USES.md").write_text(_article(EDGE_SECTIONS), encoding="utf-8")
    assert [f.problem for f in findings_for_root(owner)] == ["undocumented-field:state"]


@pytest.mark.spec("req-domain-articles-sections-1")
def test_a_missing_section_is_a_finding_naming_the_section(owner: Path):
    domain = owner / "domain"
    domain.mkdir()
    kept = tuple(s for s in EDGE_SECTIONS if s != "Boundaries")
    (domain / "USES.md").write_text(_article(kept), encoding="utf-8")
    problems = {f.problem for f in findings_for_root(owner) if f.subject.kind == "edge"}
    assert "missing-section:Boundaries" in problems


@pytest.mark.spec("req-domain-articles-sections-1")
def test_a_subheading_does_not_end_its_section(owner: Path):
    """An article is free to subdivide; only `##` starts a new section."""
    domain = owner / "domain"
    domain.mkdir()
    body = _article(NODE_SECTIONS, fields="### Naming\n\n- `full_name` — explained.\n- `state` — explained.")
    (domain / "widget.md").write_text(body, encoding="utf-8")
    (domain / "USES.md").write_text(_article(EDGE_SECTIONS), encoding="utf-8")
    assert findings_for_root(owner) == []


@pytest.mark.spec("req-domain-articles-sections-2")
def test_an_unpinned_authoritative_source_is_a_finding_per_key(owner: Path):
    domain = owner / "domain"
    domain.mkdir()
    body = _article(EDGE_SECTIONS).replace("- **Version:** placeholder\n", "")
    (domain / "USES.md").write_text(body, encoding="utf-8")
    problems = {f.problem for f in findings_for_root(owner) if f.subject.kind == "edge"}
    assert "authoritative-source-missing:Version" in problems
    assert "authoritative-source-missing:Source" not in problems


@pytest.mark.spec("req-domain-articles-sections-3")
def test_a_bare_prior_art_url_is_a_finding(owner: Path):
    domain = owner / "domain"
    domain.mkdir()
    (domain / "USES.md").write_text(
        _article(EDGE_SECTIONS, prior_art="- Example — https://example.test/spec"), encoding="utf-8"
    )
    problems = {f.problem for f in findings_for_root(owner) if f.subject.kind == "edge"}
    assert "prior-art-unpinned" in problems


@pytest.mark.spec("req-domain-articles-coverage-3")
def test_finding_key_is_repo_relative_and_carries_the_problem(tmp_path: Path):
    """The baseline key names a real repo-relative path and a drift-proof problem id."""
    root = tmp_path / "plugins" / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gadget.py").write_text(_INLINE_MODEL, encoding="utf-8")
    (finding,) = findings_for_root(root)
    assert finding_key(finding, tmp_path) == ("plugins/acme/domain/gadget.md::node:acme__gadget::missing-article")


@pytest.mark.spec("req-domain-articles-coverage-3")
def test_baseline_lives_inside_the_owner_package(tmp_path: Path):
    """Debt travels with the plugin, so eviction never strands a central row."""
    root = tmp_path / "plugins" / "acme"
    assert baseline_path_for(root) == root / "guards" / "baselines" / "domain_articles.txt"


@pytest.mark.spec("req-domain-articles-coverage-1")
def test_plugin_roots_covers_plugins_and_excludes_apps(tmp_path: Path):
    """Owners are plugin roots only — `tap_*` apps model TAP's own furniture."""
    app = tmp_path / "tap_thing"
    app.mkdir()
    (app / "apps.py").write_text("", encoding="utf-8")
    flat = tmp_path / "plugins" / "flatplug"
    flat.mkdir(parents=True)
    (flat / "tap-plugin.toml").write_text("", encoding="utf-8")
    pkg = tmp_path / "plugins" / "pkgplug" / "tap_plugin" / "pkgplug"
    pkg.mkdir(parents=True)
    (pkg / "tap-plugin.toml").write_text("", encoding="utf-8")
    assert set(plugin_roots(tmp_path)) == {flat, pkg}


@pytest.mark.spec("req-domain-articles-coverage-1")
def test_a_malformed_edge_json_is_skipped_not_crashed(tmp_path: Path):
    """A broken manifest is the edge-registration guard's problem, not this scanner's."""
    root = tmp_path / "acme"
    (root / "edges").mkdir(parents=True)
    (root / "edges" / "BROKEN.edge.json").write_text("{not json", encoding="utf-8")
    assert edge_subjects(root) == []


def test_unparseable_source_is_skipped(tmp_path: Path):
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "bad.py").write_text("class ??", encoding="utf-8")
    assert node_subjects(root) == []


@pytest.mark.spec("req-domain-articles-layer-1")
def test_the_repository_fixture_plugin_scans(tmp_path: Path):
    """A real in-tree plugin package shape (the validate_plugin fixture) resolves end-to-end."""
    from tap.guards.base import REPO_ROOT

    root = REPO_ROOT / "tap_plugins" / "tests" / "fixtures" / "validation_sample" / "tap_plugin" / "validation_sample"
    stems = {s.stem for s in subjects_for_root(root)}
    assert {"sample_node", "SAMPLE_LINK"} <= stems
    node = next(s for s in subjects_for_root(root) if s.slug == "validation_sample__sample_node")
    assert node.fields == {"name", "description"}


@pytest.mark.spec("req-domain-articles-coverage-1")
def test_an_article_with_no_type_behind_it_is_a_finding(owner: Path):
    """The symmetric check: an article left behind by a removed type reads as current."""
    domain = owner / "domain"
    domain.mkdir()
    (domain / "widget.md").write_text(
        _article(NODE_SECTIONS, fields="- `full_name` — explained.\n- `state` — explained."), encoding="utf-8"
    )
    (domain / "USES.md").write_text(_article(EDGE_SECTIONS), encoding="utf-8")
    (domain / "removed_thing.md").write_text(_article(NODE_SECTIONS), encoding="utf-8")
    (finding,) = findings_for_root(owner)
    assert finding.problem == "orphan-article"
    assert finding.subject.kind == "orphan"


def test_an_owner_with_no_domain_dir_scans_cleanly(tmp_path: Path):
    """A plugin that has written no articles yet reports missing ones, never a crash."""
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gadget.py").write_text(_INLINE_MODEL, encoding="utf-8")
    assert [f.problem for f in findings_for_root(root)] == ["missing-article"]


# --- dimensions ---------------------------------------------------------------

_DIMS_MODEL = """\
from typing import Any, ClassVar

SHARED: dict[str, Any] = {"acme.surface": "widgets"}


class Gizmo:
    ENTITY_TYPE: ClassVar[str] = "acme__gizmo"
    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {"serial": {"type": "string"}}
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = SHARED
"""


def _dim_owner(tmp_path: Path) -> Path:
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gizmo.py").write_text(_DIMS_MODEL, encoding="utf-8")
    return root


@pytest.mark.spec("req-domain-articles-layer-4")
def test_a_dimension_key_owes_an_article_in_its_own_subdirectory(tmp_path: Path):
    """A dotted dimension key lives under `domain/dimensions/`, never beside type stems."""
    root = _dim_owner(tmp_path)
    (dim,) = [s for s in subjects_for_root(root) if s.kind == "dimension"]
    assert dim.slug == "acme.surface"
    assert article_path(root, dim) == root / "domain" / "dimensions" / "acme.surface.md"


@pytest.mark.spec("req-domain-articles-coverage-4")
def test_an_undocumented_dimension_value_is_a_finding(tmp_path: Path):
    root = _dim_owner(tmp_path)
    (root / "domain" / "dimensions").mkdir(parents=True)
    (root / "domain" / "gizmo.md").write_text(
        _article(NODE_SECTIONS, fields="- `serial` — explained."), encoding="utf-8"
    )
    (root / "domain" / "dimensions" / "acme.surface.md").write_text(_article(DIMENSION_SECTIONS), encoding="utf-8")
    assert [f.problem for f in findings_for_root(root)] == ["undocumented-value:widgets"]


@pytest.mark.spec("req-domain-articles-coverage-6")
def test_dimensions_resolve_through_an_import_rather_than_reading_as_empty(tmp_path: Path):
    """`tap_web` imports its dimensions from a sibling module; without the hop it reads as zero."""
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gizmo.py").write_text(
        "from typing import Any, ClassVar\n"
        "from acme.dimensions import ACME_DIMENSIONS\n\n\n"
        "class Gizmo:\n"
        '    ENTITY_TYPE: ClassVar[str] = "acme__gizmo"\n'
        "    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = ACME_DIMENSIONS\n",
        encoding="utf-8",
    )
    (root / "dimensions.py").write_text('ACME_DIMENSIONS = {"acme.graph": "widgets"}\n', encoding="utf-8")
    dims = [s for s in subjects_for_root(root) if s.kind == "dimension"]
    assert [(d.slug, sorted(d.fields or ())) for d in dims] == [("acme.graph", ["widgets"])]


@pytest.mark.spec("req-domain-articles-coverage-6")
def test_an_unresolvable_declaration_is_reported_not_assumed_empty(tmp_path: Path):
    """A false green is worse than a failure: unresolvable terms must not read as zero."""
    root = tmp_path / "acme"
    (root / "models").mkdir(parents=True)
    (root / "models" / "gizmo.py").write_text(
        "from typing import Any, ClassVar\n"
        "from somewhere.far.away import MYSTERY\n\n\n"
        "class Gizmo:\n"
        '    ENTITY_TYPE: ClassVar[str] = "acme__gizmo"\n'
        "    FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = MYSTERY\n",
        encoding="utf-8",
    )
    (root / "domain").mkdir()
    (root / "domain" / "gizmo.md").write_text(_article(NODE_SECTIONS), encoding="utf-8")
    assert [f.problem for f in findings_for_root(root)] == ["unresolvable-declaration"]


@pytest.mark.spec("req-domain-articles-coverage-5")
def test_an_edge_must_account_for_every_dimension_it_stamps(owner: Path):
    """The drift that actually happened: an article asserting the opposite of its manifest."""
    (owner / "edges" / "USES.edge.json").write_text(
        json.dumps({"slug": "USES__acme", "default_dimensions": {"acme.observation": "declaration"}}),
        encoding="utf-8",
    )
    domain = owner / "domain"
    domain.mkdir()
    (domain / "widget.md").write_text(
        _article(NODE_SECTIONS, fields="- `full_name` — explained.\n- `state` — explained."), encoding="utf-8"
    )
    (domain / "USES.md").write_text(_article(EDGE_SECTIONS), encoding="utf-8")
    (domain / "dimensions").mkdir()
    (domain / "dimensions" / "acme.observation.md").write_text(_article(DIMENSION_SECTIONS), encoding="utf-8")
    problems = {f.problem for f in findings_for_root(owner)}
    assert "undocumented-dimension:acme.observation" in problems


@pytest.mark.spec("req-domain-articles-sections-4")
def test_a_term_may_be_written_with_or_without_its_value(owner: Path):
    """`acme.observation: declaration` accounts for the key as surely as the bare key does."""
    (owner / "edges" / "USES.edge.json").write_text(
        json.dumps({"slug": "USES__acme", "default_dimensions": {"acme.observation": "declaration"}}),
        encoding="utf-8",
    )
    domain = owner / "domain"
    domain.mkdir()
    (domain / "widget.md").write_text(
        _article(NODE_SECTIONS, fields="- `full_name` — explained.\n- `state` — explained."), encoding="utf-8"
    )
    edge = _article(EDGE_SECTIONS).replace(
        "## Endpoints\n\nBody.", "## Endpoints\n\n- **Dimensions:** `acme.observation: declaration`."
    )
    (domain / "USES.md").write_text(edge, encoding="utf-8")
    (domain / "dimensions").mkdir()
    (domain / "dimensions" / "acme.observation.md").write_text(
        _article(DIMENSION_SECTIONS, fields=""), encoding="utf-8"
    )
    problems = {f.problem for f in findings_for_root(owner)}
    assert "undocumented-dimension:acme.observation" not in problems


@pytest.mark.spec("req-domain-articles-coverage-7")
def test_an_orphan_dimension_article_is_a_finding(tmp_path: Path):
    root = tmp_path / "acme"
    (root / "domain" / "dimensions").mkdir(parents=True)
    (root / "domain" / "dimensions" / "acme.gone.md").write_text(_article(DIMENSION_SECTIONS), encoding="utf-8")
    (finding,) = findings_for_root(root)
    assert finding.problem == "orphan-article"
    assert "dimension key" in finding.detail


@pytest.mark.spec("req-domain-articles-layer-4")
def test_apps_owe_dimension_articles_but_not_type_articles(tmp_path: Path):
    """`types=False` is the `tap_*` app case: furniture is exempt, vocabulary is not."""
    root = _dim_owner(tmp_path)
    kinds = {s.kind for s in subjects_for_root(root, types=False)}
    assert kinds == {"dimension"}
