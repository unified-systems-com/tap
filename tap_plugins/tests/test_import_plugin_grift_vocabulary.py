"""`import_plugin_grift` imports the dimension vocabulary first (req-tap-plugin-load-v0-upsert-7).

aws-build Q69b, unified-systems-com/tap#1188: names resolve from live Dimension rows, so on a grid boot
has not reached, a plugin bundle that stamps a dimension fails with UnknownDimension. The command runs
boot's own vocabulary op before the plugin's bundles.
"""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.core.management import CommandError, call_command

pytestmark = [pytest.mark.spec("req-tap-plugin-load-v0-upsert-7"), pytest.mark.django_db]

_TEST_DIMENSION_SEED = (
    Path(__file__).resolve().parents[2] / "tap_grid" / "tests" / "data" / "test_dimensions.grift.json"
)
_PROBE_BATCH = "01a1e99d-78ec-75a9-bbfa-8725577d62c8"
_PROBE_NODE = "01a1e99d-78ec-75a9-bbfa-8726857be602"
_CORE_TAP_GRAPH = "tap.graph"

_MANIFEST = """\
manifest_version = "0"
plugin_version = "0.0.1"
slug = "vocab_probe"
name = "Vocabulary Probe"
description = "Test plugin: one bundle whose node stamps core's tap.graph dimension."

[grift]
seed = "grift/seed.grift.json"
"""


def _probe_document() -> dict[str, Any]:
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {
                    "entity_id": _PROBE_BATCH,
                    "entity_type": "batch",
                    "name": "vocab_probe seed",
                    "dimensions": {},
                },
                "batch_node": {
                    "source": "vocab_probe",
                    "name": "vocab_probe seed",
                    "description": "One node stamping a core dimension.",
                },
                "nodes": [
                    {
                        "entity": {
                            "entity_id": _PROBE_NODE,
                            "entity_type": "grid_fixtures__constrained_source",
                            "name": "Probe",
                            "dimensions": {_CORE_TAP_GRAPH: "probe"},
                        },
                        "node": {"name": "Probe", "description": "Stamps tap.graph."},
                    }
                ],
                "edges": [],
            }
        ],
    }


@pytest.fixture
def probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """An installed plugin, `vocab_probe`, whose one bundle stamps core's `tap.graph`."""
    import tap_plugins.seeding as seeding
    from tap_plugins.manifest import load_manifest

    (tmp_path / "grift").mkdir()
    (tmp_path / "tap-plugin.toml").write_text(_MANIFEST, encoding="utf-8")
    (tmp_path / "grift" / "seed.grift.json").write_text(json.dumps(_probe_document()), encoding="utf-8")
    plugin = SimpleNamespace(manifest=load_manifest(tmp_path), name="vocab_probe")
    real = seeding.all_tap_plugins()
    monkeypatch.setattr(seeding, "all_tap_plugins", lambda: [*real, plugin])
    return plugin


def _vocabulary_batch_ids() -> list[str]:
    from tap_plugins.seeding import dimension_bundles

    paths = [b.path for b in dimension_bundles()] + [_TEST_DIMENSION_SEED]
    ids: list[str] = []
    for path in paths:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        ids += [batch["batch_entity"]["entity_id"] for batch in document["batches"]]
    return ids


@pytest.fixture
def fresh_grid() -> None:
    """The grid as it stands before boot: no Dimension rows, and no batch that imported them."""
    from tap_grid.models import Batch, Dimension, Entity

    Dimension.all_objects.all().delete()
    Entity.objects.filter(entity_type="dimension").delete()
    batch_ids = _vocabulary_batch_ids()
    Batch.all_objects.filter(entity_id__in=batch_ids).delete()
    Entity.objects.filter(pk__in=batch_ids).delete()  # the batches' spine rows
    assert not Dimension.all_objects.exists()
    assert not Entity.objects.filter(pk__in=batch_ids).exists()


def _run(*args: str) -> str:
    out = StringIO()
    call_command("import_plugin_grift", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def test_a_fresh_grid_refuses_the_bundle_without_the_vocabulary(probe: Any, fresh_grid: None) -> None:
    """The precondition the command fixes: the plugin's bundle alone fails on a fresh grid."""
    from tap_plugins.seeding import seed_plugin

    outcomes = seed_plugin(probe, actor=None)
    assert [o.ok for o in outcomes] == [False]


def test_the_command_imports_the_vocabulary_then_the_plugin_on_a_fresh_grid(probe: Any, fresh_grid: None) -> None:
    from tap_grid.dimension_names import resolve
    from tap_grid.models import Entity

    output = _run("vocab_probe")
    assert "Dimension vocabulary:" in output and "imported" in output, output
    node = Entity.objects.get(pk=_PROBE_NODE)
    assert node.dimensions[str(resolve(_CORE_TAP_GRAPH))]["v"] == "probe"


def test_a_re_run_writes_no_vocabulary(probe: Any, fresh_grid: None) -> None:
    from tap_grid.models import Batch, Dimension

    _run("vocab_probe")
    counts = (Dimension.all_objects.count(), Batch.all_objects.count())
    output = _run("vocab_probe")
    assert (Dimension.all_objects.count(), Batch.all_objects.count()) == counts
    assert "already present" in output, output


def test_a_dry_run_imports_no_vocabulary(probe: Any, fresh_grid: None) -> None:
    from tap_grid.models import Dimension

    _run("vocab_probe", "--dry-run")
    assert not Dimension.all_objects.exists()


def test_a_broken_vocabulary_bundle_stops_the_command_naming_it(
    probe: Any, fresh_grid: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tap_plugins.seeding as seeding
    from tap_grid.models import Entity

    bad = tmp_path / "broken.grift.json"
    bad.write_text("{ not json", encoding="utf-8")
    real = seeding.dimension_bundles
    broken = seeding.DimensionBundle("vocab_probe", "vocab_probe/dimension (broken)", bad)
    monkeypatch.setattr(seeding, "dimension_bundles", lambda: [*real(), broken])
    with pytest.raises(CommandError, match=r"Dimension vocabulary bundle vocab_probe/dimension \(broken\) did not"):
        _run("vocab_probe")
    assert not Entity.objects.filter(pk=_PROBE_NODE).exists()
