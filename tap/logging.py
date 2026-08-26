"""TAP-wide logging configuration and call-site scanner.

Implements `specs/spec-tap-logging.md`. Two halves share this module:

* **Builder half** — `build_logging_config()` and helpers assemble the
  `dictConfig`-shaped dict assigned to `settings.LOGGING`.
* **Scanner half** — `scan_log_sites()` walks the given roots, parses each
  `.py` file via `ast`, and classifies every `logger.<level>(...)` call site
  against `req-tap-logging-site-ids` / `-callsite-convention`. Option A: the
  site token is a bare 4-hex `[<hex>]` with no slug/prefix; the callsite path
  is the derived logger name, so there is no locality check.

Public API:
    build_logging_config(installed_apps, env) -> dict
    plugin_logger_config(installed_apps) -> dict
    scan_log_sites(roots) -> ScanResult
    find_within_file_duplicates(well_formed) -> dict

`CallSite` and the first-party-root discovery moved to `tap.source_scan`
(`first_party_source_roots`) — they are shared by every tree-scanner, not
logging-specific. `scan_log_sites` takes the roots as an argument; callers pass
`first_party_source_roots(project_root)`.

Builder merge order (`req-tap-logging-config-location-5`):
    1. First-party app loggers — req-tap-logging-app-loggers
    2. Foundational third-party loggers — req-tap-logging-foundational-loggers
    3. Per-app `<app>.logging.app_logger_config()` contributions — req-tap-logging-component-libs
    4. Per-plugin entries from INSTALLED_APPS — req-tap-logging-plugin-loggers
    5. Environment-variable overrides — req-tap-logging-env-overrides

Defensive printing rather than logging in the builder: this module configures
the logging system, so it cannot rely on it. Warnings about malformed env
vars or broken app helpers go to stderr directly.
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Re-export the reserved-signal helpers (req-tap-logging-reserved-signals) so
# existing `from tap.logging import abort` call sites keep working; the canonical
# home is `tap.logging_signals` (ABORT/CONCERN) alongside `tap.flaws` (FLAW).
from tap.logging_signals import ABORT_SENTINEL as ABORT_SENTINEL
from tap.logging_signals import CONCERN_SENTINEL as CONCERN_SENTINEL
from tap.logging_signals import abort as abort
from tap.logging_signals import concern as concern
from tap.source_scan import CallSite, ScopeStackVisitor, iter_parsed_sources, semantic_hash

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(pathname)s:%(lineno)d — %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


# req-tap-logging-app-loggers — first-party apps with default levels.
# tap_flip and tap_ai are reserved (no app exists yet); inert until they do.
_FIRST_PARTY_APPS: dict[str, str] = {
    "tap_grid": "INFO",
    "tap_api": "INFO",
    "tap_cares": "INFO",
    "tap_web": "INFO",
    "tap_viz": "INFO",
    "tap_plugins": "INFO",
    "tap_flip": "INFO",
    "tap_ai": "INFO",
}

# req-tap-logging-foundational-loggers — libraries used transitively by anything
# with no single owner. Component-owned libraries (steady_queue, etc.) live in
# each component's <app>.logging.app_logger_config(); they are NOT listed here.
_FOUNDATIONAL_LOGGERS: dict[str, str] = {
    "django": "INFO",
    "django.db.backends": "WARNING",
    "django.server": "WARNING",
    "urllib3": "WARNING",
}

# req-tap-logging-plugin-loggers — wildcard catches plugins not explicitly
# configured (e.g. one mid-development that hasn't been added to INSTALLED_APPS).
_PLUGIN_WILDCARD_LEVEL = "INFO"

# req-tap-logging-env-overrides-4 — valid level set for env-var validation.
_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_ENV_PER_LOGGER = "TAP_LOG_LEVELS"
_ENV_ROOT = "TAP_LOG_LEVEL"


def _logger_entry(level: str) -> dict[str, Any]:
    return {"level": level, "handlers": ["console"], "propagate": False}


def _first_party_logger_configs() -> dict[str, dict[str, Any]]:
    return {name: _logger_entry(level) for name, level in _FIRST_PARTY_APPS.items()}


def _foundational_logger_configs() -> dict[str, dict[str, Any]]:
    return {name: _logger_entry(level) for name, level in _FOUNDATIONAL_LOGGERS.items()}


def _discover_plugin_slugs(installed_apps: list[str]) -> list[str]:
    """Extract plugin slugs from INSTALLED_APPS, preserving order, de-duplicated.

    Plugin entries look like `plugins.<slug>.apps.<ConfigClass>` or `plugins.<slug>`.
    """
    slugs: list[str] = []
    seen: set[str] = set()
    for entry in installed_apps:
        parts = entry.split(".")
        if len(parts) < 2 or parts[0] != "plugins":
            continue
        slug = parts[1]
        if slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def plugin_logger_config(installed_apps: list[str]) -> dict[str, dict[str, Any]]:
    """Return logger configs for registered plugins plus the wildcard fallback."""
    config: dict[str, dict[str, Any]] = {
        "plugins": _logger_entry(_PLUGIN_WILDCARD_LEVEL),
    }
    for slug in _discover_plugin_slugs(installed_apps):
        config[f"plugins.{slug}"] = _logger_entry("INFO")
    return config


def _discover_first_party_app_modules(installed_apps: list[str]) -> list[str]:
    """Return distinct tap_* app module names from INSTALLED_APPS, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for entry in installed_apps:
        head = entry.split(".", 1)[0]
        if not head.startswith("tap_"):
            continue
        if head in seen:
            continue
        seen.add(head)
        out.append(head)
    return out


def _app_logger_configs(installed_apps: list[str]) -> dict[str, dict[str, Any]]:
    """Discover and merge `<app>.logging.app_logger_config()` contributions.

    Missing modules / missing helpers are silently skipped
    (req-tap-logging-component-libs-2). A helper that raises or returns the
    wrong shape produces a stderr warning and is skipped.
    """
    config: dict[str, dict[str, Any]] = {}
    for app in _discover_first_party_app_modules(installed_apps):
        module_name = f"{app}.logging"
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        helper = getattr(module, "app_logger_config", None)
        if helper is None:
            continue
        try:
            contribution = helper()
        except Exception as exc:  # noqa: BLE001
            print(
                f"WARNING: {module_name}.app_logger_config() raised {exc!r}; skipping.",
                file=sys.stderr,
            )
            continue
        if not isinstance(contribution, dict):
            print(
                f"WARNING: {module_name}.app_logger_config() returned "
                f"{type(contribution).__name__}, expected dict; skipping.",
                file=sys.stderr,
            )
            continue
        config.update(contribution)
    return config


def _parse_env_overrides(env: Mapping[str, str]) -> tuple[dict[str, str], str | None]:
    """Parse TAP_LOG_LEVELS and TAP_LOG_LEVEL into (per_logger, root_level).

    Per-logger map: {logger_name: LEVEL}. Root level: LEVEL or None.
    Invalid entries are skipped with a stderr warning.
    """
    per_logger: dict[str, str] = {}

    raw_pairs = env.get(_ENV_PER_LOGGER, "")
    if raw_pairs:
        for raw_pair in raw_pairs.split(","):
            pair = raw_pair.strip()
            if not pair:
                continue
            if "=" not in pair:
                print(
                    f"WARNING: {_ENV_PER_LOGGER} entry {pair!r} has no '='; skipping.",
                    file=sys.stderr,
                )
                continue
            name, _, raw_level = pair.partition("=")
            name = name.strip()
            level = raw_level.strip().upper()
            if not name:
                print(
                    f"WARNING: {_ENV_PER_LOGGER} entry {pair!r} has empty logger name; skipping.",
                    file=sys.stderr,
                )
                continue
            if level not in _VALID_LEVELS:
                print(
                    f"WARNING: {_ENV_PER_LOGGER} entry for {name!r} has invalid level "
                    f"{raw_level.strip()!r}; skipping.",
                    file=sys.stderr,
                )
                continue
            per_logger[name] = level

    root_level: str | None = None
    raw_root = env.get(_ENV_ROOT)
    if raw_root is not None:
        candidate = raw_root.strip().upper()
        if candidate in _VALID_LEVELS:
            root_level = candidate
        else:
            print(
                f"WARNING: {_ENV_ROOT}={raw_root!r} is not a valid level; ignoring.",
                file=sys.stderr,
            )

    return per_logger, root_level


def build_logging_config(
    installed_apps: list[str],
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the `dictConfig`-shaped dict for `settings.LOGGING`.

    TAP-IMPLEMENTS: req-tap-logging-config-location@2eec970aa550/51ee0f46ed71 (derivation) — the one
        assembly of the logging config; ``settings.LOGGING`` is this function's return
        value and nothing else composes the dict.

    Merge order is documented at the module docstring and in
    `req-tap-logging-config-location-5`.
    """
    if env is None:
        env = os.environ

    loggers: dict[str, dict[str, Any]] = {}
    loggers.update(_first_party_logger_configs())
    loggers.update(_foundational_logger_configs())
    loggers.update(_app_logger_configs(installed_apps))
    loggers.update(plugin_logger_config(installed_apps))

    per_logger_overrides, root_override = _parse_env_overrides(env)
    for name, level in per_logger_overrides.items():
        if name in loggers:
            loggers[name] = {**loggers[name], "level": level}
        else:
            # Override mentions a logger we don't have a default for — create
            # an entry so the override takes effect. Inherits the standard
            # handler + no-propagate shape.
            loggers[name] = _logger_entry(level)

    root_entry: dict[str, Any] = {
        "level": root_override or "WARNING",
        "handlers": ["console"],
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "tap": {"format": _FORMAT, "datefmt": _DATEFMT},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "tap",
            },
        },
        "loggers": loggers,
        "root": root_entry,
    }


# =============================================================================
# Call-site scanner — req-tap-logging-site-id-scanner (Option A)
# =============================================================================
# AST-based scanner that walks the given roots, classifies every
# `logger.<level>(...)` call as well-formed / missing / malformed / noqa, and
# also detects two convention violations from `req-tap-logging-callsite-convention`:
# `getLogger(...)` calls whose argument is not `__name__`, and `logger.<level>`
# calls whose first argument is an f-string.
#
# Option A site model (`req-tap-logging-site-ids`): the token is a bare 4-hex
# `[<hex>]` with no slug or prefix. The structurally-unique callsite path is
# the derived logger name (`__name__`), which a developer never authors — so
# there is no locality check and no prefix derivation. The hex only has to be
# unique *within its file*; the module path namespaces it.
#
# The scanner is intentionally permissive about *what* it reads (best-effort
# AST parse; skip files that fail to parse) and strict about *what counts as
# a site token* (regex below). Multi-line log calls are handled because `ast`
# resolves to the call's starting line for the noqa check.

# req-tap-logging-site-ids-1 / scanner-3: bare 4-hex token, no slug/prefix.
_SITE_ID_PATTERN = re.compile(r"^\[([0-9a-f]{4})\] ")
# A bracketed prefix that *isn't* a well-formed 4-hex token — flags malformed
# attempts (uppercase, wrong length, leftover `[slug-hex]` form, etc.).
_BRACKETED_PREFIX_PATTERN = re.compile(r"^\[[^\]]+\] ")

# req-tap-logging-site-ids-2: every committed level, DEBUG included. No exemption.
_LOGGER_LEVELS = frozenset({"debug", "info", "warning", "error", "critical", "exception"})

# req-tap-logging-site-ids-5 / scanner-6: noqa escape hatch.
_NOQA_TOKEN = "noqa: TAP-LOG-ID"


@dataclass(frozen=True)
class WellFormedSite:
    """A log call site whose message starts with a well-formed `[<hex>]` token.

    The convention's anchor exemplar (`spec-tap-callsite-identity`): the token is
    unique within its file by construction, and `path::[<hex>]` namespaces it into a
    globally-unique anchor. Carries no qualname because uniqueness is enforced on the
    token, not discriminated after the fact.
    """

    path: Path
    lineno: int
    hex_token: str


@dataclass(frozen=True)
class LogViolationSite:
    """A log-site *violation* (missing token, f-string message, or bad getLogger arg).

    A violation has no `[<hex>]` yet — that is the violation — so it cannot use the
    well-formed `path::[<hex>]` anchor. It is remediated **per-call** (mint a token /
    fix the call), so it takes an occurrence key
    `path::qualname::<construct>::<kind>#<disc>` until a token is minted, then
    graduates to the well-formed anchor (`spec-tap-callsite-identity`,
    `req-tap-callsite-identity-conformance`). `construct` is `logger.<level>` (or
    `getLogger`); `kind` is the violation class; `node_dump` is the discriminator
    material.
    """

    path: Path
    lineno: int
    qualname: str
    construct: str
    kind: str
    node_dump: str

    def anchor(self, repo_root: Path) -> str:
        return f"{self.path.relative_to(repo_root).as_posix()}::{self.qualname}::{self.construct}::{self.kind}"

    def discriminator(self, repo_root: Path) -> str:
        return semantic_hash(
            self.path.relative_to(repo_root).as_posix(),
            self.qualname,
            self.construct,
            self.kind,
            self.node_dump,
        )


@dataclass
class ScanResult:
    """Categorized findings from `scan_log_sites()`."""

    well_formed: list[WellFormedSite] = field(default_factory=list)
    # Violation buckets carry qualname + kind (callsite-identity occurrence keys).
    missing_ids: list[LogViolationSite] = field(default_factory=list)
    malformed_ids: list[CallSite] = field(default_factory=list)
    noqa_skipped: list[CallSite] = field(default_factory=list)
    # getLogger-not-__name__ and f-string messages; kind carries which.
    convention_violations: list[LogViolationSite] = field(default_factory=list)


def _is_getlogger_call(call: ast.Call) -> bool:
    """True if a `Call` node targets `logging.getLogger` or bare `getLogger`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr == "getLogger":
        return True
    if isinstance(func, ast.Name) and func.id == "getLogger":
        return True
    return False


def _is_logger_level_call(call: ast.Call) -> tuple[bool, str | None]:
    """Detect `logger.<level>(...)` patterns. Returns (matched, level_name)."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False, None
    if func.attr not in _LOGGER_LEVELS:
        return False, None
    if not isinstance(func.value, ast.Name) or func.value.id != "logger":
        return False, None
    return True, func.attr


class _LogSiteVisitor(ScopeStackVisitor):
    """Classify `logger.<level>(...)` and `getLogger(...)` calls, tracking enclosing
    scope so a violation carries a drift-proof qualname (`spec-tap-callsite-identity`).

    The enclosing-scope walk is inherited from `ScopeStackVisitor`; only `visit_Call`
    is overridden. Detection is unchanged from the previous flat `ast.walk`, so
    well-formed/malformed/noqa/missing classification is identical.
    """

    def __init__(self, path: Path, source_lines: list[str], result: ScanResult) -> None:
        super().__init__()
        self.path = path
        self.source_lines = source_lines
        self.result = result

    def _qualname(self) -> str:
        return self.current_qualname()

    def visit_Call(self, node: ast.Call) -> None:
        self._classify(node)
        self.generic_visit(node)

    def _classify(self, node: ast.Call) -> None:
        path, result = self.path, self.result

        if _is_getlogger_call(node):
            ok = len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == "__name__"
            if not ok:
                result.convention_violations.append(
                    LogViolationSite(path, node.lineno, self._qualname(), "getLogger", "getlogger-arg", _dump(node))
                )
            return

        matched, level = _is_logger_level_call(node)
        if not matched:
            return
        assert level is not None
        # req-tap-logging-site-ids-2: no DEBUG exemption — every level checked.
        construct = f"logger.{level}"

        lineno = node.lineno
        line = self.source_lines[lineno - 1] if 0 < lineno <= len(self.source_lines) else ""
        if _NOQA_TOKEN in line:
            result.noqa_skipped.append(CallSite(path, lineno))
            return

        if not node.args:
            result.missing_ids.append(
                LogViolationSite(path, lineno, self._qualname(), construct, "missing", _dump(node))
            )
            return

        first = node.args[0]
        if isinstance(first, ast.JoinedStr):
            result.convention_violations.append(
                LogViolationSite(path, lineno, self._qualname(), construct, "fstring", _dump(node))
            )
            return
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            msg = first.value
            m = _SITE_ID_PATTERN.match(msg)
            if m:
                result.well_formed.append(WellFormedSite(path, lineno, m.group(1)))
            elif _BRACKETED_PREFIX_PATTERN.match(msg):
                result.malformed_ids.append(CallSite(path, lineno))
            else:
                result.missing_ids.append(
                    LogViolationSite(path, lineno, self._qualname(), construct, "missing", _dump(node))
                )
            return
        # Non-literal first argument (variable, BinOp concat, function call).
        # Treat as missing — we can't statically verify a site ID is present.
        result.missing_ids.append(LogViolationSite(path, lineno, self._qualname(), construct, "missing", _dump(node)))


def _dump(node: ast.AST) -> str:
    """Positions-stripped structural dump — drift-proof discriminator material."""
    return ast.dump(node, include_attributes=False)


def scan_log_sites(roots: list[Path]) -> ScanResult:
    """Walk each root and classify `logger.<level>(...)` call sites (Option A).

    Files that fail to parse are silently skipped (pytest's own collection will
    catch real syntax errors elsewhere). Use `tap.source_scan.first_party_source_roots()`
    to derive the first-party-app + plugin roots from the project root.
    """
    result = ScanResult()
    for parsed in iter_parsed_sources(roots):
        _LogSiteVisitor(parsed.path, parsed.lines, result).visit(parsed.tree)
    return result


def find_within_file_duplicates(
    well_formed: list[WellFormedSite],
) -> dict[tuple[Path, str], list[WellFormedSite]]:
    """Group well-formed tokens by (file, hex); return groups of >1.

    Cross-file reuse is *not* a violation — the logger name (module path)
    namespaces the hex (`req-tap-logging-site-id-scanner-4`), so the same hex
    in two different modules is two distinct call sites.
    """
    by_id: dict[tuple[Path, str], list[WellFormedSite]] = {}
    for site in well_formed:
        by_id.setdefault((site.path, site.hex_token), []).append(site)
    return {k: v for k, v in by_id.items() if len(v) > 1}
