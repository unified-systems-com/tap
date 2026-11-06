"""Run a browser-runtime check under Node against the vendored cytoscape (`tap_viz/tests/js/*.mjs`).

Each harness prints one JSON line per check, `{"check": ..., "ok": ..., "detail": ...}`. The runtime image
carries no Node and the vendored cytoscape arrives at image build, so `run_harness` SKIPS where either is
missing; `TAP_NODE` and `TAP_CYTOSCAPE_JS` name them when they are not on the default path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "tap_viz" / "static" / "tap_viz" / "js" / "runtime"
JS_TESTS = Path(__file__).resolve().parent / "js"
_VENDORED_CYTOSCAPE = REPO / "tap_viz" / "static" / "tap_viz" / "js" / "lib" / "cytoscape.min.js"


def run_harness(script: str, module: Path) -> dict[str, dict[str, object]]:
    node = os.environ.get("TAP_NODE") or shutil.which("node")
    cytoscape = Path(os.environ.get("TAP_CYTOSCAPE_JS") or _VENDORED_CYTOSCAPE)
    if not node or not cytoscape.is_file():
        pytest.skip("needs Node and the vendored cytoscape (TAP_NODE / TAP_CYTOSCAPE_JS)")
    done = subprocess.run(  # noqa: S603  # nosec B603  # nosemgrep - fixed argv, repo-owned harness
        [node, str(JS_TESTS / script), str(cytoscape), str(module)],  # nosemgrep
        capture_output=True,
        text=True,
        check=False,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    checks = {row["check"]: row for row in map(json.loads, filter(None, done.stdout.splitlines()))}
    assert checks, f"the harness printed no checks: {done.stdout!r} {done.stderr[-500:]!r}"
    return checks


def assert_ok(checks: dict[str, dict[str, object]], *names: str) -> None:
    for name in names:
        assert name in checks, f"harness did not report {name!r}; it reported {sorted(checks)}"
        assert checks[name]["ok"], f"{name}: {checks[name]['detail']}"
