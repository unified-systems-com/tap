"""Crypto Bill-of-Materials scanner (req-fips-crypto-bom) — the build-time FIPS-provider gate.

Enumerates every cryptographic *provider* actually present in an environment (core's venv + image
binaries, or a single plugin's closure) and classifies each against the curated registry in
`tap.crypto_providers`. A provider with no disposition, or a `MUST_FIX` disposition, fails the gate.

Why a scanner and not just the boot self-check: `tap.fips` proves the *OpenSSL-backed Python* layer
is enforced, but it is blind to a Go binary, a Rust crate on `ring`/`aws-lc-rs`, or a `libsodium`
wheel — those carry their own crypto, ignore `OPENSSL_CONF`, and would silently run non-FIPS crypto
with no error (doc-fips-assessment-record.md L17). This detects them by fingerprinting the real ELF
artifacts, so a dependency or binary that leaks a non-validated provider is caught at build time.

Positioned for plugins: `scan()` takes explicit roots, so per-plugin conformance can scan a single
plugin's isolated closure — plugins run in the same image/process, so a plugin leak defeats a
FIPS-capable core. The core gate (`core_report()`) scans the installed union, which under the
`test_all` profile already contains every plugin's dependency closure.

Anti-fail-open (doc L2/L12): the scan is only trustworthy if it actually read binaries. `core_report()`
records what it detected, and the gate test asserts the known-present validated providers were seen —
so an empty scan (wrong root, unreadable files) fails loudly instead of reporting a false all-clear.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import importlib.metadata as importlib_metadata
import json
import os
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

from tap.boot_naming import profile_path
from tap.crypto_providers import (
    DISPOSITIONS,
    JVM_ARTIFACT_SUFFIXES,
    JVM_EXECUTABLES,
    JVM_RUNTIME_FILES,
    KNOWN_JVM_DISTRIBUTIONS,
    KNOWN_NONFIPS_DISTRIBUTIONS,
    KNOWN_WASM_DISTRIBUTIONS,
    NONVALIDATED_CRYPTO_IMPORTS,
    SIGNATURES,
    WASM_RUNTIME_IMPORTS,
    WEAK_DIGEST_CALLS,
    Boundary,
    Disposition,
    Waiver,
)

ELF_MAGIC = b"\x7fELF"
#: Skip reading any single file larger than this (crypto libs are a few MB; a huge blob is not one).
_MAX_READ_BYTES = 96 * 1024 * 1024

# Core-environment defaults (inside the web container). `/bin`→`/usr/bin` (L4), so `/usr/bin` covers both.
_VENV_ROOT = Path("/app/.venv")
_BINARY_ROOTS = (Path("/usr/bin"),)
#: Where a bundled libcrypto/libssl FILE (the psycopg[binary] class) would hide.
_LIBCRYPTO_ROOTS = (Path("/usr/lib"), Path("/app/.venv"))
#: Real (symlink-resolved) directories where the one legitimate system OpenSSL lives (`/lib`→`/usr/lib`).
_SYSTEM_LIB_DIRS = frozenset({"/usr/lib"})


@dataclass(frozen=True)
class Finding:
    """One (artifact, provider) pair and its resolved disposition. `boundary is None` = unclassified.

    `waived` records an OPERATOR waiver (with `waiver_reason`) that excuses an otherwise-failing
    finding in a FIPS deployment. A waived finding is not a failure, but it is still *recorded* — the
    exception is visible with its justification, never silently dropped."""

    artifact: str
    provider: str
    boundary: Boundary | None
    detail: str
    rid: str | None
    waived: bool = False
    waiver_reason: str | None = None

    @property
    def is_failure(self) -> bool:
        # Unclassified (no disposition) or an in-boundary non-validated provider fails the gate —
        # unless an operator has waived it (with a reason).
        if self.waived:
            return False
        return self.boundary is None or self.boundary is Boundary.MUST_FIX


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    scanned_files: int = 0
    unreadable: list[str] = field(default_factory=list)

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.is_failure]

    @property
    def detected_providers(self) -> set[str]:
        return {f.provider for f in self.findings}


def fingerprint(data: bytes) -> set[str]:
    """Return the set of provider names whose signature (ALL needles) is present in `data`."""
    providers: set[str] = set()
    for sig in SIGNATURES:
        if all(needle in data for needle in sig.needles):
            providers.add(sig.provider)
    return providers


def _read(path: Path) -> bytes | None:
    """Read a file's bytes, or None if it cannot be read (recorded by the caller, never silently
    dropped — an error-suppressing discovery step is the L2 fail-open trap)."""
    try:
        if path.stat().st_size > _MAX_READ_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _iter_native_files(roots: Iterable[Path]) -> Iterator[Path]:
    """Yield each distinct ELF file under the given roots as its resolved (real) path.

    Dedups by real path, so the Wolfi `/bin`→`/usr/bin` and `/lib`→`/usr/lib` symlinks (L4) do not
    double-count a file, and the canonical path is what dispositions match against."""
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            candidates: Iterable[Path] = (root,)
        elif root.is_dir():
            candidates = (p for p in root.rglob("*") if p.is_file())
        else:
            continue
        for path in candidates:
            try:
                real = path.resolve()
                if real in seen:
                    continue
                with real.open("rb") as fh:
                    if fh.read(4) == ELF_MAGIC:
                        seen.add(real)
                        yield real
            except OSError:
                continue


def _disposition_for(artifact: str, provider: str) -> Disposition | None:
    """Resolve the disposition for a finding: an fnmatch on the artifact path/name, provider exact
    or '*'. First match wins (registry order)."""
    for d in DISPOSITIONS:
        if (d.provider in (provider, "*")) and fnmatch.fnmatch(artifact, d.artifact):
            return d
    return None


def _classify_artifact(path: Path, providers: set[str]) -> list[Finding]:
    """Turn one artifact's detected providers into findings.

    - `openssl-system` → a VALIDATED finding (routes through the #4282 provider);
    - a non-OpenSSL provider (go/ring/aws-lc/libsodium/…) → a finding that must be dispositioned;
      an undispositioned one is unclassified (boundary None) and fails the gate.
    """
    artifact = str(path)
    findings: list[Finding] = []
    for provider in sorted(providers):
        if provider == "openssl-system":
            findings.append(
                Finding(artifact, provider, Boundary.VALIDATED, "links system OpenSSL", "req-fips-crypto-bom")
            )
            continue
        disp = _disposition_for(artifact, provider)
        if disp is None:
            findings.append(Finding(artifact, provider, None, "no disposition — an unclassified crypto provider", None))
        else:
            findings.append(Finding(artifact, provider, disp.boundary, disp.rationale, disp.rid))
    return findings


def _libcrypto_findings(roots: Iterable[Path]) -> list[Finding]:
    """A libcrypto/libssl FILE whose real path is outside the system lib dir is a bundled OpenSSL
    (e.g. a wheel shipping its own `libcrypto-<hash>.so.3`) — the psycopg[binary] class, separate-file
    form. Dedups by real path so the `/lib`→`/usr/lib` symlink (L4) is not mistaken for a second copy."""
    findings: list[Finding] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not (path.name.startswith(("libcrypto", "libssl")) and (".so" in path.name)):
                continue
            try:
                real = path.resolve()
            except OSError:
                continue
            if real in seen or not real.is_file():
                continue
            seen.add(real)
            if str(real.parent) not in _SYSTEM_LIB_DIRS:
                findings.append(
                    Finding(
                        str(real),
                        "openssl-bundled-file",
                        Boundary.MUST_FIX,
                        "a bundled libcrypto/libssl outside the system dir — build the dependency against "
                        "the system OpenSSL instead (L17)",
                        "req-fips-crypto-bom",
                    )
                )
    return findings


def _distribution_findings(dist_names: Iterable[str]) -> list[Finding]:
    """Name-based findings for Python distributions whose crypto byte-fingerprinting cannot reach
    (pure-Python, or an indirect link) — the belt to the fingerprinter's braces."""
    findings: list[Finding] = []
    for raw in dist_names:
        name = raw.lower().replace("_", "-")
        if name in KNOWN_NONFIPS_DISTRIBUTIONS:
            disp = _disposition_for(name, "*")
            if disp is None:
                findings.append(
                    Finding(
                        f"dist:{name}",
                        "python-nonfips-crypto",
                        None,
                        "known non-FIPS crypto distribution, no disposition",
                        None,
                    )
                )
            else:
                findings.append(
                    Finding(f"dist:{name}", "python-nonfips-crypto", disp.boundary, disp.rationale, disp.rid)
                )
    return findings


def _jvm_findings(roots: Iterable[Path], dist_names: Iterable[str]) -> list[Finding]:
    """Fail-closed tripwire: a JVM/Java runtime, executable, artifact, or bridge distribution has
    arrived. Java crypto uses JCA providers (BouncyCastle → BC-FIPS), not OpenSSL, and is invisible to
    the ELF fingerprinter (jars/classes are not ELF), so its arrival must fail the gate loudly rather
    than ship a silent non-FIPS JVM (req-fips-crypto-bom residual (a))."""

    def _tripwire(artifact: str, what: str) -> Finding:
        return Finding(
            artifact,
            "jvm-detected",
            Boundary.MUST_FIX,
            f"a JVM/Java {what} arrived — the crypto-BOM does not yet reason about JVM crypto (JCA "
            "providers / BouncyCastle vs BC-FIPS). Now is the time to build the Java crypto layer, or "
            "remove it.",
            "req-fips-crypto-bom",
        )

    findings: list[Finding] = []
    seen: set[str] = set()
    for root in roots:
        candidates: Iterable[Path] = (root,) if root.is_file() else (root.rglob("*") if root.is_dir() else ())
        for path in candidates:
            name = path.name
            what = None
            if name in JVM_RUNTIME_FILES:
                what = "runtime (libjvm.so)"
            elif name in JVM_EXECUTABLES:
                what = f"executable ({name})"
            elif name.endswith(JVM_ARTIFACT_SUFFIXES):
                what = f"artifact ({name})"
            if what is not None and str(path) not in seen:
                seen.add(str(path))
                findings.append(_tripwire(str(path), what))
    for raw in dist_names:
        dist = raw.lower().replace("_", "-")
        if dist in KNOWN_JVM_DISTRIBUTIONS:
            findings.append(_tripwire(f"dist:{dist}", f"bridge distribution ({dist})"))
    return findings


# Source files whose crypto references are intentional and must NOT be flagged: test code (which
# exercises crypto, including MD5 negative controls) and the FIPS self-check itself (`tap/fips.py`
# deliberately executes MD5 to prove it is refused).


def _skip_source_file(path: Path) -> bool:
    """A test file (basename `test_*.py` or inside a `tests/` package) or the FIPS self-check itself —
    all of which legitimately reference/execute non-approved crypto. Basename-matched so an arbitrary
    scratch/tmp directory that merely happens to be named `test_*` is not mistaken for test code."""
    spath = str(path)
    return path.name.startswith("test_") or "/tests/" in spath or spath.endswith("/tap/fips.py")


def _classify_source_import(artifact: str, module_full: str) -> Finding | None:
    """Classify one import: a WASM runtime, or a non-validated crypto module → a finding; else None.
    `hashlib`/`hmac`/`secrets`/`ssl`/`cryptography`/`psycopg` are absent from the registry, so they
    (correctly) yield no finding — they route through the system OpenSSL."""
    top = module_full.split(".", 1)[0]
    if top in WASM_RUNTIME_IMPORTS or module_full in WASM_RUNTIME_IMPORTS:
        return Finding(
            artifact,
            "wasm-runtime",
            Boundary.MUST_FIX,
            f"imports a WASM runtime ({module_full}) — WASM crypto can execute here and the crypto-BOM "
            "does not yet reason about it (jars/.wasm are opaque). Review + classify, or remove.",
            "req-fips-crypto-bom-source",
        )
    note = NONVALIDATED_CRYPTO_IMPORTS.get(module_full) or NONVALIDATED_CRYPTO_IMPORTS.get(top)
    if note is None:
        return None
    disp = _disposition_for(artifact, f"src:{top}")
    if disp is None:
        return Finding(
            artifact,
            f"src:{top}",
            None,
            f"imports non-validated crypto '{module_full}' — {note}. Route it through the system OpenSSL, "
            "remove it, or (in a plugin) declare [fips] uses-nonvalidated with an operator waiver.",
            None,
        )
    return Finding(artifact, f"src:{top}", disp.boundary, disp.rationale, disp.rid)


def _weak_digest_finding(artifact: str, node: ast.Call) -> Finding | None:
    """Flag a bare non-approved digest for a SECURITY use — `hashlib.md5(...)`, `hashlib.new("md5", ...)`,
    or a bare `md5(...)` — without `usedforsecurity=False`. MD5-for-security hard-fails under FIPS at
    runtime, so this is a latent bomb; the scan catches it at build time (automating F13). SHA-1 is
    FIPS-approved as a hash and is NOT flagged."""
    func = node.func
    digest: str | None = None
    if isinstance(func, ast.Attribute):
        if func.attr in WEAK_DIGEST_CALLS:
            digest = func.attr
        elif (
            func.attr == "new"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in WEAK_DIGEST_CALLS
        ):
            digest = str(node.args[0].value)
    elif isinstance(func, ast.Name) and func.id in WEAK_DIGEST_CALLS:
        digest = func.id
    if digest is None:
        return None
    for kw in node.keywords:
        if kw.arg == "usedforsecurity" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
            return None  # the auditor-recognized non-security signal — permitted
    return Finding(
        f"{artifact}:{node.lineno}",
        f"weak-digest-{digest}",
        Boundary.MUST_FIX,
        f"bare {digest.upper()} for a security use — refused under FIPS at runtime (a latent bomb). Use an "
        "approved digest, or pass usedforsecurity=False if the use is genuinely non-security.",
        "req-fips-crypto-bom-source",
    )


def _source_findings(roots: Iterable[Path]) -> list[Finding]:
    """AST-scan `.py` source under roots for non-validated crypto imports, WASM-runtime imports, and
    bare weak-digest usage — the Python analog of the ELF fingerprinter (req-fips-crypto-bom-source).
    AST (not grep) so a string literal like `"md5"` in a data table is not mistaken for a call."""
    findings: list[Finding] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        files = (root,) if root.is_file() else root.rglob("*.py")
        for path in files:
            if path.suffix != ".py" or path in seen:
                continue
            seen.add(path)
            if _skip_source_file(path):
                continue
            spath = str(path)
            try:
                tree = ast.parse(path.read_bytes())
            except OSError, SyntaxError, ValueError:
                continue  # unparseable (e.g. a py2 file); the ELF/dist layers still cover its package
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        f = _classify_source_import(f"{spath}:{node.lineno}", alias.name)
                        if f is not None:
                            findings.append(f)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    f = _classify_source_import(f"{spath}:{node.lineno}", node.module)
                    if f is not None:
                        findings.append(f)
                elif isinstance(node, ast.Call):
                    f = _weak_digest_finding(spath, node)
                    if f is not None:
                        findings.append(f)
    return findings


def _wasm_dist_findings(dist_names: Iterable[str]) -> list[Finding]:
    """A WASM-runtime distribution is installed → the same tripwire as an imported runtime."""
    findings: list[Finding] = []
    for raw in dist_names:
        dist = raw.lower().replace("_", "-")
        if dist in KNOWN_WASM_DISTRIBUTIONS:
            findings.append(
                Finding(
                    f"dist:{dist}",
                    "wasm-runtime",
                    Boundary.MUST_FIX,
                    f"a WASM runtime distribution ({dist}) is installed — WASM crypto can execute here and "
                    "the crypto-BOM does not yet reason about it. Review + classify.",
                    "req-fips-crypto-bom-source",
                )
            )
    return findings


def _plugin_source_roots() -> tuple[Path, ...]:
    """The installed plugin namespace packages (`.venv/**/site-packages/tap_plugin/…`) — where a
    git-sourced plugin's Python source lives, for the source scan."""
    return tuple((_VENV_ROOT / "lib").glob("python*/site-packages/tap_plugin"))


def scan(
    native_roots: Iterable[Path],
    dist_names: Iterable[str] = (),
    libcrypto_roots: Iterable[Path] = (),
    jvm_roots: Iterable[Path] = (),
    source_roots: Iterable[Path] = (),
) -> Report:
    """Scan the given roots and distributions, returning a Report. This is the reusable core — the
    same call scans core's environment or a single plugin's closure, only the roots differ."""
    dist_names = list(dist_names)
    report = Report()
    for path in _iter_native_files(native_roots):
        report.scanned_files += 1
        data = _read(path)
        if data is None:
            report.unreadable.append(str(path))
            continue
        providers = fingerprint(data)
        if providers:
            report.findings.extend(_classify_artifact(path, providers))
    report.findings.extend(_libcrypto_findings(libcrypto_roots))
    report.findings.extend(_distribution_findings(dist_names))
    report.findings.extend(_jvm_findings(jvm_roots, dist_names))
    report.findings.extend(_source_findings(source_roots))
    report.findings.extend(_wasm_dist_findings(dist_names))
    return report


def core_report() -> Report:
    """Scan the core web-container environment: the venv's native extensions, the image binaries TAP
    ships/execs, the libcrypto search paths, and TAP + plugin Python SOURCE (imports / weak digests /
    WASM runtimes). Under `test_all` the venv is the full plugin union."""
    dist_names = [d.metadata["Name"] for d in importlib_metadata.distributions() if d.metadata["Name"]]
    core_src = tuple(p for p in Path("/app").glob("tap*") if p.is_dir())
    return scan(
        native_roots=(_VENV_ROOT, *_BINARY_ROOTS),
        dist_names=dist_names,
        libcrypto_roots=_LIBCRYPTO_ROOTS,
        jvm_roots=(_VENV_ROOT, *_BINARY_ROOTS, *_LIBCRYPTO_ROOTS),
        source_roots=(*core_src, *_plugin_source_roots()),
    )


class WaiverError(ValueError):
    """A malformed operator waiver (e.g. a missing/blank reason)."""


def load_waivers(raw: Iterable[object]) -> list[Waiver]:
    """Parse operator `fips_waivers` (from the boot profile) into Waivers, fail-closed.

    Each entry must be `{plugin|artifact, provider?, reason}` with a NON-EMPTY reason — you cannot
    waive a FIPS requirement silently. A blank reason or a non-dict entry is a hard error, not a
    tolerated skip (an ignored waiver would fail-open into an unexplained exception)."""
    waivers: list[Waiver] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise WaiverError(f"fips_waivers[{i}] must be an object, got {type(entry).__name__}")
        artifact = entry.get("artifact") or entry.get("plugin")
        reason = entry.get("reason")
        if not isinstance(artifact, str) or not artifact:
            raise WaiverError(f"fips_waivers[{i}] needs a non-empty 'plugin' or 'artifact' glob")
        if not isinstance(reason, str) or not reason.strip():
            raise WaiverError(
                f"fips_waivers[{i}] ('{artifact}') needs a non-empty 'reason' — a FIPS waiver must be justified"
            )
        provider = entry.get("provider", "*")
        if not isinstance(provider, str):
            raise WaiverError(f"fips_waivers[{i}] 'provider' must be a string")
        waivers.append(Waiver(artifact=artifact, provider=provider, reason=reason.strip()))
    return waivers


def _waiver_matches(waiver: Waiver, finding: Finding) -> bool:
    if waiver.provider not in (finding.provider, "*"):
        return False
    # Match the artifact path OR a plugin-slug fragment of it (a plugin owns files under .../<slug>/…).
    return fnmatch.fnmatch(finding.artifact, waiver.artifact) or f"/{waiver.artifact}/" in f"/{finding.artifact}/"


def apply_waivers(report: Report, waivers: Iterable[Waiver]) -> Report:
    """Return a new Report with every failing finding an operator waiver matches marked waived (with
    its reason). Waived findings stop being failures but remain recorded — the exception stays visible."""
    waivers = list(waivers)
    new_findings: list[Finding] = []
    for f in report.findings:
        if f.is_failure:
            match = next((w for w in waivers if _waiver_matches(w, f)), None)
            if match is not None:
                new_findings.append(replace(f, waived=True, waiver_reason=match.reason))
                continue
        new_findings.append(f)
    return Report(findings=new_findings, scanned_files=report.scanned_files, unreadable=list(report.unreadable))


def scan_plugin(plugin_root: Path, dist_names: Iterable[str] = ()) -> Report:
    """Scan a SINGLE plugin's shipped artifacts (native files + jars under its root) and declared
    distributions — the per-plugin conformance surface. A plugin is usually pure Python, so this
    catches the cases that matter: a plugin bundling a native `.so`/binary with non-validated crypto,
    a JVM artifact, a declared dependency known to carry non-FIPS crypto, or its own Python source
    importing pure-Python crypto / using a bare weak digest / pulling a WASM runtime (`req-fips-crypto-bom`)."""
    root = Path(plugin_root)
    return scan(
        native_roots=(root,), dist_names=dist_names, libcrypto_roots=(root,), jvm_roots=(root,), source_roots=(root,)
    )


def _fips_mode_on() -> bool:
    """Whether the running image declares FIPS mode (`TAP_FIPS_MODE=1`; see tap.fips)."""
    return os.environ.get("TAP_FIPS_MODE", "0").strip() == "1"


def _profile_waivers(profile_id: str) -> list[Waiver]:
    """Read `fips_waivers` from `boot/<profile_id>.boot.json` (settings-free, like tap.preboot).

    Missing profile / missing section → no waivers (an absent profile is not an error here; the boot
    pipeline validates the profile elsewhere). A malformed `fips_waivers` IS an error (fail-closed)."""
    path = profile_path(Path(__file__).resolve().parent.parent / "boot", profile_id)
    if not path.is_file():
        return []
    with path.open("rb") as fh:
        profile = json.load(fh)
    return load_waivers(profile.get("fips_waivers", []) or [])


def system_fips_gate(profile_id: str) -> tuple[int, Report]:
    """The boot-time GLOBAL FIPS validation (req-fips-crypto-bom): when the system is in FIPS mode,
    every crypto provider in the assembled environment — core AND every installed plugin — must be
    validated, unless an OPERATOR waiver (with a reason) excuses it. Returns (exit_code, report).

    When FIPS mode is off this is a no-op (exit 0, empty report): a non-FIPS deployment may use
    non-FIPS crypto, and we skip the scan cost on every non-FIPS boot."""
    if not _fips_mode_on():
        return 0, Report()
    report = apply_waivers(core_report(), _profile_waivers(profile_id))
    return (1 if report.failures else 0), report


def format_report(report: Report) -> str:
    """Human/AI-legible one-line-per-finding rendering, worst-first. Waived findings show their reason."""
    order = {None: 0, Boundary.MUST_FIX: 1, Boundary.UNREACHED: 2, Boundary.OUT_OF_BOUNDARY: 3, Boundary.VALIDATED: 4}
    lines = [f"crypto-BOM: {report.scanned_files} ELF artifacts scanned, {len(report.findings)} finding(s)"]
    for f in sorted(report.findings, key=lambda f: order.get(f.boundary, 0)):
        if f.waived:
            lines.append(f"  [WAIVED] {f.provider} @ {f.artifact} — operator waiver: {f.waiver_reason}")
            continue
        label = f.boundary.value if f.boundary else "UNCLASSIFIED"
        lines.append(f"  [{label}] {f.provider} @ {f.artifact} — {f.detail}")
    if report.unreadable:
        lines.append(f"  ({len(report.unreadable)} unreadable file(s) skipped)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI. `--gate --profile <id>` runs the boot-time global FIPS validation (fail-closed with a
    TAP-ABORT on an unwaived leak); with no args it prints the core report (report-only).

    `--profile` defaults to `TAP_BOOT_PROFILE`, and to NOTHING (no waivers) when that is
    unset — never to an invented profile id, whose waivers the operator did not choose.
    """
    parser = argparse.ArgumentParser(description="TAP crypto Bill-of-Materials scanner / FIPS-provider gate.")
    parser.add_argument("--gate", action="store_true", help="enforce the system FIPS-provider gate (fail-closed)")
    parser.add_argument(
        "--profile",
        default=os.environ.get("TAP_BOOT_PROFILE") or "",
        help="boot profile id whose fips_waivers apply; omit to gate with NO waivers",
    )
    args = parser.parse_args(argv)

    if not args.gate:
        print(format_report(core_report()))
        return 0

    # No invented default. The old `or "core_dev"` silently applied a DEV profile's
    # waivers to whatever instance was being gated whenever this ran outside the
    # entrypoint (which passes the resolved profile explicitly) — a waiver borrowed
    # from a profile the operator never chose. Absent profile now means NO waivers:
    # the strictest outcome, and loud about why.
    if not args.profile:
        print(
            "crypto-bom: no boot profile given (--profile / TAP_BOOT_PROFILE unset); "
            "gating with NO operator waivers. A legitimately waived provider will fail "
            "here until you name the profile.",
            file=sys.stderr,
        )

    try:
        code, report = system_fips_gate(args.profile)
    except WaiverError as exc:
        print(f"TAP-ABORT: crypto-bom: malformed fips_waivers in profile '{args.profile}': {exc}", file=sys.stderr)
        return 1
    if code != 0:
        print(format_report(report), file=sys.stderr)
        leaks = ", ".join(f"{f.provider}@{f.artifact}" for f in report.failures)
        print(
            f"TAP-ABORT: crypto-bom: FIPS mode is on but {len(report.failures)} crypto provider(s) are "
            f"non-validated and un-waived: {leaks}. Fix the plugin, or add a justified operator waiver "
            + (
                f"to boot/{args.profile}.boot.json 'fips_waivers'."
                if args.profile
                else "to the boot profile's 'fips_waivers' — and name that profile here via "
                "--profile / TAP_BOOT_PROFILE, since no profile was given, so NO waivers applied."
            ),
            file=sys.stderr,
        )
        return 1
    waived = [f for f in report.findings if f.waived]
    suffix = f" ({len(waived)} operator-waived)" if waived else ""
    print(f"==> crypto-BOM FIPS gate OK: all crypto providers validated or waived{suffix}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
