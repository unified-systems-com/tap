"""Plugin validation service.

Implements req-tap-plugin-validate-* from spec-tap-plugin-validation.md.

The service validates one plugin root at a time using TAP's real manifest
parsing and validation codepaths.  Three cumulative levels:

- ``structure``: manifest parsing, path checks, edge files. No Django required.
- ``loads``: structure + class-path validation via Django imports. Requires Django.
- ``runs``: loads + service-layer smoke tests. Requires Django + database.
  Runs inside a rollback transaction so no data is persisted.

Public API:
    validate_plugin(plugin_root, *, level, strict) -> ValidationResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tap.jsonfiles import validate_json

logger = logging.getLogger(__name__)

SUPPORTED_LEVELS = {"structure", "loads", "runs"}
DJANGO_REQUIRED_LEVELS = {"loads", "runs"}
KNOWN_LEVELS = {"structure", "loads", "runs"}

_SCHEMA_PATH = Path(__file__).parent / "plugin-validation-result.schema.json"


@dataclass
class Message:
    severity: str  # "info", "warning", "error"
    text: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"severity": self.severity, "text": self.text}
        if self.path is not None:
            d["path"] = self.path
        return d


@dataclass
class CheckResult:
    id: str
    name: str
    status: str = "pass"  # "pass", "warn", "fail"
    messages: list[Message] = field(default_factory=list)
    details: dict[str, Any] | None = None

    def fail(self, text: str, *, path: str | None = None) -> None:
        self.status = "fail"
        self.messages.append(Message(severity="error", text=text, path=path))

    def warn(self, text: str, *, path: str | None = None) -> None:
        if self.status != "fail":
            self.status = "warn"
        self.messages.append(Message(severity="warning", text=text, path=path))

    def info(self, text: str, *, path: str | None = None) -> None:
        self.messages.append(Message(severity="info", text=text, path=path))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.details is not None:
            d["details"] = self.details
        return d


@dataclass
class ValidationResult:
    ok: bool
    level: str
    plugin_path: str
    strict: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        passed = sum(1 for c in self.checks if c.status == "pass")
        warned = sum(1 for c in self.checks if c.status == "warn")
        failed = sum(1 for c in self.checks if c.status == "fail")
        warnings_total = sum(1 for c in self.checks for m in c.messages if m.severity == "warning")
        errors_total = sum(1 for c in self.checks for m in c.messages if m.severity == "error")
        return {
            "checks_total": len(self.checks),
            "checks_passed": passed,
            "checks_warned": warned,
            "checks_failed": failed,
            "warnings_total": warnings_total,
            "errors_total": errors_total,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "level": self.level,
            "plugin_path": self.plugin_path,
            "strict": self.strict,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
        }

    def to_json(self) -> str:
        doc = self.to_dict()
        validate_json(doc, _SCHEMA_PATH, source="plugin-validation-result")
        return json.dumps(doc, indent=2)

    def to_human(self) -> str:
        lines: list[str] = []
        status_icon = "PASS" if self.ok else "FAIL"
        lines.append(f"Plugin validation: {status_icon}")
        lines.append(f"  Path:   {self.plugin_path}")
        lines.append(f"  Level:  {self.level}")
        lines.append(f"  Strict: {self.strict}")
        lines.append("")

        s = self.summary
        lines.append(
            f"  Checks: {s['checks_total']} total, "
            f"{s['checks_passed']} passed, "
            f"{s['checks_warned']} warned, "
            f"{s['checks_failed']} failed"
        )
        lines.append("")

        for check in self.checks:
            icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}[check.status]
            lines.append(f"  [{icon}] {check.name}")
            for msg in check.messages:
                prefix = {"info": "     ", "warning": "     WARN:", "error": "     ERR:"}[msg.severity]
                path_suffix = f" ({msg.path})" if msg.path else ""
                lines.append(f"{prefix} {msg.text}{path_suffix}")

        lines.append("")
        return "\n".join(lines)


class UnsupportedLevelError(Exception):
    """Raised when a validation level is not yet implemented."""


def validate_plugin(
    plugin_root: Path,
    *,
    level: str = "structure",
    strict: bool = False,
) -> ValidationResult:
    """Validate a single plugin root directory.

    Args:
        plugin_root: Absolute path to the plugin root.
        level: Validation level — ``"structure"``, ``"loads"``, or ``"runs"``.
        strict: If True, warnings are promoted to failures.

    Returns:
        A ValidationResult with per-check detail.

    Raises:
        UnsupportedLevelError: If *level* is a known but unimplemented level.
        ValueError: If *level* is not a recognized level name.
    """
    if level not in KNOWN_LEVELS:
        raise ValueError(f"Unknown validation level: {level!r}")
    if level not in SUPPORTED_LEVELS:
        raise UnsupportedLevelError(f"Validation level {level!r} is not yet implemented")

    result = ValidationResult(
        ok=True,
        level=level,
        plugin_path=str(plugin_root),
        strict=strict,
    )

    # Structure checks (always run)
    manifest = _run_structure_checks(plugin_root, result)

    # Loads checks (cumulative — requires Django)
    if level in ("loads", "runs") and manifest is not None:
        _run_loads_checks(manifest, result)

    # Runs checks (cumulative — requires Django + database)
    if level == "runs" and manifest is not None:
        # Only run if all prior checks passed — no point smoke-testing
        # a plugin whose classes don't even import.
        if all(c.status != "fail" for c in result.checks):
            _run_runs_checks(manifest, result)

    if strict:
        for check in result.checks:
            if check.status == "warn":
                check.status = "fail"
                for msg in check.messages:
                    if msg.severity == "warning":
                        msg.severity = "error"

    result.ok = all(c.status != "fail" for c in result.checks)
    return result


# ---------------------------------------------------------------------------
# Structure-level checks
# ---------------------------------------------------------------------------


def _resolve_package_root(plugin_root: Path) -> Path:
    """Return the directory that holds ``tap-plugin.toml`` (+ ``apps.py``/``__init__.py``).

    Handles both plugin layouts during the package-mode transition:

    - **Legacy (build-baked):** manifest + code live at ``plugin_root`` itself.
    - **Package-mode (namespaced):** manifest + code live at
      ``plugin_root/tap_plugin/<slug>/`` (PEP 420 namespace); ``tests/`` stays at
      ``plugin_root``. See req-tap-plugin-arch-identity-3.

    Falls back to ``plugin_root`` when no manifest is found so the core-files /
    manifest-parse checks report the missing manifest rather than raising here.
    """
    if (plugin_root / "tap-plugin.toml").is_file():
        return plugin_root
    namespace_dir = plugin_root / "tap_plugin"
    if namespace_dir.is_dir():
        candidates = sorted(p.parent for p in namespace_dir.glob("*/tap-plugin.toml"))
        if candidates:
            return candidates[0]
    return plugin_root


def _run_structure_checks(plugin_root: Path, result: ValidationResult) -> Any:
    """Run all structure-level validation checks. Returns manifest or None."""
    # In package-mode the manifest + code sit inside tap_plugin/<slug>/, while tests/
    # stays at the plugin root. Resolve the package dir for the manifest-anchored
    # checks; keep the tests check anchored at the (top) plugin root.
    package_root = _resolve_package_root(plugin_root)
    _check_plugin_root(plugin_root, result)
    _check_core_files(package_root, result)
    manifest = _check_manifest_parse(package_root, result)
    if manifest is not None:
        _check_convention_dirs(manifest, result)
        _check_edge_files(manifest, result)
        _check_grift_paths(manifest, result)
        _check_undeclared_files(manifest, result)
        _check_tests_dir(package_root, result)
        _check_identity_coherence(plugin_root, package_root, manifest, result)
        _check_declared_dependencies(package_root, manifest, result)
        _check_requires_tap(manifest, result)
        _check_crypto_providers(plugin_root, manifest, result)
    return manifest


def _declared_dependency_names(plugin_root: Path) -> list[str]:
    """Best-effort read of the plugin's declared third-party distributions from its pyproject.toml
    `[project].dependencies` — the crypto-risk surface (a plugin is usually pure Python; its RISK is
    what it pulls in). Version specifiers are stripped to the bare distribution name."""
    import re
    import tomllib

    pyproject = plugin_root / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError, tomllib.TOMLDecodeError:
        return []
    deps = data.get("project", {}).get("dependencies", []) or []
    names: list[str] = []
    for spec in deps:
        if isinstance(spec, str):
            name = re.split(r"[<>=!~ \[;]", spec.strip(), maxsplit=1)[0]
            if name:
                names.append(name)
    return names


def _check_crypto_providers(plugin_root: Path, manifest: Any, result: ValidationResult) -> None:
    """Per-plugin crypto Bill-of-Materials + declaration check (req-fips-crypto-bom): does this plugin
    ship or pull a NON-FIPS-validated crypto provider, and does its declared `[fips]` posture match?

    A plugin runs in the same image/process as core, so a plugin leaking non-validated crypto defeats
    a FIPS-capable core. This is the "declare" half of declare-vs-decide: the author DECLARES posture
    in `[fips]`, and this VERIFIES it against the scan (the author cannot excuse the plugin — only the
    operator waives, via the boot profile's `fips_waivers`, enforced by the boot-time system gate):

    - declared `compatible` but the scan finds non-validated crypto → FAIL (the declaration is false);
    - declared `uses-nonvalidated` (+ a reason) → PASS (honest); a FIPS deployment still needs a waiver;
    - UNDECLARED but the scan finds non-validated crypto → WARN (declare it); `--strict` → fail.
    """
    from tap import crypto_bom

    check = CheckResult(id="crypto-providers", name="Crypto providers are FIPS-validated")
    report = crypto_bom.scan_plugin(plugin_root, dist_names=_declared_dependency_names(plugin_root))
    declaration = getattr(manifest, "fips", None)
    status = declaration.status if declaration is not None else None
    declared_reason = declaration.reason if declaration is not None else None
    nonvalidated = [f for f in report.findings if f.is_failure]

    # Informational: every non-failing finding (validated / out-of-boundary / unreached).
    for finding in report.findings:
        if not finding.is_failure:
            label = finding.boundary.value if finding.boundary else "noted"
            check.info(f"{label}: {finding.provider} ({finding.artifact})")

    if nonvalidated:
        providers = sorted({f.provider for f in nonvalidated})
        if status == "compatible":
            check.fail(
                f"[fips] status='compatible' is FALSE — this plugin ships/pulls non-validated crypto provider(s) "
                f"{providers}. Build them against the system OpenSSL / swap to an ecosystem-validated module, or "
                f"change the declaration to status='uses-nonvalidated' with a reason."
            )
        elif status == "uses-nonvalidated":
            check.info(
                f"[fips] status='uses-nonvalidated' (reason: {declared_reason}) — acknowledged non-validated "
                f"provider(s) {providers}. Honest; a FIPS-mode deployment still needs a justified 'fips_waivers' entry."
            )
        else:
            for finding in nonvalidated:
                check.warn(
                    f"undeclared non-validated crypto provider '{finding.provider}' ({finding.artifact}): "
                    f"{finding.detail}. Declare it in a [fips] table (status='uses-nonvalidated' + reason) or make "
                    f"it FIPS-validated; a FIPS-mode deployment refuses it without an operator waiver.",
                    path=finding.artifact,
                )
    elif status == "compatible":
        check.info("[fips] status='compatible' — verified: no non-validated crypto provider detected.")
    elif status == "uses-nonvalidated":
        check.info("[fips] status='uses-nonvalidated' declared, but no non-validated provider detected (conservative).")
    elif not report.findings:
        check.info("No crypto providers detected (pure-Python; no bundled native crypto or crypto-bearing deps).")

    result.checks.append(check)


def _check_plugin_root(plugin_root: Path, result: ValidationResult) -> None:
    check = CheckResult(id="plugin-root", name="Plugin root directory exists")
    if not plugin_root.is_dir():
        check.fail(f"Plugin root is not a directory: {plugin_root}")
    else:
        check.info(f"Plugin root: {plugin_root}")
    result.checks.append(check)


def _check_core_files(plugin_root: Path, result: ValidationResult) -> None:
    check = CheckResult(id="core-files", name="Core required files exist")

    for filename in ("__init__.py", "apps.py", "tap-plugin.toml"):
        path = plugin_root / filename
        if path.exists():
            check.info(f"Found {filename}")
        else:
            check.fail(f"Missing required file: {filename}", path=filename)

    result.checks.append(check)


def _check_manifest_parse(plugin_root: Path, result: ValidationResult) -> Any:
    """Parse and structurally validate the manifest. Returns PluginManifest or None."""
    from tap_plugins.manifest import PluginManifestError, load_manifest

    check = CheckResult(id="manifest-parse", name="Manifest parses and validates")

    manifest_path = plugin_root / "tap-plugin.toml"
    if not manifest_path.exists():
        check.fail("tap-plugin.toml not found")
        result.checks.append(check)
        return None

    try:
        manifest = load_manifest(plugin_root)
    except PluginManifestError as exc:
        check.fail(str(exc))
        result.checks.append(check)
        return None

    check.info(f"Plugin: {manifest.name} (slug={manifest.slug})")
    check.info(f"Version: {manifest.plugin_version}")
    surface_parts = []
    if manifest.models:
        surface_parts.append(f"{len(manifest.models)} model(s)")
    if manifest.edges:
        surface_parts.append(f"{len(manifest.edges)} edge(s)")
    if manifest.editors:
        surface_parts.append(f"{len(manifest.editors)} editor(s)")
    if manifest.searches:
        surface_parts.append(f"{len(manifest.searches)} search(es)")
    if manifest.grift:
        surface_parts.append(f"{len(manifest.grift)} grift bundle(s)")
    if surface_parts:
        check.info(f"Surfaces: {', '.join(surface_parts)}")
    else:
        check.info("No TAP surfaces declared")

    result.checks.append(check)
    return manifest


def _check_convention_dirs(manifest: Any, result: ValidationResult) -> None:
    check = CheckResult(id="convention-dirs", name="Convention directories present")

    required_when_declared = [
        (manifest.models, "models"),
        (manifest.edges, "edges"),
        (manifest.searches, "searches"),
        (manifest.grift, "grift"),
    ]

    for entries, dirname in required_when_declared:
        dir_path = manifest.plugin_root / dirname
        if entries:
            if dir_path.is_dir():
                check.info(f"{dirname}/ exists")
            else:
                check.fail(
                    f"[{dirname}] declared but {dirname}/ directory missing",
                    path=dirname,
                )
        elif dir_path.is_dir():
            check.info(f"{dirname}/ exists (no [{dirname}] declared)")

    result.checks.append(check)


def _check_edge_files(manifest: Any, result: ValidationResult) -> None:
    if not manifest.edges:
        return

    check = CheckResult(id="edge-files", name="Edge definition files valid")
    for edge in manifest.edges:
        check.info(
            f"Edge {edge.slug}: {edge.name} " f"(sources={edge.sources or 'any'}, targets={edge.targets or 'any'})"
        )
    result.checks.append(check)


def _check_grift_paths(manifest: Any, result: ValidationResult) -> None:
    if not manifest.grift:
        return

    check = CheckResult(id="grift-paths", name="GRIFT bundle paths exist")
    for entry in manifest.grift:
        full_path = manifest.plugin_root / entry.path
        if full_path.exists():
            check.info(f"Bundle '{entry.name}': {entry.path}")
        else:
            check.fail(f"Bundle '{entry.name}' path not found: {entry.path}", path=entry.path)
    result.checks.append(check)


def _check_undeclared_files(manifest: Any, result: ValidationResult) -> None:
    from tap_plugins.manifest import PluginManifest

    assert isinstance(manifest, PluginManifest)

    check = CheckResult(id="undeclared-files", name="No undeclared convention files")

    declared_grift_paths = {entry.path for entry in manifest.grift}
    declared_edge_paths = {entry.file_path for entry in manifest.edges}

    grift_dir = manifest.plugin_root / "grift"
    if grift_dir.is_dir():
        for grift_file in grift_dir.rglob("*.grift.json"):
            rel = str(grift_file.relative_to(manifest.plugin_root))
            if rel not in declared_grift_paths:
                check.warn(f"Undeclared GRIFT file: {rel}", path=rel)

    edges_dir = manifest.plugin_root / "edges"
    if edges_dir.is_dir():
        for edge_file in edges_dir.glob("*.edge.json"):
            rel = str(edge_file.relative_to(manifest.plugin_root))
            if rel not in declared_edge_paths:
                check.warn(f"Undeclared edge file: {rel}", path=rel)

    if check.status == "pass":
        check.info("All convention files are declared in the manifest")

    result.checks.append(check)


def _check_tests_dir(package_root: Path, result: ValidationResult) -> None:
    check = CheckResult(id="tests-dir", name="Tests directory exists and holds tests")
    # tests/ lives INSIDE the namespace package (tap_plugin/<slug>/tests/) so it
    # ships in the built wheel and travels with the plugin — the all-plugins CI
    # lane's coverage and an AI-legible corpus (see tap.plugin_testing).
    tests_dir = package_root / "tests"
    if not tests_dir.is_dir():
        check.warn("Missing tests/ directory", path="tests")
        result.checks.append(check)
        return

    # Existence is not coverage. A tests/ holding only __init__.py satisfies "the
    # directory is there" while `pytest --pyargs tap_plugin.<slug>` collects nothing,
    # so the plugin looks gated and is not — the exact shape of the two evicted
    # plugins whose suites were dead for two weeks (doc-plugin-eviction-plan.md).
    # Match pytest's own discovery patterns so this agrees with what actually runs.
    test_files = sorted(p.name for p in tests_dir.rglob("test_*.py")) + sorted(
        p.name for p in tests_dir.rglob("*_test.py")
    )
    if test_files:
        check.info(f"tests/ exists with {len(test_files)} test file(s)")
    else:
        check.warn(
            "tests/ exists but contains no test files (test_*.py / *_test.py) — "
            "`pytest --pyargs tap_plugin.<slug>` would collect nothing, so the plugin "
            "would appear gated while gating nothing",
            path="tests",
        )
    result.checks.append(check)


def _check_identity_coherence(
    plugin_root: Path,
    package_root: Path,
    manifest: Any,
    result: ValidationResult,
) -> None:
    """Verify the package-mode identity chain agrees end to end.

    req-tap-plugin-arch-identity requires a single identity to run unbroken across four
    surfaces: the manifest slug, the namespace package segment (``tap_plugin/<slug>/``),
    the distribution name (``tap-plugin-<slug>``), and the ``tap.plugins`` entry-point key.
    The pre-boot conformance gate enforces this from *installed* metadata; this check
    enforces the same chain from the *on-disk source tree* so a drift is caught at author
    time — before the plugin is ever built or installed. See req-tap-plugin-validate-identity.

    Legacy flat plugins (manifest at the plugin root, no ``tap_plugin/`` namespace and no
    ``pyproject.toml``) predate the identity chain; the check is reported as inapplicable
    rather than failing them.
    """
    import tomllib

    # tap.plugin_identity, NOT tap.preboot — same three symbols, but preboot imports
    # tap.plugin_source_auth -> tap.runtime_secrets -> tap.registry -> Django, and this
    # runs in the per-repo CI conformance job on a bare runner with no Django installed.
    # Enforced by tap/tests/test_plugin_identity.py, not just by this comment.
    from tap.plugin_identity import NAMESPACE_PACKAGE, TAP_PLUGINS_ENTRY_POINT_GROUP, dist_name_for_slug

    check = CheckResult(id="identity-coherence", name="Package identity chain agrees (slug/namespace/dist/entry-point)")
    slug = manifest.slug

    # Legacy flat layout: the package dir IS the plugin root, so there is no namespace
    # segment or pyproject to cross-check. Nothing to verify — report and return.
    if package_root == plugin_root:
        check.info(f"Legacy flat layout — package identity chain not applicable (slug={slug})")
        result.checks.append(check)
        return

    # 1) Namespace segment: tap_plugin/<segment>/ dir name must equal the slug.
    segment = package_root.name
    expected_parent = plugin_root / NAMESPACE_PACKAGE
    if package_root.parent != expected_parent:
        check.fail(
            f"Package dir {package_root} is not under {expected_parent} — "
            f"package-mode plugins live at {NAMESPACE_PACKAGE}/<slug>/ (req-tap-plugin-arch-identity-3)"
        )
    elif segment != slug:
        check.fail(
            f"Namespace segment {NAMESPACE_PACKAGE}.{segment} does not match manifest slug {slug!r} "
            f"— rename the package dir to {slug}"
        )
    else:
        check.info(f"Namespace: {NAMESPACE_PACKAGE}.{slug}")

    # 2) Distribution name + entry-point key from pyproject.toml.
    pyproject_path = plugin_root / "pyproject.toml"
    if not pyproject_path.is_file():
        check.fail("Package-mode plugin missing pyproject.toml", path="pyproject.toml")
        result.checks.append(check)
        return

    try:
        with pyproject_path.open("rb") as fh:
            pyproject = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        check.fail(f"pyproject.toml could not be parsed: {exc}", path="pyproject.toml")
        result.checks.append(check)
        return

    project = pyproject.get("project", {})
    expected_dist = dist_name_for_slug(slug)
    dist_name = project.get("name")
    if dist_name != expected_dist:
        check.fail(
            f"[project].name is {dist_name!r} but slug {slug!r} requires distribution "
            f"{expected_dist!r} (req-tap-plugin-arch-identity)",
            path="pyproject.toml",
        )
    else:
        check.info(f"Distribution: {expected_dist}")

    entry_points = project.get("entry-points", {}).get(TAP_PLUGINS_ENTRY_POINT_GROUP)
    if not isinstance(entry_points, dict) or not entry_points:
        check.fail(
            f'No [project.entry-points."{TAP_PLUGINS_ENTRY_POINT_GROUP}"] entry declared',
            path="pyproject.toml",
        )
    else:
        keys = sorted(entry_points)
        if keys != [slug]:
            check.fail(
                f"Entry-point group '{TAP_PLUGINS_ENTRY_POINT_GROUP}' declares {keys} — "
                f"expected exactly one key equal to the slug {slug!r}",
                path="pyproject.toml",
            )
        else:
            target = entry_points[slug]
            expected_prefix = f"{NAMESPACE_PACKAGE}.{slug}"
            if not isinstance(target, str) or not target.startswith(expected_prefix):
                check.fail(
                    f"Entry point '{slug}' points at {target!r} — expected a target under "
                    f"{expected_prefix} (its AppConfig)",
                    path="pyproject.toml",
                )
            else:
                check.info(f"Entry point: {slug} = {target}")

    result.checks.append(check)


def _check_declared_dependencies(package_root: Path, manifest: Any, result: ValidationResult) -> None:
    """Verify every cross-plugin ``tap_plugin.<other>`` import is declared in ``depends_on``.

    req-tap-plugin-arch-dependencies requires each plugin's manifest ``depends_on`` to cover
    every OTHER plugin it imports, so the boot install order can satisfy them. The pre-boot
    dependency-consistency guard enforces ``declared ⊇ observed`` across the whole profile;
    this check applies the same rule to a single plugin at author time. Declared-but-unimported
    edges (pure data/vocabulary dependencies, e.g. one plugin seeding another's node types) are
    legitimate and not flagged. See req-tap-plugin-validate-deps.
    """
    from tap import plugin_deps

    check = CheckResult(id="declared-dependencies", name="Cross-plugin imports are declared in depends_on")

    observed = plugin_deps.scan_observed_imports(package_root, manifest.slug)
    declared = {dep.slug for dep in plugin_deps.read_declared_depends_on(package_root)}

    undeclared = sorted(observed - declared)
    for missing in undeclared:
        check.fail(
            f"imports 'tap_plugin.{missing}' but does not declare it in depends_on — "
            f'add {{ slug = "{missing}" }} to depends_on (req-tap-plugin-arch-dependencies)'
        )

    for dep in sorted(observed & declared):
        check.info(f"declared + imported: {dep}")
    for dep in sorted(declared - observed):
        check.info(f"declared (data/vocabulary dependency, not imported): {dep}")
    if not observed and not declared:
        check.info("No cross-plugin dependencies")

    result.checks.append(check)


def _check_requires_tap(manifest: Any, result: ValidationResult) -> None:
    """Verify the plugin's ``requires_tap`` compatibility floor against this harness core.

    ``req-tap-plugin-extdev-compat-floor`` (the VS Code ``engines.vscode`` model): a plugin
    declares the range of core (``tap``) versions it supports; the pre-boot gate refuses
    a mismatch at standup. This author-time check surfaces the same thing in the
    developer's own cloned-core harness — a declared floor the harness core does *not*
    satisfy is a failure, so the developer sees the mismatch before release rather than
    at their users' boot. An absent floor is informational only: ``requires_tap`` is
    optional in v0 (``req-tap-plugin-extdev-compat-floor-4``), so absence must NOT fail — not
    even under ``--strict`` (a warning would, and strict is the reusable-CI conformance
    gate). It tightens to a warning/failure in a later version once every TAP-owned plugin
    declares one. The specifier itself is already validated at manifest parse (a malformed
    value fails the manifest-parse check upstream), so here it is either None or well-formed.
    """
    from tap.core_version import CoreVersionError, core_satisfies_requires_tap, core_tap_version

    check = CheckResult(id="requires-tap", name="Compatibility floor (requires_tap) is declared and satisfied")

    requires_tap = getattr(manifest, "requires_tap", None)
    if requires_tap is None:
        check.info(
            "no requires_tap declared (optional in v0) — recommend declaring the range of TAP core "
            'versions this plugin supports (e.g. requires_tap = ">=0.1,<0.2") so an incompatible core '
            "is refused at boot"
        )
        result.checks.append(check)
        return

    try:
        core_version = core_tap_version()
    except CoreVersionError as exc:
        check.info(
            f"requires_tap = {requires_tap!r}; harness core version could not be resolved ({exc}) — not verified here"
        )
        result.checks.append(check)
        return

    if core_satisfies_requires_tap(requires_tap, core_version=core_version):
        check.info(f"requires_tap = {requires_tap!r}; satisfied by harness core {core_version}")
    else:
        check.fail(
            f"requires_tap = {requires_tap!r} is NOT satisfied by this harness core {core_version} — "
            f"the plugin would be refused at boot against this core"
        )

    result.checks.append(check)


# ---------------------------------------------------------------------------
# Loads-level checks (requires Django app registry)
# ---------------------------------------------------------------------------


def _run_loads_checks(manifest: Any, result: ValidationResult) -> None:
    """Run loads-level checks: class-path validation via Django imports."""
    _check_model_classes(manifest, result)
    _check_model_icons(manifest, result)
    _check_editor_classes(manifest, result)
    _check_search_callables(manifest, result)


def _check_model_classes(manifest: Any, result: ValidationResult) -> None:
    if not manifest.models:
        return

    check = CheckResult(id="model-classes", name="Model classes import and validate")

    from django.utils.module_loading import import_string

    for entry in manifest.models:
        try:
            cls = import_string(entry.class_path)
        except ImportError as exc:
            check.fail(
                f"Cannot import '{entry.class_path}': {exc}",
                path=entry.class_path,
            )
            continue
        except Exception as exc:
            check.fail(
                f"'{entry.class_path}' raised {type(exc).__name__}: {exc}",
                path=entry.class_path,
            )
            continue

        entity_type = getattr(cls, "ENTITY_TYPE", None)
        if entity_type != entry.slug:
            check.fail(
                f"'{entry.class_path}' ENTITY_TYPE='{entity_type}' " f"does not match manifest slug='{entry.slug}'",
                path=entry.class_path,
            )
            continue

        check.info(f"Model {entry.slug}: {entry.class_path}")

    result.checks.append(check)


def _check_model_icons(manifest: Any, result: ValidationResult) -> None:
    """Validate that models with ENTITY_ICON have valid keys and existing SVG files."""
    if not manifest.models:
        return

    check = CheckResult(id="model-icons", name="Model icons exist")

    from django.contrib.staticfiles import finders
    from django.utils.module_loading import import_string

    from tap_grid.icon import validate_icon_key

    seen_keys: set[str] = set()

    for entry in manifest.models:
        try:
            cls = import_string(entry.class_path)
        except Exception:
            continue  # already reported by model-classes check

        icon_key = getattr(cls, "ENTITY_ICON", "")
        if not icon_key:
            continue

        # Deduplicate — multiple models may share an icon key
        if icon_key in seen_keys:
            continue
        seen_keys.add(icon_key)

        if not validate_icon_key(icon_key):
            check.fail(
                f"'{entry.slug}' ENTITY_ICON='{icon_key}' is not valid kebab-case",
                path=entry.class_path,
            )
            continue

        static_path = f"{manifest.slug}/icons/{icon_key}.svg"
        if finders.find(static_path):
            check.info(f"Icon '{icon_key}': {static_path}")
        else:
            check.fail(
                f"Icon '{icon_key}' SVG not found at {static_path}",
                path=static_path,
            )

    if not seen_keys:
        check.info("No models declare ENTITY_ICON")

    result.checks.append(check)


def _check_editor_classes(manifest: Any, result: ValidationResult) -> None:
    if not manifest.editors:
        return

    check = CheckResult(id="editor-classes", name="Editor classes import and validate")

    from django.utils.module_loading import import_string

    from tap_web.editor import EditorDescriptor

    for entry in manifest.editors:
        try:
            cls = import_string(entry.class_path)
            instance = cls()
        except ImportError as exc:
            check.fail(f"Cannot import '{entry.class_path}': {exc}", path=entry.class_path)
            continue
        except Exception as exc:
            check.fail(f"Cannot instantiate '{entry.class_path}': {exc}", path=entry.class_path)
            continue

        if not isinstance(instance, EditorDescriptor):
            check.fail(
                f"'{entry.class_path}' is not an EditorDescriptor subclass",
                path=entry.class_path,
            )
            continue

        if instance.entity_type != entry.entity_type:
            check.fail(
                f"'{entry.class_path}' entity_type='{instance.entity_type}' "
                f"does not match manifest key='{entry.entity_type}'",
                path=entry.class_path,
            )
            continue

        check.info(f"Editor {entry.entity_type}: {entry.class_path}")

    result.checks.append(check)


def _check_search_callables(manifest: Any, result: ValidationResult) -> None:
    if not manifest.searches:
        return

    check = CheckResult(id="search-callables", name="Search callables import and validate")

    from django.utils.module_loading import import_string

    for entry in manifest.searches:
        try:
            obj = import_string(entry.callable_path)
        except ImportError as exc:
            check.fail(f"Cannot import '{entry.callable_path}': {exc}", path=entry.callable_path)
            continue
        except Exception as exc:
            check.fail(
                f"'{entry.callable_path}' raised {type(exc).__name__}: {exc}",
                path=entry.callable_path,
            )
            continue

        if not callable(obj):
            check.fail(
                f"'{entry.callable_path}' is not callable",
                path=entry.callable_path,
            )
            continue

        check.info(f"Search {entry.runner_key}: {entry.callable_path}")

    result.checks.append(check)


# ---------------------------------------------------------------------------
# Runs-level checks (requires Django + database, uses rollback transaction)
# ---------------------------------------------------------------------------


def _run_runs_checks(manifest: Any, result: ValidationResult) -> None:
    """Run runs-level checks inside a transaction that is always rolled back."""
    from django.db import transaction

    from tap_grid.batch import create_batch
    from tap_grid.caller_context import CallerContext

    class _RollbackValidation(Exception):
        """Sentinel to force transaction rollback after validation completes."""

    try:
        with transaction.atomic():
            batch = create_batch(
                source=f"validate_plugin:{manifest.slug}",
                name=f"Plugin validation: {manifest.slug}",
                description=f"Smoke-test batch created by validate_plugin --level runs "
                f"for '{manifest.slug}'. Rolled back on completion.",
            )
            ctx = CallerContext(batch_id=str(batch.entity_id))

            _check_create_nodes(manifest, result, caller_context=ctx)
            _check_create_edges(manifest, result, caller_context=ctx)
            _check_grift_import(manifest, result)

            raise _RollbackValidation()
    except _RollbackValidation:
        pass


def _generate_payload(model_cls: type) -> dict[str, Any]:
    """Auto-generate a minimal valid payload for create_node from FIELD_CRUD_SCHEMA + CREATE_REQUIRED."""
    field_schema: dict[str, dict] = getattr(model_cls, "FIELD_CRUD_SCHEMA", {})
    create_required: list[str] = getattr(model_cls, "CREATE_REQUIRED", [])

    payload: dict[str, Any] = {}
    for field_name in create_required:
        schema = field_schema.get(field_name, {})
        payload[field_name] = _synthetic_value(schema)

    return payload


def _synthetic_value(schema: dict[str, Any]) -> Any:
    """Generate a synthetic value from a JSON Schema type declaration."""
    type_decl = schema.get("type", "string")

    # Handle nullable types like ["string", "null"]
    if isinstance(type_decl, list):
        type_decl = next((t for t in type_decl if t != "null"), "string")

    if type_decl == "string":
        min_length = schema.get("minLength", 1)
        enum = schema.get("enum")
        if enum:
            return enum[0]
        return "t" * max(min_length, 1)
    elif type_decl == "integer":
        return 1
    elif type_decl == "boolean":
        return False
    elif type_decl == "object":
        return {}
    elif type_decl == "array":
        return []
    elif type_decl == "number":
        return 1.0
    else:
        return "test"


def _generate_edge_properties(property_schema: dict[str, Any]) -> dict[str, Any]:
    """Auto-generate edge properties from a property_schema with required fields."""
    properties: dict[str, Any] = {}
    required = property_schema.get("required", [])
    schema_props = property_schema.get("properties", {})

    for field_name in required:
        field_schema = schema_props.get(field_name, {})
        properties[field_name] = _synthetic_value(field_schema)

    return properties


def _check_create_nodes(manifest: Any, result: ValidationResult, *, caller_context: Any = None) -> None:
    if not manifest.models:
        return

    check = CheckResult(id="create-nodes", name="create_node succeeds for declared models")

    from django.utils.module_loading import import_string

    from tap_grid.services import create_node

    for entry in manifest.models:
        try:
            cls = import_string(entry.class_path)
        except ImportError:
            check.fail(f"Cannot import '{entry.class_path}'", path=entry.class_path)
            continue

        payload = _generate_payload(cls)

        try:
            write_result = create_node(entry.slug, payload, caller_context=caller_context)
        except Exception as exc:
            check.fail(
                f"create_node('{entry.slug}') raised: {exc}",
                path=entry.slug,
            )
            continue

        if write_result.success:
            check.info(f"create_node('{entry.slug}') OK")
        else:
            error_msgs = "; ".join(f"{e.field}: {e.message}" if e.field else e.message for e in write_result.errors)
            check.fail(
                f"create_node('{entry.slug}') failed: {error_msgs}",
                path=entry.slug,
            )

    result.checks.append(check)


def _check_create_edges(manifest: Any, result: ValidationResult, *, caller_context: Any = None) -> None:
    if not manifest.edges:
        return

    # Only test edges that have both explicit sources and targets
    testable_edges = [e for e in manifest.edges if e.sources and e.targets]
    if not testable_edges:
        return

    check = CheckResult(id="create-edges", name="create_edge succeeds for constrained edge types")

    from tap_grid.models import Entity
    from tap_grid.registry import get_model_class
    from tap_grid.services import create_edge, create_node, resolve_entity

    # Build a cache of entities we've already created for source/target types
    entity_cache: dict[str, Entity] = {}

    def _ensure_entity(type_slug: str) -> Entity | None:
        if type_slug in entity_cache:
            return entity_cache[type_slug]
        try:
            model_cls = get_model_class(type_slug)
        except KeyError:
            return None
        payload = _generate_payload(model_cls)
        try:
            wr = create_node(type_slug, payload, caller_context=caller_context)
        except Exception:
            return None
        if not wr.success or wr.entity_id is None:
            return None
        entity = resolve_entity(wr.entity_id)
        entity_cache[type_slug] = entity
        return entity

    for edge in testable_edges:
        source_type = edge.sources[0]
        target_type = edge.targets[0]

        source_entity = _ensure_entity(source_type)
        if source_entity is None:
            check.fail(
                f"Cannot create source entity '{source_type}' for edge '{edge.slug}'",
                path=edge.slug,
            )
            continue

        target_entity = _ensure_entity(target_type)
        if target_entity is None:
            check.fail(
                f"Cannot create target entity '{target_type}' for edge '{edge.slug}'",
                path=edge.slug,
            )
            continue

        # Auto-generate edge properties if the edge has a property_schema with required fields
        properties = _generate_edge_properties(edge.property_schema) if edge.property_schema else None

        try:
            create_edge(source_entity, target_entity, edge.slug, properties=properties)
            check.info(f"create_edge('{source_type}' -> '{target_type}', '{edge.slug}') OK")
        except Exception as exc:
            check.fail(
                f"create_edge('{source_type}' -> '{target_type}', '{edge.slug}') " f"raised: {exc}",
                path=edge.slug,
            )

    result.checks.append(check)


def _check_grift_import(manifest: Any, result: ValidationResult) -> None:
    if not manifest.grift:
        return

    check = CheckResult(id="grift-import", name="GRIFT bundles import successfully")

    import json as json_mod

    try:
        from tap_grid.grift import grift_import
    except ImportError:
        check.fail("tap_grid.grift not available")
        result.checks.append(check)
        return

    for entry in manifest.grift:
        grift_path = manifest.plugin_root / entry.path
        try:
            with open(grift_path) as fh:
                document = json_mod.load(fh)
            import_result = grift_import(  # TAP-AUTHZ-COV: validate_plugin CLI conformance dry-run (actor=None); not request-reachable
                document, dangling_edge_mode="warn", actor=None
            )
        except Exception as exc:
            check.fail(
                f"GRIFT bundle '{entry.name}' import raised: {exc}",
                path=entry.path,
            )
            continue

        if import_result.success:
            counts = import_result.counts
            check.info(f"Bundle '{entry.name}': {counts.nodes_imported} node(s), " f"{counts.edges_imported} edge(s)")
            for w in import_result.warnings:
                check.warn(
                    f"Bundle '{entry.name}' [{w.phase}]: {w.message}",
                    path=entry.path,
                )
        else:
            error_msgs = "; ".join(f"[{e.phase}] {e.path}: {e.message}" for e in import_result.errors)
            check.fail(
                f"Bundle '{entry.name}' import failed: {error_msgs}",
                path=entry.path,
            )

    result.checks.append(check)
