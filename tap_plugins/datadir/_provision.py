"""Core creates a declared directory; the plugin never does (`req-tap-plugin-datadir-provision`).

``<root>/<slug>/``, created ``0700``, with core's description file and, for a cache, the standard
cache tag. Idempotent: an existing directory with the right owner is left exactly as it is, apart
from core's own files when the declaration changed. Core refuses rather than repairs: a symbolic
link, a non-directory or a directory owned by someone else fails provisioning with the path and
the fact found, and core does not follow the link, replace the file or change ownership.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import stat
import subprocess  # nosec B404 — one fixed argv: the core-written probe script, never a shell
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tap.jsonfiles import JsonFileError, load_json_file
from tap.plugin_identity import valid_slug
from tap_plugins.datadir._placement import RESERVED_PREFIX, PluginDataDirectoryError

DESCRIPTION_FILENAME = ".tap-plugin-dir.json"
DESCRIPTION_FORMAT_VERSION = 1
DESCRIPTION_SCHEMA = Path(__file__).resolve().parent.parent / "schemas" / "plugin-data-directory.schema.json"

CACHE_TAG_FILENAME = "CACHEDIR.TAG"
#: The Cache Directory Tagging Specification's signature: exactly these 43 octets open the file.
CACHE_TAG_SIGNATURE = b"Signature: 8a477f597d28d172789f06886806bc55"
CACHE_TAG_CONTENT = (
    CACHE_TAG_SIGNATURE + b"\n"
    b"# This file is a cache directory tag created by TAP for a plugin data directory\n"
    b'# declared "cache": everything here can be fetched or rebuilt.\n'
    b"# For information about cache directory tags, see https://bford.info/cachedir/\n"
)

logger = logging.getLogger(__name__)

EXEC_PROBE_PREFIX = RESERVED_PREFIX + "exec-probe-"
_EXEC_PROBE_TIMEOUT_S = 10


def check_slug(slug: str) -> None:
    """Refuse a slug that is not safe as one directory name, before any filesystem call."""
    if not valid_slug(slug):
        raise PluginDataDirectoryError(f"{slug!r} is not a valid plugin slug ([a-z0-9_]+)")


def describe(path: Path) -> str:
    """What is at *path*, for an error: ``""`` when it is a directory this process owns."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(st.st_mode):
        return "is a symbolic link"
    if not stat.S_ISDIR(st.st_mode):
        return "is not a directory"
    if st.st_uid != os.geteuid():
        return f"is owned by uid {st.st_uid}, not the runtime user (uid {os.geteuid()})"
    return ""


def provision(
    root: Path,
    slug: str,
    declaration: Any,
    plugin_version: str,
    *,
    ephemeral: bool,
) -> Path:
    """Create or confirm ``<root>/<slug>`` for one declaring plugin and return its path.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-provision@1e659b121f6b/2bbdd17d2844 (derivation) — the one
        place a plugin data directory is created and its core-owned files are written.

    The caller has already passed the mount gate for *root* and holds the plugin's shared lock.
    The ephemeral root itself is created here when first needed; the volume root never is
    (req-tap-plugin-datadir-root-4).
    """
    check_slug(slug)
    if ephemeral:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / slug
    try:
        os.mkdir(path, 0o700)
        # The umask applied to creation; set the mode explicitly. 0700 is owner-only, the spec's
        # mode for a plugin directory (req-tap-plugin-datadir-provision-1).
        os.chmod(path, stat.S_IRWXU)
    except FileExistsError:
        problem = describe(path)
        if problem:
            raise PluginDataDirectoryError(f"cannot provision plugin data directory {path}: it {problem}") from None
        # An existing directory is left as it is, except that a loose mode is reset (ruled
        # 2026-11-17): a 0777 directory would hand the plugin's state to anyone who can reach
        # the root, and refusing boot over it would stop the instance for a chmod.
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        if mode != 0o700:
            os.chmod(path, stat.S_IRWXU)
            logger.warning("[e070] plugin data: reset %s from mode %04o to 0700", path, mode)
    _write_description(path, slug, declaration, plugin_version, ephemeral=ephemeral)
    _apply_cache_tag(path, declaration.durability)
    return path


def description_for(slug: str, declaration: Any, plugin_version: str, *, ephemeral: bool) -> dict[str, Any]:
    return {
        "format_version": DESCRIPTION_FORMAT_VERSION,
        "slug": slug,
        "durability": declaration.durability,
        "purpose": declaration.purpose,
        "max_bytes": declaration.max_bytes,
        "executes": declaration.executes,
        "location": "ephemeral" if ephemeral else "volume",
        "created_by_plugin_version": plugin_version,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


#: The fields that make up the declaration; the creation fields are kept from the first write.
_DECLARED_FIELDS = ("slug", "durability", "purpose", "max_bytes", "executes", "location")


def read_description(path: Path) -> dict[str, Any] | None:
    """The directory's description file, validated against its schema; ``None`` when absent or invalid."""
    target = path / DESCRIPTION_FILENAME
    if not target.is_file() or target.is_symlink():
        return None
    try:
        data = load_json_file(target, schema=DESCRIPTION_SCHEMA)
    except JsonFileError:
        return None
    return data if isinstance(data, dict) else None


def _write_description(path: Path, slug: str, declaration: Any, plugin_version: str, *, ephemeral: bool) -> None:
    wanted = description_for(slug, declaration, plugin_version, ephemeral=ephemeral)
    existing = read_description(path)
    if existing is not None:
        if all(existing.get(field) == wanted[field] for field in _DECLARED_FIELDS):
            return
        wanted["created_by_plugin_version"] = existing["created_by_plugin_version"]
        wanted["created_at"] = existing["created_at"]
    _atomic_write(path / DESCRIPTION_FILENAME, (json.dumps(wanted, indent=2, sort_keys=True) + "\n").encode())


def _apply_cache_tag(path: Path, durability: str) -> None:
    tag = path / CACHE_TAG_FILENAME
    if durability == "cache":
        try:
            if not tag.is_symlink() and tag.read_bytes().startswith(CACHE_TAG_SIGNATURE):
                return
        except OSError:
            pass
        _atomic_write(tag, CACHE_TAG_CONTENT)
    elif tag.exists() or tag.is_symlink():
        # A directory that changed from cache to state must not be silently skipped by backup tools.
        tag.unlink()


def _atomic_write(target: Path, content: bytes) -> None:
    staging = target.with_name(f"{RESERVED_PREFIX}staging-{secrets.token_hex(6)}")
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, content)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(staging, target)


def prove_execution(path: Path) -> str:
    """Write, mark executable, run and remove a probe script in *path*; return the failure, or ``""``.

    For a plugin that declares ``executes = true``: a volume mounted so nothing on it can run fails
    here, at boot, in place of the plugin failing in the middle of its work.
    """
    probe = path / f"{EXEC_PROBE_PREFIX}{secrets.token_hex(6)}"
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
        try:
            os.write(fd, b"#!/bin/sh\nexit 0\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        # Owner read and execute only: the probe must run, and nothing else needs it.
        os.chmod(probe, 0o500)
        result = subprocess.run(  # nosec B603  # nosemgrep  # noqa: S603
            [str(probe)], capture_output=True, timeout=_EXEC_PROBE_TIMEOUT_S, check=False
        )
        if result.returncode != 0:
            return f"the probe script exited {result.returncode}"
        return ""
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{type(exc).__name__}: {exc}"
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "CACHE_TAG_FILENAME",
    "CACHE_TAG_SIGNATURE",
    "DESCRIPTION_FILENAME",
    "DESCRIPTION_SCHEMA",
    "check_slug",
    "describe",
    "description_for",
    "prove_execution",
    "provision",
    "read_description",
]
