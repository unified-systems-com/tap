"""Static-typing (mypy) ceiling ratchet — freeze the baseline, block new errors.

TAP-IMPLEMENTS: req-dev-validation-mypy-ratchet@fa630990c5bc/09ec6f90dc32 (enforcement) —
    the per-file+error-code ceiling ratchet over the strict-mode baseline.

`strict = true` is set in pyproject but nothing gated on it, so mypy drifted to
~1200 errors — overwhelmingly django-stubs friction (Django's dynamic ORM: `.objects`,
`._meta`, subclass fields via `BaseModel`) and test-fixture `no-untyped-call` cascade,
NOT latent bugs (an audit of the only crash-risk bucket, `union-attr`, found the
production cases are `hasattr`-guarded false positives). Driving that to zero is a
~1200-line, near-zero-correctness diff. The value is forward: freeze the set so a NEW
error — new untyped code, or a genuine new `union-attr` — fails at authoring time.

Keyed by `path:code:count` (per file, per error-code, with the count), deliberately
NOT by line number: an edit that shifts lines does not churn the baseline, but adding
an error bumps a count → a new `:count` key fails and the old one goes stale (both
teeth). Known limitation (named, per the honest-risk discipline): fixing one error and
introducing another of the *same code in the same file* leaves the count unchanged and
is not caught — an acceptable blind spot given the surface is ~all noise. Regenerate
the baseline with `manage.py guards --sync-mypy` (see the command) after a real change.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import ClassVar

from tap.guards.base import REPO_ROOT, CeilingRatchet

BASELINE_PATH = Path(__file__).resolve().parent / "baselines" / "mypy.txt"

# mypy emits `path:line:col: error: message  [code]` (line/col optional). Path has no
# colon; capture the file and the trailing `[code]`. Lines without a `[code]` are rare
# and counted under "no-code".
_ERROR_LINE = re.compile(r"^(?P<path>[^:]+):(?:\d+:)?(?:\d+:)? error: .*?(?:\[(?P<code>[a-z-]+)\])?\s*$")


def mypy_error_counts() -> dict[str, int]:
    """Run `mypy .` and aggregate errors to `{f"{path}:{code}": count}`.

    Raises if mypy could not run (rc >= 2 — e.g. a config/resolution crash), so a
    broken run fails loudly instead of measuring an empty set that reads as "all fixed".
    """
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode >= 2:
        raise AssertionError(
            f"mypy did not complete (rc={proc.returncode}) — a config or resolution error, not a type "
            f"error. Fix the invocation before trusting the ratchet:\n{proc.stdout}\n{proc.stderr}"
        )
    counts: Counter[str] = Counter()
    for line in proc.stdout.splitlines():
        m = _ERROR_LINE.match(line)
        if m:
            counts[f"{m.group('path')}:{m.group('code') or 'no-code'}"] += 1
    return dict(counts)


class MypyRatchet(CeilingRatchet):
    slug = "mypy-static-typing"
    map_row = "Static typing (mypy)"
    rid = "req-dev-validation-mypy-ratchet"
    description = (
        "pyproject sets mypy strict=true but nothing gates on it, so it drifted to ~1200 errors (mostly "
        "django-stubs friction + test-fixture cascade, not bugs). This freezes that baseline per "
        "file+error-code and fails on any NEW error — so new untyped code and genuine new None-access "
        "bugs are caught at authoring time — while the recorded debt ratchets down as files are cleaned."
    )
    baseline_path: ClassVar[Path] = BASELINE_PATH
    new_hint = (
        "A new mypy error appeared. Fix it (annotate the def, guard the Optional, correct the type). If it "
        "is unavoidable django-stubs friction, a narrow `# type: ignore[<code>]` on the line is acceptable. "
        "Only regenerate the baseline (`manage.py guards --sync-mypy`) for a legitimate, reviewed change."
    )

    def measure(self) -> set[str]:
        return {f"{key}:{count}" for key, count in mypy_error_counts().items()}

    def check(self) -> None:
        # Install-aware ratchet. `mypy .` + the django-stubs plugin introspect
        # INSTALLED_APPS, so a focused stack (fewer plugins installed) resolves plugin
        # models differently and its measured error set diverges from the frozen
        # (full-install) baseline — a false red on entries for plugins that simply are
        # not here. Filter BOTH the measured set and the baseline to core paths + paths
        # of installed plugins, so the ratchet compares like-for-like over whatever this
        # stack actually has; the all-plugins CI lane (test_all installs everything)
        # filters nothing and enforces the full set. Mirrors tap.plugin_testing.
        # requires_plugins + req-dev-validation-all-plugins-lane; a step toward the
        # per-owner baselines in spec-tap-plugin-validation-distribution.
        from tap.guards.base import ratchet_ceiling, read_baseline_set
        from tap.plugin_testing import installed_plugin_slugs

        installed = set(installed_plugin_slugs())

        def _relevant(entry: str) -> bool:
            # entry is "path:code:count"; the path (no colon) is segment 0. Keep core
            # paths; keep a plugins/<slug>/… path only when <slug> is installed here.
            parts = entry.split(":", 1)[0].split("/")
            if len(parts) >= 2 and parts[0] == "plugins":
                return parts[1] in installed
            return True

        ratchet_ceiling(
            current={e for e in self.measure() if _relevant(e)},
            baseline={e for e in read_baseline_set(self.baseline_path) if _relevant(e)},
            surface=self.map_row,
            baseline_path=self.baseline_path,
            new_hint=self.new_hint,
        )
