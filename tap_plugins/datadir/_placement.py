"""Where a plugin's data directory lives, and whether it may live there at all.

`tap_plugins/specs/spec-tap-plugin-data-directory.md`: the root (`req-tap-plugin-datadir-root`)
and the mount gate's table (`req-tap-plugin-datadir-mount-gate`). Two roots exist. The volume root
is the operator's, named by ``settings.TAP_PLUGIN_DATA_ROOT`` and optional. The ephemeral root is
core's, fixed, inside the container's own filesystem, and only ever holds caches, and only when no
volume is enabled.

|                         | no plugin declares | a plugin declares cache | a plugin declares state |
| volume not enabled      | boots              | boots, ephemeral        | aborts, naming it       |
| volume enabled, usable  | boots              | boots, on the volume    | boots, on the volume    |
| volume enabled, broken  | aborts             | aborts                  | aborts                  |

A cache never falls back to the ephemeral root because an enabled volume failed its test.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap.volume_mount import VolumeVerdict, check_volume

#: The ephemeral root: one constant, under the runtime user's data directory, never configurable by a
#: plugin and never on the configured volume (req-tap-plugin-datadir-root-5). Everything in it is lost
#: when the container is recreated, and that is its stated contract.
EPHEMERAL_ROOT = Path.home() / ".local" / "share" / "tap" / "plugin-data-ephemeral"

#: Names directly under a root that belong to core. Every name core reserves under a root or inside a
#: plugin directory begins with this prefix, apart from CACHEDIR.TAG.
RESERVED_PREFIX = ".tap-"
LOCKS_DIRNAME = ".tap-locks"

#: Per-process memo of the volume verdict: the write probe is not repeated on every accessor call
#: (req-tap-plugin-datadir-accessor). Keyed by the root so a test that changes the setting is not
#: served a stale answer.
_VERDICTS: dict[str, VolumeVerdict] = {}


class PluginDataDirectoryError(Exception):
    """A plugin data directory cannot be handed out or provisioned; the message says why."""


def volume_root() -> Path | None:
    """The configured volume root, or ``None`` when the plugin data volume is not enabled."""
    from django.conf import settings

    raw = getattr(settings, "TAP_PLUGIN_DATA_ROOT", "") or ""
    return Path(raw) if raw else None


def volume_verdict(*, fresh: bool = False) -> VolumeVerdict | None:
    """The mount test's verdict on the volume root, memoised per process; ``None`` when not enabled.

    Boot passes ``fresh=True``: a gate must test the disk as it is now, not as it was when the
    process started.
    """
    root = volume_root()
    if root is None:
        return None
    key = str(root)
    if fresh or key not in _VERDICTS:
        _VERDICTS[key] = _overlap_with_file_store(root) or check_volume(root)
    return _VERDICTS[key]


def _overlap_with_file_store(root: Path) -> VolumeVerdict | None:
    """Refuse a plugin data root that is, or nests with, the file store's root.

    Two volumes by ruling (req-tap-plugin-datadir-scope-2): a backup treats them differently and an
    operator may size them apart, which one directory inside the other would silently defeat.
    """
    from tap_files.store import configured_root

    files_root = configured_root()
    if files_root is None:
        return None
    raw = str(files_root)
    mine, theirs = Path(os.path.realpath(root)), Path(os.path.realpath(raw))
    if mine == theirs or mine.is_relative_to(theirs) or theirs.is_relative_to(mine):
        return VolumeVerdict(
            False,
            "overlaps_file_store",
            f"{root} and the file store root {raw} are the same directory or one contains the other; "
            "they must be separate volumes",
        )
    return None


def reset_verdicts() -> None:
    """Forget the memoised verdicts (tests, and after a purge recreates nothing that matters)."""
    _VERDICTS.clear()


def volume_refusal(root: Path | None, verdict: VolumeVerdict) -> str:
    """The one wording of "the configured volume failed its test", shared by the gate and the accessor."""
    return f"plugin data volume {root} failed the mount test ({verdict.check}): {verdict.reason}"


@dataclass(frozen=True)
class Placement:
    """The mount gate's decision for one declared directory."""

    slug: str
    #: The root the directory lives under, or ``None`` when it may not be placed anywhere.
    root: Path | None
    ephemeral: bool
    #: Why it cannot be placed; empty when ``root`` is set.
    refusal: str = ""

    @property
    def path(self) -> Path | None:
        return None if self.root is None else self.root / self.slug


def place(slug: str, durability: str, *, fresh: bool = False) -> Placement:
    """Apply the mount gate's table to one declaration.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-root@42b5bc3acb7f/35e13d466ab3 (derivation) — which of the two
        roots a directory lands under is decided here and nowhere else.
    """
    verdict = volume_verdict(fresh=fresh)
    root = volume_root()
    if verdict is None:
        if durability == "state":
            return Placement(
                slug,
                None,
                False,
                f'plugin {slug!r} declares a "state" data directory, and the plugin data volume is not '
                "enabled (TAP_PLUGIN_DATA_ROOT is unset); state cannot be placed where it will be thrown away",
            )
        return Placement(slug, EPHEMERAL_ROOT, True)
    if not verdict.usable:
        return Placement(slug, None, False, volume_refusal(root, verdict))
    assert root is not None  # nosec B101 — a verdict exists only for a configured root
    return Placement(slug, root, False)


def declared_directories() -> dict[str, tuple[Any, str]]:
    """Every loaded plugin that declares a directory: ``slug -> (declaration, plugin_version)``.

    Read from the app registry's loaded manifests, the same source the plugin report uses, so the
    gate, the accessor, the report and the probe agree on what is installed.
    """
    from django.apps import apps

    from tap_plugins.base import TapPluginConfig

    found: dict[str, tuple[Any, str]] = {}
    for config in apps.get_app_configs():
        if not isinstance(config, TapPluginConfig):
            continue
        manifest = config.manifest
        declaration = getattr(manifest, "data_directory", None) if manifest is not None else None
        if declaration is not None:
            found[config.label] = (declaration, manifest.plugin_version)
    return dict(sorted(found.items()))


__all__ = [
    "EPHEMERAL_ROOT",
    "LOCKS_DIRNAME",
    "Placement",
    "PluginDataDirectoryError",
    "RESERVED_PREFIX",
    "declared_directories",
    "place",
    "reset_verdicts",
    "volume_refusal",
    "volume_root",
    "volume_verdict",
]
