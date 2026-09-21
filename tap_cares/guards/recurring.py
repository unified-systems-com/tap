"""Recurring-task uniqueness guard — `req-tap-cares-task-backend-recurring-scope-4`.

Exactly one Steady Queue `@recurring` decoration may exist (the TAP scheduler tick);
every other scheduling need routes through an on-grid `Schedule` entity, never a new
code-level recurring task.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard

_RECURRING_SCAN_ROOTS = (
    "tap_cares",
    "tap_grid",
    "tap_plugins",
    "tap_api",
    "tap_web",
    "tap_viz",
    "plugins",
)


class RecurringUniquenessGuard(Guard):
    slug = "recurring-uniqueness"
    map_row = "Recurring-task uniqueness"
    rid = "req-tap-cares-task-backend-recurring-scope-4"
    description = (
        "Steady Queue's @recurring decorator is permitted for exactly one task — the TAP scheduler tick. "
        "Every other scheduling need must route through an on-grid Schedule entity (auditable, FLIP-able), "
        "not a new code-level recurring task. This asserts there is exactly one @recurring callsite."
    )

    def check(self) -> None:
        callsites: list[str] = []
        for root in _RECURRING_SCAN_ROOTS:
            root_path = REPO_ROOT / root
            if not root_path.is_dir():
                continue
            for path in root_path.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                rel = str(path.relative_to(REPO_ROOT))
                for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                    if line.lstrip().startswith("@recurring("):
                        callsites.append(f"{rel}:{lineno}: {line.lstrip()}")

        assert len(callsites) == 1, (
            f"Expected exactly one @recurring callsite (the TAP scheduler tick in "
            f"tap_cares/task_backend.py), found {len(callsites)}:\n  "
            + "\n  ".join(callsites)
            + "\n\nAdditional recurring tasks belong on the TAP grid as Schedule entities, not as "
            "@recurring decorators (req-tap-cares-task-backend-recurring-scope-4)."
        )
        assert (
            "tap_cares/task_backend.py" in callsites[0]
        ), f"Expected the @recurring callsite to live in tap_cares/task_backend.py; got {callsites[0]}"
