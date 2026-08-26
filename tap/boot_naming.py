"""Boot-profile file naming + settings-free profile-reading facts.

The one spelling of ``<profile_id>.boot.json``, and the one home of profile facts
every runtime floor's raw reader must agree on (``step_enabled``).

Stdlib-only leaf (the ``tap/secret_naming.py`` shape): the path grammar for boot
profiles is derived here once and consumed on every runtime floor — the
host-runnable stage-0 tools (``tap/boot_pointer.py``, ``tap/dev_workspace.py``),
the settings-free pre-boot readers (``tap/preboot.py``, ``tap/crypto_bom.py``),
the settings-time reader (``tap_auth/boot.py``), and the in-Django loader
(``tap_boot/profile.py``).

The *root* (which ``boot/`` directory) deliberately stays with each caller:
``tap_boot`` derives it from ``settings.BASE_DIR``, the pre-Django readers from
``__file__``, and stage-0 tools from a caller-supplied worktree — so the shared
fact is the last hop only. The inverse (filename → id) is
``tap.jsonfiles.instance_id(path, role="boot")`` for in-Django callers; the
stdlib-only boot tools slice with ``RECORD_SUFFIX`` since they cannot import
``tap.jsonfiles`` (it pulls jsonschema at module scope).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

# The boot-record / boot-profile filename suffix (role "boot" in the JSON-files
# naming convention, req-tap-json-naming).
RECORD_SUFFIX: Final[str] = ".boot.json"


def profile_filename(profile_id: str) -> str:
    """The basename of a boot profile file: ``<profile_id>.boot.json``."""
    return f"{profile_id}{RECORD_SUFFIX}"


def step_enabled(entry: dict[str, Any]) -> bool:
    """Whether a profile install/population entry is enabled — **absent = disabled**.

    The schema requires ``enabled`` on every entry and the validated loader is
    strict, but two raw readers legitimately bypass the schema (pre-Django
    ``tap.preboot`` by design; ``tap_boot.profile_install_slugs`` over discovered
    profiles). They historically defaulted in OPPOSITE directions (install-nothing
    vs count-as-present) — a divergence a spawn-supplied unvalidated profile could
    hit. Fail-closed is the only safe default for a security-load-bearing install
    set: an entry that doesn't say ``enabled: true`` installs nothing.
    """
    return bool(entry.get("enabled", False))


def profile_path(boot_dir: Path, profile_id: str) -> Path:
    """The path of profile ``profile_id`` inside ``boot_dir``.

    ``boot_dir`` is the caller's own root derivation (settings.BASE_DIR-based,
    ``__file__``-based, or a stage-0 worktree) — see the module docstring.
    """
    return boot_dir / profile_filename(profile_id)
