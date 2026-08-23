"""Shared JSON file load + schema-validate helper (spec-tap-json-files.md).

TAP-IMPLEMENTS: req-tap-json-loader@f0365e36869f/8324d5036fed (derivation) — the one home of the
read → parse → validate → JSON-pointer-location mechanics; loaders re-wrap
`JsonFileError`, they never re-derive the mechanics.

One load path for every TAP-owned config/data JSON file: read → parse →
optional schema-validate → uniform error. Loaders catch `JsonFileError` and
re-raise their own domain exception (`req-tap-json-adoption`), so the read +
parse + JSON-pointer-location mechanics live here exactly once instead of being
copy-pasted across a dozen loaders.

This module also hosts the filename-convention scanner (`scan_json_files`,
`req-tap-json-scanner`), mirroring the way `tap/logging.py` hosts both the
logging config builder and its site-id scanner.

Spec: specs/spec-tap-json-files.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema

# tap/jsonfiles.py → repo root. Used to render scanner paths relative to the
# repo so the baseline file is location-independent.
REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# load + validate (req-tap-json-loader)
# --------------------------------------------------------------------------- #


class JsonFileError(Exception):
    """The one failure type for the shared JSON load path.

    Carries structured attributes so a caller can re-wrap with a domain-shaped
    message by reading fields rather than re-parsing the rendered string
    (`req-tap-json-loader-4`):

    - ``path``: the file involved.
    - ``reason``: the underlying cause (OS error, JSON parse detail, or schema
      validator message).
    - ``location``: JSON-pointer-ish path to the offending node for schema
      failures (e.g. ``population/steps/0``), or ``None`` for read/parse errors.
    """

    def __init__(self, path: Path | str, reason: str, *, location: str | None = None) -> None:
        self.path = Path(path)
        self.reason = reason
        self.location = location
        super().__init__(self._render())

    def _render(self) -> str:
        if self.location is not None:
            return f"{self.path}: schema validation failed at {self.location}: {self.reason}"
        return f"{self.path}: {self.reason}"


@cache
def _read_schema_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JsonFileError(path, f"could not read schema: {exc}") from exc
    try:
        schema: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonFileError(path, f"invalid JSON schema: line {exc.lineno} column {exc.colno} ({exc.msg})") from exc
    return schema


def load_schema(path: Path | str) -> dict[str, Any]:
    """Read a ``*.schema.json`` file once and cache it (`req-tap-json-loader-5`).

    Replaces the hand-rolled, per-module ``@lru_cache`` ``_schema()`` readers.
    The returned dict is shared across callers; treat it as read-only.
    """
    return _read_schema_cached(str(Path(path)))


def load_json_file(path: Path | str, *, schema: dict[str, Any] | Path | str | None = None) -> Any:
    """Read, parse, and optionally schema-validate a JSON file.

    Args:
        path: File to load.
        schema: A loaded JSON Schema dict, or a path to a ``*.schema.json``
            file. When given, the parsed document is validated and a failure
            raises `JsonFileError` with the offending ``location`` populated.

    Returns:
        The parsed JSON value on success.

    Raises:
        JsonFileError: on an unreadable file, malformed JSON, or schema
            violation. This is the **only** exception the helper raises — never
            a raw ``json``/``jsonschema`` error (`req-tap-json-loader-2`).
    """
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise JsonFileError(path, f"could not read file: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JsonFileError(path, f"invalid JSON: line {exc.lineno} column {exc.colno} ({exc.msg})") from exc

    if schema is not None:
        validate_json(data, schema, source=path)

    return data


def validate_json(
    instance: Any,
    schema: dict[str, Any] | Path | str,
    *,
    source: Path | str | None = None,
) -> None:
    """Validate an already-in-memory value against a JSON Schema.

    The companion to `load_json_file` for the cases where the value is not read
    from a file in the same breath — an extracted sub-section, a constructed
    payload, a per-entry check. Keeps the JSON-pointer location formatter in one
    place (`req-tap-json-loader-3`); a failure raises `JsonFileError` with
    ``location`` set and ``path`` taken from ``source`` (or ``<in-memory>``).
    """
    schema_obj = load_schema(schema) if isinstance(schema, (str, Path)) else schema
    try:
        jsonschema.validate(instance=instance, schema=schema_obj)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise JsonFileError(source if source is not None else "<in-memory>", exc.message, location=location) from exc


# --------------------------------------------------------------------------- #
# discovery (req-tap-json-discovery)
# --------------------------------------------------------------------------- #


def discover_json_files(directory: Path | str, *, role: str, recursive: bool = False) -> list[Path]:
    """Discover ``*.<role>.json`` files under ``directory``, sorted.

    TAP-IMPLEMENTS: req-tap-json-discovery@7552e55f7399/b9282ff8c063 (derivation) — the one role-keyed
        discovery scan; a bare ``*.json`` glob anywhere else is the bug class this exists
        to end.

    Keys discovery on an explicit ``role`` (the file-suffix vocabulary of
    `req-tap-json-naming`) instead of a bare ``*.json`` glob, so a stray JSON
    dropped in the directory is never mis-discovered. Dotfiles and non-files are
    skipped; a missing/non-directory path returns ``[]`` (a missing optional
    source is normal, `req-tap-json-discovery-4`).
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    pattern = f"*.{role}.json"
    matches = directory.rglob(pattern) if recursive else directory.glob(pattern)
    return sorted(p for p in matches if p.is_file() and not p.name.startswith("."))


def instance_id(path: Path | str, *, role: str) -> str:
    """Return the instance id of a ``<id>.<role>.json`` file (the suffix stripped).

    Use this, not ``Path.stem`` — ``Path("base.boot.json").stem`` is
    ``"base.boot"``, not ``"base"`` (`req-tap-json-discovery` Development).
    """
    name = Path(path).name
    suffix = f".{role}.json"
    if not name.endswith(suffix):
        raise JsonFileError(path, f"name does not end with {suffix!r}")
    return name[: -len(suffix)]


# --------------------------------------------------------------------------- #
# filename scanner (req-tap-json-scanner)
# --------------------------------------------------------------------------- #

# Known discovered-family roles whose `*.<role>.json` suffix is a conforming name.
KNOWN_ROLES: tuple[str, ...] = ("boot", "secret", "grift", "edge", "gridkin")

# First-party app labels accepted as the `<app>.` prefix of a singleton config
# file (`req-tap-json-naming` pattern 2). Stable set; deriving from Django would
# pull settings into a lexical filename scanner that deliberately imports nothing.
FIRST_PARTY_APPS: tuple[str, ...] = (
    "tap_grid",
    "tap_plugins",
    "tap_api",
    "tap_web",
    "tap_viz",
    "tap_ai",
    "tap_cares",
    "tap_auth",
    "tap_boot",
)

# Directories never walked. `vendor` holds third-party files (e.g. the NIST
# OSCAL schemas under plugins/roscale/vendor/) that are not TAP-owned and so not
# subject to this convention.
_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {".venv", "node_modules", "__pycache__", ".git", ".claude", ".mypy_cache", ".pytest_cache", "vendor"}
)

# Standard tooling JSON that is not TAP-owned config/data.
_TOOLING_NAMES: frozenset[str] = frozenset({"package.json", "package-lock.json", "tsconfig.json"})

# Path segments that mark test scaffolding, exempt from the convention.
_TEST_SEGMENTS: frozenset[str] = frozenset({"tests", "fixtures", "expected", "snapshots"})

DEFAULT_BASELINE = Path(__file__).resolve().parent / "tests" / "_json_file_baseline.txt"


@dataclass(frozen=True)
class ScanResult:
    """Outcome of a filename-convention scan."""

    conforming: tuple[Path, ...]
    baselined: tuple[Path, ...]
    new_violations: tuple[Path, ...]
    stale_baseline: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.new_violations


def _is_excluded(path: Path) -> bool:
    return any(part in _EXCLUDE_DIRS for part in path.parts)


def filename_conforms(rel_path: Path) -> bool:
    """True if ``rel_path`` (relative to the repo root) satisfies the convention."""
    name = rel_path.name
    parts = set(rel_path.parts)

    # Test scaffolding and tooling are exempt.
    if parts & _TEST_SEGMENTS:
        return True
    if name in _TOOLING_NAMES or name.endswith(".lock"):
        return True
    if name.endswith(".expected.json"):
        return True

    # Schemas: `<type>.schema.json`.
    if name.endswith(".schema.json"):
        return True

    # Discovered families: `<name>.<role>.json`.
    for role in KNOWN_ROLES:
        if name.endswith(f".{role}.json"):
            return True

    # Singleton app config: `<app>.<name>.json`.
    for app in FIRST_PARTY_APPS:
        if name.startswith(f"{app}."):
            return True

    # Plugin-owned singleton: `<plugin>.<name>.json` living under `plugins/<plugin>/`.
    # A one-of-a-kind, non-globbed data file owned by a plugin (e.g. a coverage
    # ledger) takes the same owner-prefix form as a first-party singleton, but its
    # owner is the enclosing plugin package rather than a tap_* app. Deriving the
    # prefix from the path keeps this general — no per-plugin allowlist to maintain.
    parts = rel_path.parts
    if len(parts) >= 2 and parts[0] == "plugins" and name.startswith(f"{parts[1]}."):
        return True

    return False


def _read_baseline(baseline_path: Path) -> set[str]:
    if not baseline_path.is_file():
        return set()
    lines = baseline_path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def scan_json_files(roots: list[Path], *, baseline_path: Path | None = None) -> ScanResult:
    """Scan ``roots`` for `.json` files and classify each against the convention.

    TAP-IMPLEMENTS: req-tap-json-scanner@d4463a9f94cb/71b595088c92 (enforcement) — the convention's one
        scanner; the baseline ratchet in the test lane consumes exactly this result.

    A non-conforming file is a **new violation** unless it appears in the
    baseline (`req-tap-json-scanner-4`). Baseline entries that no longer exist on
    disk are reported as ``stale_baseline`` so they can be removed as the debt is
    paid down. The scan is purely lexical over filenames — it never opens a file.
    """
    baseline = _read_baseline(baseline_path or DEFAULT_BASELINE)

    conforming: list[Path] = []
    baselined: list[Path] = []
    new_violations: list[Path] = []
    seen_rel: set[str] = set()

    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            if _is_excluded(path) or not path.is_file():
                continue
            try:
                rel = path.resolve().relative_to(REPO_ROOT)
            except ValueError:
                rel = path
            rel_str = str(rel)
            seen_rel.add(rel_str)
            if filename_conforms(rel):
                conforming.append(rel)
            elif rel_str in baseline:
                baselined.append(rel)
            else:
                new_violations.append(rel)

    stale = tuple(sorted(entry for entry in baseline if entry not in seen_rel))
    return ScanResult(
        conforming=tuple(conforming),
        baselined=tuple(baselined),
        new_violations=tuple(new_violations),
        stale_baseline=stale,
    )


__all__ = [
    "JsonFileError",
    "load_json_file",
    "validate_json",
    "load_schema",
    "discover_json_files",
    "instance_id",
    "scan_json_files",
    "filename_conforms",
    "ScanResult",
    "KNOWN_ROLES",
    "FIRST_PARTY_APPS",
    "DEFAULT_BASELINE",
]
