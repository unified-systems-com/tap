"""Plugin data root single-source guard — `req-tap-plugin-datadir-root` (`-root-1`).

`TAP_PLUGIN_DATA_ROOT` is read from the environment in `tap/settings.py` and nowhere else, and no
path literal stands in for it: with the variable unset the setting is empty, which means "no
volume", and a plugin asks `tap_plugins.data_dir()` rather than building the path itself. The
pattern is the secrets root's (`secrets-root-resolution`), and the reason is the same: an entry
point that re-derives where data lives can land it somewhere the gate never tested. Needles are
assembled by concatenation so this module never matches its own scan.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard
from tap.source_scan import is_excluded_dir

_ENV_NAME = "TAP_PLUGIN_DATA" + "_ROOT"
_ENV_READ_NEEDLES = (
    f'environ.get("{_ENV_NAME}"',
    f'environ["{_ENV_NAME}"]',
    f'getenv("{_ENV_NAME}"',
)
#: The compose mount path. It belongs to docker-compose.yml and the Dockerfile; Python code that
#: names it is deriving the location instead of reading the setting.
_MOUNT_LITERAL = "/var/lib/tap/" + "plugin-data"

_ALLOWED: dict[str, tuple[str, ...]] = {"tap/settings.py": _ENV_READ_NEEDLES}
_OWN_PATH = "tap_plugins/guards/plugin_data_root_resolution.py"


def _python_files() -> list[str]:
    rels: list[str] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        # A nested dev-plugin checkout is another repository with its own CI (see the
        # secrets-root guard for the full reasoning).
        if is_excluded_dir(rel, extra=frozenset({"_dev-plugins"})) or "tests" in rel.parts:
            continue
        if path.is_file():
            rels.append(rel.as_posix())
    return rels


class PluginDataRootResolutionGuard(Guard):
    slug = "plugin-data-root-resolution"
    map_row = "Plugin data root single source"
    rid = "req-tap-plugin-datadir-root"
    description = (
        "Where plugin data lives must not be re-derived per entry point: TAP_PLUGIN_DATA_ROOT is read in "
        "tap/settings.py only, with no default, and no Python code names the compose mount path. A plugin "
        "asks tap_plugins.data_dir() for its directory, so the mount gate's verdict covers every path handed out."
    )

    def check(self) -> None:
        needles = (*_ENV_READ_NEEDLES, _MOUNT_LITERAL)
        violations: list[str] = []
        for rel in _python_files():
            if rel == _OWN_PATH:
                continue
            text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")
            allowed = _ALLOWED.get(rel, ())
            violations.extend(f"{rel}: {needle!r}" for needle in needles if needle in text and needle not in allowed)
        assert not violations, (  # nosec B101
            f"Plugin data root resolution restated outside tap/settings.py ({len(violations)}):\n  "
            + "\n  ".join(violations)
            + "\n\nRead settings.TAP_PLUGIN_DATA_ROOT, or ask tap_plugins.data_dir(slug) (req-tap-plugin-datadir-root)."
        )
