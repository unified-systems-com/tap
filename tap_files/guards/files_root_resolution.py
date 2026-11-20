"""File store root single-source guard — `req-tap-files-root` (`-root-1`) and `req-tap-files-interface-1`.

`TAP_FILES_ROOT` is read from the environment in `tap/settings.py` and nowhere else; the setting is
read in `tap_files/config.py` and nowhere else; and no Python code names the compose mount
path. So the only way to a path under the store root is through the store, which is what lets every
write follow the write path and every read be verified. Needles are assembled by concatenation so
this module never matches its own scan.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import is_excluded_dir

_NAME = "TAP_FILES" + "_ROOT"
_ENV_READS = (f'environ.get("{_NAME}"', f'environ["{_NAME}"]', f'getenv("{_NAME}"')
_SETTING_READS = (f'"{_NAME}"', f"settings.{_NAME}")
_MOUNT_LITERAL = "/var/lib/tap/" + "files"

_ALLOWED: dict[str, tuple[str, ...]] = {
    "tap/settings.py": (*_ENV_READS, f'"{_NAME}"'),
    "tap_files/config.py": _SETTING_READS,
}
_OWN_PATH = "tap_files/guards/files_root_resolution.py"


def _python_files() -> list[str]:
    rels: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if is_excluded_dir(rel, extra=frozenset({"_dev-plugins"})) or "tests" in rel.parts:
            continue
        if path.is_file():
            rels.append(rel.as_posix())
    return rels


class FilesRootResolutionGuard(Guard):
    slug = "files-root-resolution"
    map_row = "File store root single source"
    rid = "req-tap-files-root"
    description = (
        "Every path under the file store root must come from the store: TAP_FILES_ROOT is read from the "
        "environment in tap/settings.py only, the setting is read in tap_files/config.py only, and no Python code "
        "names the compose mount path. A second reader could write outside the write path or read without "
        "verifying, which is exactly what the store exists to prevent."
    )

    def check(self) -> None:
        """Fail on any read of the root setting or the mount path outside the allowed modules.

        TAP-IMPLEMENTS: req-tap-files-scope@7d9ec33c456a/af301a402300 (enforcement) — one store: no module but the store's
            own config reaches the root, so every byte under it follows the store's write and read paths.
        """
        needles = (*_ENV_READS, *_SETTING_READS, _MOUNT_LITERAL)
        violations: list[str] = []
        for rel in _python_files():
            if rel == _OWN_PATH:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            allowed = _ALLOWED.get(rel, ())
            violations.extend(f"{rel}: {n!r}" for n in needles if n in text and n not in allowed)
        assert not violations, (  # nosec B101
            f"File store root read outside its homes ({len(violations)}):\n  "
            + "\n  ".join(violations)
            + "\n\nUse tap_files.config.configured_root() or the gateway, tap_files.services (req-tap-files-root, req-tap-files-interface-1)."
        )
