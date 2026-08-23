"""Out-of-band component detection (req-cicd-sbom-12): declaration is DETECTED, never remembered.

Two halves, staged per the requirement:

 * Dockerfile reconciliation (fail-closed, live via tap/tests/test_sbom_oob.py):
   every ``COPY --from=`` line introduces bytes that did not come from the build
   context — the exact class the supplemental manifests (req-cicd-sbom-3) declare.
   Each such line MUST either resolve to declared component path(s) in the image's
   supplemental manifest, or carry an explicit ``# sbom-allow(<rid>): <reason>``
   annotation on the immediately preceding comment line (Dockerfiles have no
   trailing comments). An unannotated, undeclared site is a defect: it is how the
   NEXT fips.so would silently vanish from the SBOM.

 * Unknowns budget (DRY RUN today, report-only): scan an image ref with the pinned
   Syft and report executable files no cataloged package claims and no declaration
   covers. The fail-closed budget in the publish pipeline flips only after the dry
   run's numbers are reviewed (the requirement's staging).

Shares generate.py's pinned Syft + supplemental loader by path-import (one
derivation, not a copy — the plugin_release.py pattern).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

_HERE = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location("sbom_generate", _HERE / "generate.py")
assert _spec is not None and _spec.loader is not None
_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gen)

SYFT_IMAGE = _gen.SYFT_IMAGE
_REPO_ROOT = _HERE.parent.parent

# Annotation grammar: a DEFINED requirement id + a mandatory non-empty reason.
_ALLOW_RE = re.compile(r"#\s*sbom-allow\((?P<rid>req-[a-z0-9-]+)\)\s*:\s*\S")
# Dockerfile instructions are case-insensitive and flags may precede --from
# (--chown=... --from=...); parse accordingly, and fail CLOSED on any COPY
# that mentions --from but resists parsing (Codex finding on PR #115: a
# guard that recognizes only one spelling is a guard in name only).
_COPY_RE = re.compile(r"^\s*copy\s+(?P<rest>.+)$", re.IGNORECASE)
_FROM_FLAG_RE = re.compile(r"--from=(?P<src_stage>\S+)")


def _defined_rids(repo_root: Path) -> set[str]:
    """Every requirement id DEFINED in the spec tree: RID: lines + table-row ids."""
    rids: set[str] = set()
    for spec in repo_root.glob("**/specs/spec-*.md"):
        for line in spec.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("RID:") or stripped.startswith("| req-"):
                rids.update(re.findall(r"req-[a-z0-9-]+", stripped))
    return rids


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """(first_lineno, line) with backslash continuations joined — a COPY split
    across lines must parse as the single instruction Docker sees."""
    out: list[tuple[int, str]] = []
    pending: str | None = None
    pending_no = 0
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.rstrip()
        if pending is not None:
            if stripped.endswith("\\"):
                pending = pending + " " + stripped[:-1].strip()
            else:
                out.append((pending_no, pending + " " + raw.strip()))
                pending = None
            continue
        if stripped.endswith("\\") and not raw.lstrip().startswith("#"):
            pending = stripped[:-1].strip()
            pending_no = lineno
            continue
        out.append((lineno, raw))
    if pending is not None:
        out.append((pending_no, pending))
    return out


class CopySite(NamedTuple):
    """One ``COPY --from=`` instruction and how it accounts for itself."""

    dockerfile: str
    lineno: int
    src_stage: str
    sources: list[str]
    dest: str
    allow_rid: str | None


def parse_copy_sites(dockerfile: Path) -> list[CopySite]:
    """Every COPY --from site, with any sbom-allow annotation from the preceding comment.

    Raises ValueError (fail-closed) on a COPY that mentions --from but cannot
    be parsed into sources + destination — an unrecognized spelling must never
    pass silently.
    """
    sites: list[CopySite] = []
    pending_allow: str | None = None
    for lineno, raw in _logical_lines(dockerfile.read_text(encoding="utf-8")):
        line = raw.strip()
        if line.startswith("#"):
            m = _ALLOW_RE.search(line)
            if m:
                pending_allow = m.group("rid")
            continue
        if not line:
            continue
        copy_m = _COPY_RE.match(line)
        if copy_m and "--from" in line:
            from_m = _FROM_FLAG_RE.search(line)
            if not from_m:
                raise ValueError(f"{dockerfile}:{lineno} COPY mentions --from in an unsupported form: {line!r}")
            rest = copy_m.group("rest")
            if "[" in rest:
                # JSON (exec) form: COPY --from=x ["src", "dest"]
                parsed = json.loads(rest[rest.index("[") :])
                args = [str(a) for a in parsed]
            else:
                args = [t for t in rest.split() if not t.startswith("--")]
            if len(args) < 2:
                raise ValueError(f"{dockerfile}:{lineno} COPY --from with unparseable args: {line!r}")
            sites.append(
                CopySite(
                    dockerfile=str(dockerfile),
                    lineno=lineno,
                    src_stage=from_m.group("src_stage"),
                    sources=args[:-1],
                    dest=args[-1],
                    allow_rid=pending_allow,
                )
            )
        # Any non-comment line consumes the pending annotation: it binds to the
        # NEXT instruction only, never floats down the file.
        pending_allow = None
    return sites


def _declared_paths(supplemental: dict[str, object]) -> set[str]:
    components = supplemental["components"]
    assert isinstance(components, list)
    return {c["path"] for c in components}


def check_dockerfile_sites(
    dockerfile: Path, supplemental: dict[str, object], repo_root: Path | None = None
) -> list[str]:
    """The reconciliation gate: every COPY --from site declared or explicitly allowed."""
    declared = _declared_paths(supplemental)
    known_rids = _defined_rids(repo_root if repo_root is not None else _REPO_ROOT)
    problems: list[str] = []
    try:
        sites = parse_copy_sites(dockerfile)
    except ValueError as exc:
        return [str(exc)]
    for site in sites:
        if site.allow_rid is not None:
            if site.allow_rid not in known_rids:
                problems.append(
                    f"{site.dockerfile}:{site.lineno} sbom-allow names '{site.allow_rid}', which is not a "
                    f"defined requirement — an exemption must cite the real rule that justifies it"
                )
            continue
        if site.dest.endswith("/"):
            computed = [site.dest + Path(s).name for s in site.sources]
        else:
            computed = [site.dest]
        undeclared = [p for p in computed if p not in declared]
        if undeclared:
            problems.append(
                f"{site.dockerfile}:{site.lineno} COPY --from={site.src_stage} lands undeclared path(s) "
                f"{undeclared} — declare in the supplemental manifest (req-cicd-sbom-3) or annotate the "
                f"preceding line with '# sbom-allow(<rid>): <reason>'"
            )
    return problems


def unknown_executables(image_ref: str, supplemental: Path | None = None) -> dict[str, object]:
    """DRY RUN (report-only): executables in the image no cataloged package claims.

    One pinned-Syft scan with file metadata ON (this mode needs the file
    inventory that the SBOM scans deliberately turn off), diffed against every
    cataloged artifact's location paths and the scan-surface exclusions.
    """
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "syft.json"
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{td}:/out",
            SYFT_IMAGE,
            "scan",
            f"docker:{image_ref}",
            "-o",
            "syft-json=/out/syft.json",
        ]
        print(f"+ {' '.join(cmd)}", file=sys.stderr)
        subprocess.run(cmd, check=True)
        doc = json.loads(out.read_text(encoding="utf-8"))

    owned: set[str] = set()
    for artifact in doc.get("artifacts", []):
        for loc in artifact.get("locations", []):
            owned.add(loc.get("path", ""))
        # apk ownership lives in the package's FILE INVENTORY (metadata.files),
        # not in locations (those point at the apk DB entry) — without this,
        # every libc/busybox member reads as unknown (proven in the first dry
        # run: 565/296 raw vs the real residue).
        meta = artifact.get("metadata") or {}
        for f in meta.get("files", []) or []:
            path = f.get("path") if isinstance(f, dict) else None
            if path:
                stripped = path.lstrip("/")
                owned.add(stripped)
                # Wolfi layout aliasing: the apk DB records usr/lib64/... while
                # the filesystem canonicalizes to /usr/lib/... (lib64 is a
                # symlink) — even `apk info --who-owns` cannot connect the two.
                # Own both spellings, else libffi.so reads as unknown forever.
                if stripped.startswith("usr/lib64/"):
                    owned.add("usr/lib/" + stripped[len("usr/lib64/") :])
    excluded_prefixes = tuple(p.rstrip("*/") for p in _gen.SYFT_EXCLUDES)

    declared: set[str] = set()
    if supplemental is not None:
        # Report tool: paths only, no schema validation (that is the publish
        # gate's job) — keeps this runnable on a bare host python.
        declared = {c["path"] for c in json.loads(supplemental.read_text(encoding="utf-8"))["components"]}

    unknowns: list[dict[str, str]] = []
    for f in doc.get("files", []):
        meta = f.get("metadata") or {}
        path = (f.get("location") or {}).get("path", "")
        mode = meta.get("mode", 0)
        is_exec = isinstance(mode, int) and bool(mode & 0o111) and meta.get("type") == "RegularFile"
        if (
            not is_exec
            or path in owned
            or path.lstrip("/") in owned
            or path in declared
            or path.startswith(excluded_prefixes)
        ):
            continue
        unknowns.append({"path": path, "mime": meta.get("mimeType", "?")})
    return {"image": image_ref, "unknown_executables": unknowns, "count": len(unknowns)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dockerfile",
        nargs=2,
        metavar=("DOCKERFILE", "SUPPLEMENTAL"),
        action="append",
        help="reconcile one Dockerfile against its supplemental manifest (repeatable; fail-closed)",
    )
    mode.add_argument("--unknowns", metavar="IMAGE_REF", help="report-only unknown-executables scan of an image")
    ap.add_argument(
        "--fail",
        action="store_true",
        help="with --unknowns: exit non-zero when any unknown executable remains (the req-cicd-sbom-12 budget, fail-closed)",
    )
    ap.add_argument(
        "--supplemental",
        type=Path,
        default=None,
        help="with --unknowns: subtract this manifest's declared paths from the report",
    )
    args = ap.parse_args(argv)

    if args.unknowns:
        report = unknown_executables(args.unknowns, supplemental=args.supplemental)
        print(json.dumps(report, indent=2))
        mode_label = "BUDGET" if args.fail else "REPORT"
        count = int(str(report["count"]))
        print(f"oob-unknowns: {count} unknown executable(s) in {args.unknowns} ({mode_label})", file=sys.stderr)
        if count > 0 and not args.fail:
            # Findings in report mode annotate the run; ONLY findings are
            # report-only — an operational failure (docker/syft/pull error)
            # propagates as a raised exception and fails the job (Codex
            # finding on PR #115: a check that cannot run must not pass).
            print(f"::warning::req-cicd-sbom-12: {count} unknown executable(s) in {args.unknowns}")
        if args.fail and count > 0:
            return 1
        return 0

    problems: list[str] = []
    for df, supp in args.dockerfile:
        problems += check_dockerfile_sites(Path(df), _gen.load_supplemental(Path(supp)))
    if problems:
        _gen.fail(problems, "oob")
    print("oob-dockerfiles: OK (every COPY --from site declared or explicitly allowed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
