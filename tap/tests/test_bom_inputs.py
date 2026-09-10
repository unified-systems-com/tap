"""The BOM inputs are declared once and every consumer derives from them (tap#379).

Spec: specs/spec-dev-validation.md (req-dev-validation-product-line-lanes-9, req-dev-validation-bom-lane-2).

Proven here: every declared pattern classifies `boot` (drop one from the classifier and this is red);
the boot's real read set is covered by the declaration (a new install input cannot appear unnamed);
a change under a record's editable path is `boot`; inert paths are not; and every uv-cache
`hashFiles(...)` in the workflows is exactly the declared resolution inputs — the generated fragment,
checked, because YAML cannot read the declaration at expression time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tap.bom_inputs import BOM_INPUTS, RESOLUTION_INPUTS, hashfiles_expression, is_bom_input, record_source_paths

REPO_ROOT = Path(__file__).resolve().parents[2]

# One concrete path per declared pattern: the drop-one test.
EXAMPLES: dict[str, str] = {
    "uv.lock": "uv.lock",
    "pyproject.toml": "pyproject.toml",
    "boot/*.boot.json": "boot/core_ci.boot.json",
    "**/boot/*.boot.json": "tap_plugins/tests/fixtures/x/tap_plugin/x/boot/ci.boot.json",
    "docker/Dockerfile*": "docker/Dockerfile",
    "docker/entrypoint.sh": "docker/entrypoint.sh",
    "docker/build-openssl-fips.sh": "docker/build-openssl-fips.sh",
    "docker/openssl-release-keys.asc": "docker/openssl-release-keys.asc",
    "docker-compose*.yml": "docker-compose.ci.yml",
    ".env": ".env",
    "tap/preboot.py": "tap/preboot.py",
    "tap_boot/**": "tap_boot/schemas/boot.schema.json",
}

# What the boot actually reads or executes (the coverage fixture): each must be declared, so a
# new install-time input cannot be added without naming it here AND in the declaration.
BOOT_READ_SET = [
    "boot/test_all.boot.json",
    "uv.lock",
    "pyproject.toml",
    "docker/entrypoint.sh",
    "docker/Dockerfile",
    "docker/build-openssl-fips.sh",
    "docker/openssl-release-keys.asc",
    "docker-compose.yml",
    ".env",
    "tap/preboot.py",
    "tap_boot/schemas/boot.schema.json",
]


def test_every_declared_pattern_has_an_example_and_classifies_boot() -> None:
    assert set(EXAMPLES) == set(BOM_INPUTS), "declare an example for every pattern (and vice versa)"
    for pattern, path in EXAMPLES.items():
        assert is_bom_input(path), f"{path} should be `boot` via {pattern}"


@pytest.mark.parametrize("pattern", BOM_INPUTS)
def test_dropping_one_pattern_loses_its_example(pattern: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex/tap#379 F2: removing a declared input from the classifier turns its example inert."""
    import tap.bom_inputs as mod

    remaining = tuple(p for p in BOM_INPUTS if p != pattern)
    monkeypatch.setattr(mod, "BOM_INPUTS", remaining)
    path = EXAMPLES[pattern]
    others = [p for p in remaining if mod._match(path, p)]
    if not others:  # the example is covered by this pattern alone
        assert not mod.is_bom_input(path)


def test_the_boots_read_set_is_declared() -> None:
    undeclared = [p for p in BOOT_READ_SET if not is_bom_input(p)]
    assert undeclared == [], f"boot reads these but the declaration does not name them: {undeclared}"


def test_resolution_inputs_are_a_subset_of_bom_inputs() -> None:
    assert set(RESOLUTION_INPUTS) <= set(BOM_INPUTS)


def test_inert_paths_are_not_boot() -> None:
    for path in (
        "docs/doc-x.md",
        "specs/spec-x.md",
        "tap_web/views.py",
        "README.md",
        ".github/workflows/x.yml",
        "scripts/test",
    ):
        assert not is_bom_input(path, REPO_ROOT), path


def test_editable_record_path_is_boot(tmp_path: Path) -> None:
    """Codex/tap#379 F3: a record's editable/path source is unpinned, so a change under it boots differently."""
    (tmp_path / "boot").mkdir()
    rec = {
        "install": {"plugins": [{"slug": "s", "enabled": True, "source": {"type": "editable", "path": "fixtures/s"}}]}
    }
    (tmp_path / "boot" / "x.boot.json").write_text(json.dumps(rec))
    assert record_source_paths(tmp_path) == ["fixtures/s"]
    assert is_bom_input("fixtures/s/tap_plugin/s/models.py", tmp_path)
    assert not is_bom_input("fixtures/other/models.py", tmp_path)


def test_real_records_editable_paths_resolve() -> None:
    """The repo's own records name the validation_sample fixture editable; a change there is `boot`."""
    sources = record_source_paths(REPO_ROOT)
    assert any(s.endswith("validation_sample") for s in sources), sources
    assert is_bom_input(
        "tap_plugins/tests/fixtures/validation_sample/tap_plugin/validation_sample/__init__.py", REPO_ROOT
    )


_HASHFILES = re.compile(r"hashFiles\(([^)]*)\)")


def test_workflow_cache_keys_hash_exactly_the_declared_resolution_inputs() -> None:
    """The generated fragment, checked: every uv-cache key in the workflows hashes RESOLUTION_INPUTS."""
    expected = hashfiles_expression()
    seen = 0
    for wf in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for line in wf.read_text().splitlines():
            if "uv-ci-" not in line:
                continue
            for args in _HASHFILES.findall(line):
                seen += 1
                assert args.strip() == expected, f"{wf.name}: hashFiles({args}) != hashFiles({expected})"
    assert seen >= 3, "expected the uv-cache keys in product-lines, bom-boot and api-fuzz"
