"""Structure-level plugin validation must import WITHOUT Django.

The per-repo CI conformance job (`.github/workflows/plugin-ci.yml`,
`req-tap-plugin-extdev-repo-ci`) is the admission gate every plugin repo — ours and external
developers' — runs. It deliberately runs on a bare runner with only `jsonschema` and
`packaging` installed: no core `uv sync`, no Django, no database. That is what makes it
fast enough to run on every push in a dozen repos.

That property was previously only a COMMENT. It drifted: `_check_identity_coherence`
imported three constants from `tap.preboot`, which imports `tap.plugin_source_auth` ->
`tap.runtime_secrets` -> `tap.registry` -> Django. Nothing noticed, because the workflow
that would have caught it had never successfully compiled. When it finally ran, a
conformant plugin failed with `ModuleNotFoundError: No module named 'django'` — an error
naming the PLUGIN for a defect in CORE, which is the worst possible place to point a
plugin author.

This test enforces the property the CI job depends on. It runs in a SUBPROCESS with an
import hook that makes `import django` fail, because Django is necessarily importable in
this test environment — checking `sys.modules` in-process would prove nothing.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Block Django at the meta-path, import the structure-validation entry point, and
# actually RUN it against a real plugin — importability alone would miss a lazy import
# on the execution path.
_PROBE = textwrap.dedent("""
    import sys

    class _NoDjango:
        def find_module(self, name, path=None):
            return self.find_spec(name, path)

        def find_spec(self, name, path=None, target=None):
            if name == "django" or name.startswith("django."):
                raise ModuleNotFoundError(
                    f"No module named {name!r} (blocked: the conformance gate must be Django-free)"
                )
            return None

    sys.meta_path.insert(0, _NoDjango())

    from pathlib import Path

    from tap_plugins.validate.service import validate_plugin

    result = validate_plugin(Path(sys.argv[1]), level="structure", strict=True)
    print("OK" if result.ok else "VALIDATION_FAILED", result.to_human())
    """)


def _fixture_plugin() -> Path:
    return REPO_ROOT / "tap_plugins" / "tests" / "fixtures" / "validation_sample"


def test_structure_validation_runs_without_django() -> None:
    """The exact operation the per-repo CI conformance job performs."""
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(_fixture_plugin())],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "Structure-level validate_plugin can no longer run without Django. Something on "
        "the structure path grew an import that reaches Django (the usual culprit is "
        "importing from tap.preboot instead of tap.plugin_identity). The per-repo CI "
        f"conformance job installs no Django, so this breaks every plugin repo.\n\n"
        f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
    )
    assert "OK" in proc.stdout, f"validation did not pass: {proc.stdout}\n{proc.stderr}"


def test_probe_actually_blocks_django() -> None:
    """Guard the guard — a probe that silently permits Django would test nothing."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            _PROBE.replace("from tap_plugins.validate.service", "import django\n    from tap_plugins.validate.service"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0, "the Django-blocking import hook is not actually blocking Django"


def test_identity_module_imports_no_third_party() -> None:
    """tap.plugin_identity is the stdlib-only leaf the whole arrangement rests on."""
    source = (REPO_ROOT / "tap" / "plugin_identity.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and not line.startswith("from __future__")
    ]
    assert not offenders, f"tap/plugin_identity.py must import nothing but the standard library; found: {offenders}"


def test_preboot_still_exports_the_identity_symbols() -> None:
    """Moving the definitions must not shrink preboot's declared public surface."""
    from tap import preboot

    for symbol in ("NAMESPACE_PACKAGE", "TAP_PLUGINS_ENTRY_POINT_GROUP", "dist_name_for_slug"):
        assert symbol in preboot.__all__, f"{symbol} dropped from tap.preboot.__all__"
        assert hasattr(preboot, symbol), f"{symbol} no longer importable from tap.preboot"
