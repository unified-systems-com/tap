"""The product image: a boot record's whole environment, baked (req-tap-bake-product-image).

A product image is built ``FROM`` a tap-web image named by digest. At build time it installs
the core environment from ``uv.lock`` and the record's plugins as wheels built from their
pinned commits, with the plugins' dependency closure resolved against the core and
hash-verified. Then it writes an **install manifest** tying every installed distribution to
where its bytes came from. At start, nothing is installed: pre-boot reads the manifest
instead of git metadata (a wheel install carries no PEP 610 VCS record) and checks the
installed bytes against it (`req-tap-bake-product-image-3`).

Nothing here names a product (`req-tap-bake-lifecycle-2`). The inputs are a boot record, its
profile id and the base image's digest reference, and the only output is the manifest.

Two roles, one module, so the writer and the reader cannot drift on what an entry means:

- ``build``: run once, inside ``docker/product-image.Dockerfile``, after ``uv sync``.
- ``load_manifest`` / ``check_record`` / ``plugin_problems``: run by pre-boot at every start
  of a product image.

CLI: ``python -m tap.product_image build --record <path> --profile <id> --base-image <ref>``.

Spec: specs/spec-tap-baked-instance.md (`req-tap-bake-product-image`,
`req-tap-bake-immutable-env`).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import logging
import re
import shutil
import subprocess  # nosec B404 — fixed tool argv only (git, uv), list form, never a shell
import sys
import tempfile
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tap.git_pin import COMMIT_SHA_PATTERN, check_pin

logger = logging.getLogger("tap.product_image")

# The manifest's place in a product image. Baked by the build and owned by root, so the
# serving user cannot change it; its presence is what puts the entrypoint and pre-boot in
# product-image mode. A module constant rather than an environment variable, so a stray
# setting cannot switch a development stack into it.
MANIFEST_PATH = Path("/app/tap-product/install-manifest.json")
MANIFEST_SCHEMA = "tap.install-manifest/1"

# `req-tap-bake-product-image-1`: a base named by digest. A tag is mutable, so a tag-only
# base would make the image's provenance a claim about the registry rather than a fact.
DIGEST_REF_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?@sha256:[0-9a-f]{64}$")

_VENV_DIR = Path("/app/.venv")
_UV_LOCK = Path("/app/uv.lock")
_BOOT_DIR = Path("/app/boot")

# What a record may put into an argv or a path. The record is the product's, so it is treated
# as untrusted input here: a slug names a directory, a URL and a tag reach `git fetch`.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:[0-9]+)?/[A-Za-z0-9._~/-]+$")
_REV_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class ProductImageError(RuntimeError):
    """The build cannot produce a sound image, or an image does not match its manifest."""


def canonical_name(name: str) -> str:
    """PEP 503 normalization, so a manifest key matches however a distribution spells itself."""
    return re.sub(r"[-_.]+", "-", name).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def require_digest_ref(ref: str) -> str:
    if not DIGEST_REF_RE.match(ref):
        raise ProductImageError(
            f"base image {ref!r} is not named by digest; a product image is built FROM tap-web@sha256:<digest>, "
            "never from a tag (req-tap-bake-product-image-1)"
        )
    return ref


# =============================================================================
# Installed distributions: what the manifest records, and how it is checked
# =============================================================================


def _record_file(dist: importlib.metadata.Distribution) -> Path:
    files = dist.files or []
    for f in files:
        if f.name == "RECORD" and f.parent.name.endswith(".dist-info"):
            return Path(str(f.locate()))
    raise ProductImageError(f"distribution {dist.metadata['Name']!r} has no RECORD")


def _record_hash(raw: str) -> str | None:
    """A RECORD row's hash as hex sha256, or None when the row carries none (RECORD itself, .pyc)."""
    if not raw.startswith("sha256="):
        return None
    b64 = raw.removeprefix("sha256=")
    return base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4)).hex()


def distribution_entry(dist: importlib.metadata.Distribution) -> dict[str, Any]:
    """The part of a manifest entry read from the installed distribution itself."""
    return {
        "name": canonical_name(dist.metadata["Name"]),
        "version": dist.version,
        "record_sha256": sha256_file(_record_file(dist)),
    }


def distribution_problems(dist: importlib.metadata.Distribution, entry: dict[str, Any]) -> list[str]:
    """Why an installed distribution does not match its manifest entry; empty when it does.

    The RECORD file's own digest is in the manifest, and RECORD holds a sha256 for every
    file the wheel installed, so checking both covers every installed byte the wheel
    shipped without the manifest listing each file.
    """
    name = entry["name"]
    if dist.version != entry["version"]:
        return [f"{name}: installed version {dist.version}, manifest {entry['version']}"]
    record = _record_file(dist)
    if sha256_file(record) != entry["record_sha256"]:
        return [f"{name}: RECORD differs from the manifest"]
    problems: list[str] = []
    for row in record.read_text().splitlines():
        parts = row.rsplit(",", 2)
        if len(parts) != 3:
            continue
        rel, raw_hash, _size = parts
        expected = _record_hash(raw_hash)
        if expected is None:
            continue
        path = Path(str(dist.locate_file(rel)))
        if not path.is_file():
            problems.append(f"{name}: {rel} is missing")
        elif sha256_file(path) != expected:
            problems.append(f"{name}: {rel} differs from its RECORD hash")
    return problems


def installed_distributions() -> dict[str, importlib.metadata.Distribution]:
    found: dict[str, importlib.metadata.Distribution] = {}
    for dist in importlib.metadata.distributions():
        found.setdefault(canonical_name(dist.metadata["Name"]), dist)
    return found


# =============================================================================
# Reading a manifest (pre-boot, every start of a product image)
# =============================================================================


def load_manifest(path: Path | None = None) -> dict[str, Any] | None:
    """The image's install manifest, or None when this is not a product image."""
    path = path or MANIFEST_PATH
    if not path.is_file():
        return None
    manifest: dict[str, Any] = json.loads(path.read_text())
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ProductImageError(f"{path}: schema {manifest.get('schema')!r}, expected {MANIFEST_SCHEMA!r}")
    return manifest


def check_record(manifest: dict[str, Any], profile_id: str, record_path: Path) -> None:
    """The record being booted is the one the image was built from, byte for byte."""
    baked = manifest["record"]
    if profile_id != baked["profile_id"]:
        raise ProductImageError(
            f"this product image was built for boot record {baked['profile_id']!r}, not {profile_id!r}"
        )
    actual = sha256_file(record_path)
    if actual != baked["sha256"]:
        raise ProductImageError(
            f"boot record {record_path} is not the one this image was built from "
            f"(sha256 {actual[:12]}, built from {baked['sha256'][:12]}); a product image's record is part of the image"
        )


def plugin_problems(entry: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    """Why a record plugin is not satisfied by this product image; empty when it is.

    Satisfied means: the manifest holds a plugin entry for the slug, built from the commit the
    record pins, and the installed distribution's version and bytes match that entry.
    """
    slug = entry["slug"]
    source = entry["source"]
    plugins = {p["slug"]: p for p in manifest["distributions"] if p.get("origin") == "plugin"}
    baked = plugins.get(slug)
    if baked is None:
        return [f"plugin '{slug}' is not in this image's install manifest"]
    if source.get("type") != "git" or baked["commit"] != source.get("commit"):
        return [
            f"plugin '{slug}': the record pins {source.get('commit')!r}, the image was built from {baked['commit']!r}"
        ]
    dist = installed_distributions().get(baked["name"])
    if dist is None:
        return [f"plugin '{slug}': {baked['name']} is in the manifest but not installed"]
    return distribution_problems(dist, baked)


# =============================================================================
# Building (once, inside the product-image Dockerfile)
# =============================================================================


def _tool(name: str) -> str:
    """The absolute path of ``git`` or ``uv``, so no argv starts with a bare name a PATH could shadow."""
    found = shutil.which(name)
    if found is None:
        raise ProductImageError(f"{name} is not installed in the base image")
    return found


def _run(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run ``git`` or ``uv`` with an argv built here from validated values (see ``_record_plugins``)."""
    if args[0] not in ("git", "uv"):
        raise ProductImageError(f"refusing to run {args[0]!r}")
    argv = [_tool(args[0]), *args[1:]]
    logger.info("[b4k1] product image: %s", " ".join(args))
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, shell=False)  # nosec B603  # nosemgrep
    if check and result.returncode != 0:
        raise ProductImageError(f"{' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}")
    return result


def _out(args: list[str], *, cwd: Path | None = None) -> str:
    return _run(args, cwd=cwd).stdout


def _record_plugins(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The record's enabled plugins, refusing what a product image cannot carry honestly."""
    entries = [p for p in (record.get("install") or {}).get("plugins") or [] if p.get("enabled", True)]
    for entry in entries:
        source = entry.get("source") or {}
        slug = entry.get("slug")
        if not isinstance(slug, str) or not _SLUG_RE.match(slug):
            raise ProductImageError(f"plugin slug {slug!r} is not a lowercase identifier")
        if source.get("type") != "git":
            raise ProductImageError(
                f"plugin '{slug}': a product image builds git sources only, not {source.get('type')!r}"
            )
        if not re.fullmatch(COMMIT_SHA_PATTERN, str(source.get("commit") or "")):
            raise ProductImageError(f"plugin '{slug}': a product image needs a pinned 40-hex commit, not a tag only")
        if not _URL_RE.match(str(source.get("url") or "")):
            raise ProductImageError(f"plugin '{slug}': source url is not a plain https URL")
        if not _REV_RE.match(str(source.get("rev") or "")):
            raise ProductImageError(f"plugin '{slug}': rev is not a plain tag name")
        if source.get("credential") or source.get("auth"):
            raise ProductImageError(f"plugin '{slug}': credentialed sources are not built into product images yet")
    return entries


def _checkout(url: str, rev: str, commit: str, dest: Path) -> None:
    """Fetch exactly ``commit`` and its tag, and prove the tree checked out is that commit.

    The tag rides along because plugins version themselves from git (setuptools-scm, hatch-vcs):
    without it a shallow checkout builds ``0.0.1.dev1+g<sha>`` and every inter-plugin version
    pin fails to resolve. A tag that has moved off the commit is not followed; the wheel then
    gets a development version and the resolve fails loudly, which is the right outcome.
    """
    dest.mkdir(parents=True)
    _run(["git", "init", "--quiet"], cwd=dest)
    _run(["git", "fetch", "--quiet", "--depth", "1", "--", url, commit], cwd=dest)
    if rev != commit:
        tagged = _run(
            ["git", "fetch", "--quiet", "--depth", "1", "--", url, f"refs/tags/{rev}:refs/tags/{rev}"],
            cwd=dest,
            check=False,
        )
        if tagged.returncode != 0:
            logger.warning("[b4k4] product image: %s has no tag %s (%s)", url, rev, tagged.stderr.strip())
    _run(["git", "checkout", "--quiet", "FETCH_HEAD"], cwd=dest)
    head = _out(["git", "rev-parse", "HEAD"], cwd=dest).strip()
    if head != commit:
        raise ProductImageError(f"{url}: fetched {head}, pinned {commit}")


def _build_wheel(src: Path, out: Path) -> Path:
    out.mkdir(parents=True)
    _run(["uv", "build", "--wheel", "--quiet", "--out-dir", str(out), str(src)])
    wheels = list(out.glob("*.whl"))
    if len(wheels) != 1:
        raise ProductImageError(f"{src}: expected one wheel, built {[w.name for w in wheels]}")
    return wheels[0]


def _lock_digests(lock: Path) -> dict[str, dict[str, Any]]:
    """uv.lock's packages: version, the artifact digests the sync verified against, and source kind."""
    data = tomllib.loads(lock.read_text())
    out: dict[str, dict[str, Any]] = {}
    for pkg in data.get("package", []):
        source = pkg.get("source") or {}
        kind = "workspace" if ("editable" in source or "virtual" in source) else "lock"
        hashes = [w["hash"] for w in pkg.get("wheels", []) if "hash" in w]
        if "sdist" in pkg and "hash" in pkg["sdist"]:
            hashes.append(pkg["sdist"]["hash"])
        out[canonical_name(pkg["name"])] = {"version": pkg.get("version"), "kind": kind, "digests": sorted(hashes)}
    return out


_REQ_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?(?:==([^\s;\\]+)| @ )")
_HASH_RE = re.compile(r"--hash=(sha256:[0-9a-f]{64})")


def _parse_compiled(text: str) -> dict[str, list[str]]:
    """A ``uv pip compile --generate-hashes`` output as name → the digests it allows."""
    out: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _REQ_LINE_RE.match(stripped)
        if m and not line.startswith((" ", "\t")):
            current = canonical_name(m.group(1))
            out.setdefault(current, [])
        if current is not None:
            out[current].extend(_HASH_RE.findall(stripped))
    return {k: sorted(set(v)) for k, v in out.items()}


def _closure_without(text: str, names: set[str]) -> str:
    """A compiled requirements text with the named distributions' entries (and hash lines) removed."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        m = _REQ_LINE_RE.match(line)
        if m and not line.startswith((" ", "\t")):
            skipping = canonical_name(m.group(1)) in names
        if not skipping:
            kept.append(line)
    return "".join(kept)


def _core_constraints(dists: Iterable[importlib.metadata.Distribution]) -> str:
    """Every installed core distribution pinned at its version, so plugins cannot move the core."""
    return "".join(f"{canonical_name(d.metadata['Name'])}=={d.version}\n" for d in dists)


def build(profile_id: str, base_image: str) -> dict[str, Any]:
    """Install the record's plugins into the image's venv and write the install manifest.

    Runs after ``uv sync --frozen --all-packages`` has built the core environment from the
    image's own lock. Each plugin is fetched at its pinned commit, built into a wheel, and
    installed with its dependency closure resolved against the core (constrained to the
    versions already installed) and hash-verified. The build fails if any installed
    distribution is not accounted for (`req-tap-bake-product-image-2`).

    TAP-IMPLEMENTS: req-tap-bake-product-image@f9de390e4de9/0be40de65fec (derivation) — the one
        place a product image's environment and its install manifest are produced.
    """
    require_digest_ref(base_image)
    if not _SLUG_RE.match(profile_id):
        raise ProductImageError(f"profile id {profile_id!r} is not a lowercase identifier")
    # The record is read from the one place the Dockerfile puts it, and the manifest is written
    # to the one place pre-boot reads it: neither path is an input.
    boot_dir = _BOOT_DIR.resolve()
    record_path = (boot_dir / f"{profile_id}.boot.json").resolve()
    if not record_path.is_relative_to(boot_dir) or not record_path.is_file():
        raise ProductImageError(f"no boot record for profile {profile_id!r} in {boot_dir}")
    # NOSONAR (S8707) — checked immediately above: resolved, inside /app/boot, a real file.
    record_bytes = record_path.read_bytes()  # NOSONAR (S8707)
    record = json.loads(record_bytes)
    plugins = _record_plugins(record)
    core = installed_distributions()
    lock = _lock_digests(_UV_LOCK)

    with tempfile.TemporaryDirectory(prefix="tap-product-") as tmp:
        work = Path(tmp)
        built: dict[str, dict[str, Any]] = {}
        requirements: list[str] = []
        wheels: list[Path] = []
        for entry in plugins:
            slug, source = entry["slug"], entry["source"]
            src = work / "src" / slug
            _checkout(source["url"], source["rev"], source["commit"], src)
            wheel = _build_wheel(src, work / "wheels" / slug)
            dist_name = canonical_name(wheel.name.split("-", 1)[0])
            tag = check_pin(source["url"], source["rev"], source["commit"])
            built[dist_name] = {
                "slug": slug,
                "url": source["url"],
                "rev": source["rev"],
                "commit": source["commit"],
                "tag_check": tag.state,
                "wheel": wheel.name,
                "wheel_sha256": sha256_file(wheel),
            }
            requirements.append(f"{dist_name} @ {wheel.as_uri()}\n")
            wheels.append(wheel)

        (work / "plugins.in").write_text("".join(requirements))
        (work / "core.txt").write_text(
            _core_constraints(d for n, d in core.items() if lock.get(n, {}).get("kind") != "workspace")
        )
        compiled = _out(
            [
                "uv", "pip", "compile", "--quiet", "--generate-hashes", "--no-header",
                "--python", str(_VENV_DIR), "--constraint", str(work / "core.txt"), str(work / "plugins.in"),
            ]
        )  # fmt: skip
        closure = _parse_compiled(compiled)
        # Two installs, because uv's hash mode refuses a closure that carries local wheels. The
        # dependencies go first, hash-verified against the compiled closure and with --no-deps:
        # the closure IS the dependency set, so nothing may be resolved past it. The plugin
        # wheels follow, also --no-deps; they were built above and their digests recorded. Both run
        # outside /app, so the project's own uv settings (its constraint-dependencies, which the
        # compile above already honoured) are not re-applied as unpinned requirements.
        dep_lines = _closure_without(compiled, set(built))
        (work / "closure.txt").write_text(dep_lines)
        _run(
            [
                "uv", "pip", "install", "--python", str(_VENV_DIR), "--require-hashes", "--no-deps",
                "-r", str(work / "closure.txt"),
            ],
            cwd=work,
        )  # fmt: skip
        _run(["uv", "pip", "install", "--python", str(_VENV_DIR), "--no-deps", *(str(w) for w in wheels)], cwd=work)
        _run(["uv", "pip", "check", "--python", str(_VENV_DIR)])

    distributions: list[dict[str, Any]] = []
    unaccounted: list[str] = []
    for name, dist in sorted(installed_distributions().items()):
        entry = distribution_entry(dist)
        if name in built:
            entry |= {"origin": "plugin", **built[name]}
        elif name in core and lock.get(name, {}).get("kind") == "workspace":
            entry |= {"origin": "workspace"}
        elif name in core and name in lock and lock[name]["version"] == dist.version:
            entry |= {"origin": "core", "digests": lock[name]["digests"]}
        elif name in closure and closure[name]:
            entry |= {"origin": "plugin-dependency", "digests": closure[name]}
        else:
            unaccounted.append(f"{name}=={dist.version}")
            continue
        distributions.append(entry)
    if unaccounted:
        raise ProductImageError(
            f"installed but not accounted for by uv.lock or the plugin closure: {', '.join(unaccounted)}"
        )
    missing = sorted(set(built) - {d["name"] for d in distributions})
    if missing:
        raise ProductImageError(f"plugins built but not installed: {', '.join(missing)}")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "base_image": base_image,
        "record": {"profile_id": profile_id, "sha256": hashlib.sha256(record_bytes).hexdigest()},
        "distributions": distributions,
    }
    target = MANIFEST_PATH
    # NOSONAR (S8707) — a module constant; no argument names this path.
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")  # NOSONAR (S8707)
    logger.info(
        "[b4k2] product image: manifest written to %s (%d distributions, %d plugins)",
        target,
        len(distributions),
        len(built),
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="tap.product_image", description="Bake a boot record's environment.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="install the record's plugins and write the install manifest")
    b.add_argument("--profile", required=True)
    b.add_argument("--base-image", required=True, help="the tap-web image, by digest")
    args = parser.parse_args(argv)
    try:
        build(args.profile, args.base_image)
    except ProductImageError as exc:
        logger.error("[b4k3] product image build failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
