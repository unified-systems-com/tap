"""Bootstrap pointer parsing + stage-0 fetch (spec-tap-boot-bootstrap).

A bootstrap pointer names an artifact + a boot record inside it:

    <source-ref>#<record>[@<algo>:<hex>]        (req-boot-bootstrap-pointer-grammar)

``<source-ref>`` (before ``#``) is resolved by the source machinery to a versioned artifact;
``#<record>`` selects ``boot/<record>.boot.json`` from inside it; the trailing ``@<algo>:<hex>``
is the reserved fail-closed digest guard. This module owns the **git arm** of stage-0: pull ONLY
the one boot record out of the artifact WITHOUT installing or importing the package
(``req-boot-bootstrap-stage0``), verify it against the repo's shipped ``[[boot.records]]`` sha256
(the cheap integrity edge), and write just that staged record to a caller-chosen path. The normal
``--boot-file`` staging then consumes it as an ordinary local profile; nothing else persists.

**Host-runnable, pure stdlib** (``subprocess``/``json``/``tomllib``/``hashlib``/``tempfile``): it
resolves on the host during ``spawn-session``, before the session container exists, so it must not
import the jsonschema-backed ``tap.jsonfiles``/``tap.plugin_source_auth`` (venv-only). Stage-0 is a
**blobless, no-checkout, depth-1 clone** (``--filter=blob:none``): git protocol v2 fetches the
commit + trees and lazily materializes only the single record blob on ``git show`` — as light as a
raw-content GET but **host-generic** (any git server, reusing ``GIT_ASKPASS`` auth), not coupled to
one host's API.

Credential handling here is deliberately reduced, and the reduction is now exact. The
``GIT_ASKPASS`` mechanism itself is NOT reimplemented: it is the shared stdlib
``tap.git_invocation`` leaf, the same code the install system uses (token in the child env,
never the URL or argv). What stage-0 does on its own is the *envelope read*: a stdlib
``json.loads`` that checks the ``kind`` is ``github_pat`` — cheap, no jsonschema, and
load-bearing, since without it any envelope carrying a ``token`` would have its secret handed
to whatever git host the pointer names (credential confusion). What stage-0 still cannot do is
validate the ``data`` block against the ``github_pat`` source **schema**, which needs
jsonschema (venv-only, unavailable on the host). So a well-formed envelope of the right kind
but wrong data shape is caught later, not here: the clone itself fails loud on a bad token, and
the container's install path re-resolves and fully validates the record's OWN per-entry
credentials when it git-installs the plugins.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tap.boot_naming import RECORD_SUFFIX
from tap.boot_records import BootRecordManifestError, canonical_digest_bytes, declared_record_digests
from tap.git_invocation import DEFAULT_HOST, DEFAULT_USERNAME, GITHUB_PAT_KIND, askpass_env, run_git
from tap.secret_naming import SECRET_SUFFIX
from tap.secrets_root import resolve as resolve_secrets_root

__all__ = [
    "BootPointerError",
    "Pointer",
    "GitRef",
    "parse_pointer",
    "parse_git_ref",
    "stage0_fetch",
    "main",
]

DEFAULT_SECRETS_ROOT = Path.home() / "tap-secrets"

# tap_plugin/<slug>/boot/<name>.boot.json inside an artifact.
_RECORD_IN_ARTIFACT = re.compile(r"^tap_plugin/(?P<slug>[^/]+)/boot/(?P<name>[^/]+)\.boot\.json$")


class BootPointerError(Exception):
    """Raised on a malformed pointer, a fetch failure, or an integrity mismatch."""


@dataclass(frozen=True)
class Pointer:
    """A parsed bootstrap pointer: ``<source-ref>#<record>[@<digest>]``."""

    source_ref: str
    record: str | None  # None => default record (fail-closed if absent)
    digest: str | None  # reserved grammar (pointer-side fail-closed pin)


@dataclass(frozen=True)
class GitRef:
    """A git ``<source-ref>``: ``git+<url>@<rev>``."""

    url: str
    rev: str


def parse_pointer(raw: str) -> Pointer:
    """Parse ``<source-ref>#<record>[@<algo>:<hex>]`` (``req-boot-bootstrap-pointer-grammar``).

    TAP-IMPLEMENTS: req-boot-bootstrap-pointer-grammar@a2e4b8a00478/769596b50231 (derivation) — the one
        parser of the pointer grammar; stage-0 and every later reader route through it
        rather than re-splitting the string."""
    raw = raw.strip()
    if not raw:
        raise BootPointerError("empty pointer")
    source_ref, sep, rest = raw.partition("#")
    record: str | None = None
    digest: str | None = None
    if sep:
        name, at, dig = rest.partition("@")
        record = name or None
        if at:
            digest = dig or None
    return Pointer(source_ref=source_ref, record=record, digest=digest)


def parse_git_ref(source_ref: str) -> GitRef | None:
    """Parse a ``git+<url>@<rev>`` source-ref, or ``None`` if it is not a git ref.

    The rev is split on the LAST ``@`` so an ``https://…`` URL (no ``@``) parses cleanly.
    """
    if not source_ref.startswith("git+"):
        return None
    body = source_ref[len("git+") :]
    url, at, rev = body.rpartition("@")
    if not at or not url or not rev:
        raise BootPointerError(f"git source-ref must be 'git+<url>@<rev>', got: {source_ref!r}")
    return GitRef(url=url, rev=rev)


# ---------------------------------------------------------------------------
# Credential (minimal, stdlib — see module docstring)
# ---------------------------------------------------------------------------


def _resolve_token(credential: str | None, secrets_root: Path | None) -> tuple[str, str, str] | None:
    """Resolve a source credential to ``(token, host, username)``, or ``None`` for public.

    ``credential`` is either a full path to a ``*.secret.json`` file (git-install secrets may
    live anywhere) or a bare name resolved under the secrets root (``TAP_SECRETS_ROOT``, default
    ``~/tap-secrets``). There is no implicit default key — the name/path is explicit.
    """
    import json

    if credential is None:
        return None

    candidate = Path(credential).expanduser()
    if candidate.is_file():
        secret_path = candidate
    else:
        # GnuPG-style host-tool precedence: --secrets-root flag > env (via the
        # canonical settings-free lookup, req-tap-cares-secrets-root-resolution)
        # > the host home default.
        root = secrets_root or resolve_secrets_root() or DEFAULT_SECRETS_ROOT
        matches = sorted(root.rglob(f"{credential}{SECRET_SUFFIX}"))
        if not matches:
            raise BootPointerError(f"credential '{credential}' not found (no {credential}{SECRET_SUFFIX} under {root})")
        secret_path = matches[0]

    try:
        envelope = json.loads(secret_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BootPointerError(f"credential '{credential}' unreadable at {secret_path}: {exc}") from exc
    # Kind check before touching data.token: without it, ANY envelope carrying a
    # `token` field would have its secret handed to whatever git host the pointer
    # names — credential confusion (material for service A sent to service B).
    # Costs no jsonschema, so the host boundary is no excuse for skipping it.
    kind = envelope.get("kind")
    if kind != GITHUB_PAT_KIND:
        raise BootPointerError(
            f"credential '{credential}' ({secret_path}) has kind {kind!r}, expected '{GITHUB_PAT_KIND}'"
        )
    data = envelope.get("data") or {}
    token = data.get("token")
    if not isinstance(token, str) or not token:
        raise BootPointerError(f"credential '{credential}' ({secret_path}) has no data.token")
    return token, str(data.get("host", DEFAULT_HOST)), str(data.get("username", DEFAULT_USERNAME))


@contextmanager
def _git_askpass(token_tuple: tuple[str, str, str] | None) -> Iterator[dict[str, str]]:
    """Yield a git env overlay feeding the token via GIT_ASKPASS, or ``{}`` for public."""
    if token_tuple is None:
        yield {}
        return
    token, _host, username = token_tuple
    with askpass_env(username=username, token=token, prefix="tap-stage0-askpass-") as overlay:
        yield overlay


# ---------------------------------------------------------------------------
# Stage-0 fetch
# ---------------------------------------------------------------------------


def _git(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    """Run git for stage-0, raising BootPointerError on failure."""
    return run_git(args, env, error_cls=BootPointerError)


def stage0_fetch(
    pointer: Pointer,
    out_dir: Path,
    *,
    credential: str | None = None,
    secrets_root: Path | None = None,
) -> Path:
    """Fetch the pointer's boot record into ``out_dir`` and return the staged record path.

    The git arm does a blobless/no-checkout/depth-1 clone into a throwaway tempdir under
    ``out_dir``, pulls only the one record blob, verifies it against the artifact's declared
    ``[[boot.records]]`` sha256, writes ``<out_dir>/<record>.boot.json``, and discards the clone.
    A local ``.boot.json`` path source-ref is returned as-is (the subsumed ``--boot-file``).
    """
    if pointer.digest is not None:
        raise BootPointerError(
            "pointer-side digest guard (@<algo>:<hex>) is reserved grammar "
            "(req-boot-bootstrap-pointer-grammar-6); pin the carrier version instead"
        )

    git_ref = parse_git_ref(pointer.source_ref)
    if git_ref is None:
        local = Path(pointer.source_ref).expanduser()
        if local.is_file() and local.name.endswith(RECORD_SUFFIX):
            return local  # local-path arm: subsumes --boot-file, nothing to fetch
        raise BootPointerError(
            f"unsupported source-ref {pointer.source_ref!r}: expected 'git+<url>@<rev>' or a local "
            f"*.boot.json path (bare-slug / index / wheelhouse arms are reserved)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    token = _resolve_token(credential, secrets_root)
    with _git_askpass(token) as overlay:
        env = {**os.environ, **overlay}
        with tempfile.TemporaryDirectory(prefix="tap-stage0-", dir=str(out_dir)) as tmp:
            clone = Path(tmp) / "repo"
            _git(
                [
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    "--branch",
                    git_ref.rev,
                    "--filter=blob:none",
                    "--no-checkout",
                    git_ref.url,
                    str(clone),
                ],
                env,
            )
            listing = _git(["-C", str(clone), "ls-tree", "-r", "--name-only", "HEAD"], env)
            boot_paths = [line for line in listing.stdout.decode().splitlines() if _RECORD_IN_ARTIFACT.match(line)]
            available = sorted(_RECORD_IN_ARTIFACT.match(p).group("name") for p in boot_paths)  # type: ignore[union-attr]

            target = pointer.record or "default"
            matches = [p for p in boot_paths if _RECORD_IN_ARTIFACT.match(p).group("name") == target]  # type: ignore[union-attr]
            if not matches:
                if pointer.record is None:
                    raise BootPointerError(
                        f"no default record in {git_ref.url}@{git_ref.rev}; select one with #<record>. "
                        f"Available: {available or '(none)'}"
                    )
                raise BootPointerError(
                    f"record '{pointer.record}' not found in {git_ref.url}@{git_ref.rev}. "
                    f"Available: {available or '(none)'}"
                )
            record_path = matches[0]
            slug = _RECORD_IN_ARTIFACT.match(record_path).group("slug")  # type: ignore[union-attr]

            record_bytes = _git(["-C", str(clone), "show", f"HEAD:{record_path}"], env).stdout
            toml_bytes = _git(["-C", str(clone), "show", f"HEAD:tap_plugin/{slug}/tap-plugin.toml"], env).stdout
            _verify_integrity(toml_bytes, target, record_bytes, git_ref)

            out_path = out_dir / f"{target}{RECORD_SUFFIX}"
            out_path.write_bytes(record_bytes)
            return out_path


def _verify_integrity(toml_bytes: bytes, record_name: str, record_bytes: bytes, git_ref: GitRef) -> None:
    """Fail closed unless the fetched record matches the artifact's declared ``[[boot.records]]`` sha256."""
    manifest = tomllib.loads(toml_bytes.decode("utf-8"))
    try:
        declared = declared_record_digests(manifest).get(record_name)
    except BootRecordManifestError as exc:
        raise BootPointerError(
            f"malformed [[boot.records]] in {git_ref.url}@{git_ref.rev} tap-plugin.toml: {exc}"
        ) from exc
    if not declared:
        raise BootPointerError(
            f"record '{record_name}' has no declared sha256 in {git_ref.url}@{git_ref.rev} tap-plugin.toml — "
            f"cannot verify integrity (was it published with `scripts/boot-record-hash --refresh`?)"
        )
    computed = canonical_digest_bytes(record_bytes)
    if computed != declared:
        raise BootPointerError(
            f"integrity check FAILED for record '{record_name}' from {git_ref.url}@{git_ref.rev}: "
            f"declared {declared} != fetched {computed} (the artifact's record content does not match its manifest)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tap.boot_pointer", description="Resolve a bootstrap pointer (stage-0 fetch)."
    )
    parser.add_argument("pointer", help="<source-ref>#<record>  (e.g. git+https://…@v0.1.0#soak)")
    parser.add_argument("--credential", help="source-secret name (under TAP_SECRETS_ROOT/~/tap-secrets) or a full path")
    parser.add_argument("--secrets-root", help="override the secrets root for a bare --credential name")
    parser.add_argument("--out", required=True, help="directory to write the staged record into")
    args = parser.parse_args(argv)

    try:
        staged = stage0_fetch(
            parse_pointer(args.pointer),
            Path(args.out),
            credential=args.credential,
            secrets_root=Path(args.secrets_root) if args.secrets_root else None,
        )
    except BootPointerError as exc:
        print(f"boot-pointer: {exc}", file=sys.stderr)
        return 1

    print(staged)  # stdout carries ONLY the staged record path (for spawn-session to capture)
    return 0


if __name__ == "__main__":
    sys.exit(main())
