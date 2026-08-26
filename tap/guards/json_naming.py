"""JSON-filename convention guard — `spec-tap-json-files.md` (`req-tap-json-naming`).

TAP-IMPLEMENTS: req-tap-json-naming@b4fbca7dc1af/4db993fbae1c (enforcement) — the guard
    that fails a TAP-owned JSON file outside the three filename patterns.

Every TAP-owned `.json` file's name must declare its role: discovered data/config
`<name>.<role>.json` (role in {boot, secret, grift, edge, gridkin}), singleton app
config `<app>.<name>.json`, or a schema `<type>.schema.json`. A non-conforming name
is a violation unless baselined in `_json_file_baseline.txt`, which ratchets down.

The diff (new violations, stale baseline) is done inside `scan_json_files`, so this
is a `Guard` wrapping the scanner's own ratchet rather than a `CeilingRatchet`.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard

_ROOTS = [
    REPO_ROOT / name
    for name in (
        "tap",
        "tap_grid",
        "tap_plugins",
        "tap_api",
        "tap_web",
        "tap_viz",
        "tap_ai",
        "tap_cares",
        "tap_auth",
        "tap_boot",
        "plugins",
        "boot",
    )
]


class JsonNamingGuard(Guard):
    slug = "json-file-naming"
    map_row = "JSON-file naming"
    rid = "req-tap-json-naming"
    description = (
        "A JSON file whose name doesn't declare its role is undiscoverable by the role-keyed loaders "
        "(boot profiles, grift bundles, edge/gridkin/secret files) and hides its purpose from a reader. "
        "This flags every non-conforming name and ratchets the baseline of grandfathered ones toward zero."
    )

    def check(self) -> None:
        from tap.jsonfiles import DEFAULT_BASELINE, scan_json_files

        result = scan_json_files(_ROOTS, baseline_path=DEFAULT_BASELINE)
        messages: list[str] = []
        if result.new_violations:
            listing = "\n  ".join(str(p) for p in result.new_violations)
            messages.append(
                f"JSON files whose names don't declare their purpose ({len(result.new_violations)}):\n  "
                + listing
                + "\n\nName discovered data/config `<name>.<role>.json` (role in "
                "{boot, secret, grift, edge, gridkin}), singleton app config `<app>.<name>.json`, and "
                "schemas `<type>.schema.json` (spec-tap-json-files.md req-tap-json-naming). If a file "
                "genuinely cannot be renamed now, append its repo-relative path to "
                "tap/tests/_json_file_baseline.txt — last resort only."
            )
        if result.stale_baseline:
            listing = "\n  ".join(result.stale_baseline)
            messages.append(
                f"Baseline entries that no longer exist ({len(result.stale_baseline)}):\n  "
                + listing
                + "\n\nRemove these lines from tap/tests/_json_file_baseline.txt — they have been renamed "
                "or deleted. The baseline ratchets down."
            )
        assert not messages, "\n\n".join(messages)
