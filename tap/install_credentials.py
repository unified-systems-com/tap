"""Enumerate-first preflight for the boot record's install-source credentials.

TAP-IMPLEMENTS: req-tap-plugin-arch-source-secret@d6c1cb0e9a14/2394c157c833 (enforcement) — the one
derivation of "which install credentials does this record declare, and can this host satisfy them",
enforced offline before any install or clone runs (`req-tap-plugin-arch-source-secret-7`/`-8`/`-9`).
`tap/plugin_source_auth.py` stays the derivation of the resolution itself; this front-runs its
failure mode for the whole declared set at once.

A boot record's ``install`` entries may each name a source ``credential``
(`req-tap-plugin-arch-source-secret-6`); naming it IS the declaration that it is required
(`-5`). Until this module existed that requirement was discovered the hard way — *inside*
the install loop, one entry at a time, after the network work of the entries before it had
already run. The population half of boot has had the better shape since 2026-08-09
(`req-boot-required-secrets-5`: enumerate the declared set, check presence + kind offline,
report every failure in one verdict, abort before anything mutates). This is that shape,
applied to the install half — which runs *first*, and therefore fails *earlier and more
expensively* when it fails at all.

**Two consumers, two lookup rules — checked together, on purpose.** The same declared
credential is resolved by two different resolvers with different floors:

* **Host-side** (``tap.boot_pointer._resolve_token``, used by stage-0 and by
  ``tap.dev_workspace``): finds the envelope by **filename** — ``<key>.secret.json``
  anywhere under the secrets root — because it runs under bare ``python3`` before any
  venv exists and cannot reach the registry.
* **Container-side** (``tap.plugin_source_auth.resolve_git_credential`` →
  ``tap.runtime_secrets``): finds it by **identity** — the envelope whose ``scope`` is
  ``tap_plugins.source`` and whose ``key`` is the declared key.

An envelope can satisfy one and not the other (right filename, wrong declared ``scope``;
or right identity under an unexpected filename). Checking only one rule would let a spawn
sail through its host-side preflight and then abort in-container two minutes later — the
precise failure this module exists to prevent. So the check verifies **both** rules and
names which one an envelope breaks. This is a genuine two-resolver seam, not a duplicated
fact: the seam is documented at ``req-tap-plugin-arch-source-secret-7``.

**Stdlib only, and it must stay that way** — ``scripts/spawn-session.sh`` runs this as
``python3 -m tap.install_credentials`` on the bare host, before the container (and any
venv) exists, exactly as it runs ``tap.boot_pointer`` and ``tap.dev_workspace``. The floor
is machine-checked by ``test_stage0_credential_machinery_is_stdlib_only``. Consequently the
host check does *not* run the jsonschema ``data`` validation the container adds; it checks
the two facts a missing/mis-shaped envelope actually trips on (``kind`` and a non-empty
``data.token``) and says so.

Never reads or reports a credential VALUE — only refs, kinds, paths, and problems
(`req-boot-required-secrets-5`'s rule, same reason).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from tap.boot_naming import RECORD_SUFFIX, profile_path, step_enabled
from tap.git_invocation import GITHUB_PAT_KIND, SOURCE_SECRET_SCOPE
from tap.secret_naming import SECRET_EXAMPLE_SUFFIX, SECRET_SUFFIX
from tap.secrets_root import for_host_tool as host_tool_secrets_root
from tap.secrets_root import resolve as resolve_secrets_root

#: Exit status for "the record declares credentials this host cannot satisfy". Distinct
#: from 1 (usage/IO error) so a caller can tell a provisioning gap from a broken argv.
EXIT_UNSATISFIED: Final[int] = 3


class InstallCredentialError(Exception):
    """Raised when a record's declared install credentials cannot be satisfied."""


@dataclass(frozen=True)
class DeclaredCredential:
    """One credential key a record declares, with every install entry that needs it."""

    key: str
    #: Slugs whose source names this key — a credential is commonly shared by several.
    slugs: tuple[str, ...]
    #: The repo URLs those entries pull, so the "is it actually private?" hint can name them.
    urls: tuple[str, ...]


@dataclass(frozen=True)
class CredentialProblem:
    """A declared credential this host cannot satisfy, and why."""

    declared: DeclaredCredential
    #: Short machine-readable class: missing | unreadable | kind | token | identity | filename | split.
    problem: str
    #: Human sentence naming exactly what is wrong, including the path when there is one.
    detail: str
    #: Envelope paths considered, for the operator to inspect (never their contents).
    considered: tuple[Path, ...] = field(default=())


def entries_of(record: dict[str, Any]) -> list[dict[str, Any]]:
    """The record's ``install.plugins`` list — the one reach into that shape from here."""
    return list(record.get("install", {}).get("plugins", []))


def declared_credentials(entries: Iterable[dict[str, Any]]) -> list[DeclaredCredential]:
    """Return every install credential the **enabled** entries declare.

    Enabled-scoped for the same reason the population preflight is
    (`req-boot-required-secrets-5`): a disabled entry is never installed, so its
    credential is not required and must not block a boot. Order follows the record so
    the report reads in install order; entries sharing a key collapse into one row.
    """
    order: list[str] = []
    slugs: dict[str, list[str]] = {}
    urls: dict[str, list[str]] = {}
    for entry in entries:
        if not step_enabled(entry):
            continue
        source = entry.get("source", {})
        if not isinstance(source, dict) or source.get("type") != "git":
            continue
        declared = source.get("credential")
        if declared is None:
            continue  # public git source — no auth (req-tap-plugin-arch-source-secret-5)
        key = str(declared)
        if key not in order:
            order.append(key)
        slugs.setdefault(key, []).append(str(entry.get("slug", "?")))
        url = source.get("url")
        if url and str(url) not in urls.setdefault(key, []):
            urls[key].append(str(url))
    return [DeclaredCredential(key=k, slugs=tuple(slugs[k]), urls=tuple(urls.get(k, ()))) for k in order]


def redact_url_userinfo(url: str) -> str:
    """Strip any ``user:password@`` from a URL before it is shown to anyone.

    A record's `url` is authored elsewhere — it can arrive from a plugin repo through a
    pointer fetch — so it is not ours to trust. TAP never PUTS a token in a URL
    (`req-tap-plugin-arch-source-secret-4`: it rides GIT_ASKPASS precisely so it cannot
    leak into `direct_url.json`), but that governs what TAP generates, not what a
    hand-authored record may contain. This message exists to be read by an operator and
    pasted into a chat or a ticket, so it must not be the thing that publishes a
    credential someone else embedded. Cheap edge, taken while the surface is open.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable url>"
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def _candidate_envelopes(root: Path) -> list[Path]:
    """Every real ``*.secret.json`` under *root* (never a committed ``*.secret.example.json``)."""
    return sorted(p for p in root.rglob(f"*{SECRET_SUFFIX}") if not p.name.endswith(SECRET_EXAMPLE_SUFFIX))


def _check_one(declared: DeclaredCredential, root: Path) -> CredentialProblem | None:
    """Check one declared credential against both resolvers' rules. ``None`` when satisfiable."""
    by_filename: list[Path] = []
    by_identity: list[Path] = []
    unreadable: list[tuple[Path, str]] = []

    for path in _candidate_envelopes(root):
        filename_match = path.name == f"{declared.key}{SECRET_SUFFIX}"
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Only a filename match makes an unreadable file this credential's problem;
            # an unrelated corrupt envelope is someone else's preflight to fail.
            if filename_match:
                unreadable.append((path, str(exc)))
            continue
        if not isinstance(envelope, dict):
            if filename_match:
                unreadable.append((path, "envelope is not a JSON object"))
            continue
        if filename_match:
            by_filename.append(path)
        if envelope.get("scope") == SOURCE_SECRET_SCOPE and envelope.get("key") == declared.key:
            by_identity.append(path)

    if unreadable and not by_identity:
        path, why = unreadable[0]
        return CredentialProblem(declared, "unreadable", f"{path} could not be parsed: {why}", (path,))

    if not by_filename and not by_identity:
        return CredentialProblem(
            declared,
            "missing",
            f"no {declared.key}{SECRET_SUFFIX} under {root}, and no envelope there declaring "
            f"scope '{SOURCE_SECRET_SCOPE}' key '{declared.key}'",
        )

    # Present on at least one rule. Agreement is not "each rule found something" and not
    # even "some file satisfies both" — it is that each resolver's ACTUAL PICK is the same
    # file. The host takes the first filename match in sorted order
    # (`boot_pointer._resolve_token`: `sorted(root.rglob(...))[0]`), so a decoy sorting
    # earlier wins there even when a correct envelope exists further down, while the
    # container resolves by scope+key and picks the correct one. Modelling the picks is the
    # only way this check predicts what the two consumers will really do.
    host_pick = by_filename[0] if by_filename else None
    container_pick = by_identity[0] if by_identity else None
    if host_pick is None or container_pick is None or host_pick != container_pick:
        if container_pick is None and host_pick is not None:
            path = host_pick
            envelope = json.loads(path.read_text(encoding="utf-8"))
            return CredentialProblem(
                declared,
                "identity",
                f"{path} is named for '{declared.key}' (the host-side resolver would find it) but "
                f"declares scope '{envelope.get('scope')}' key '{envelope.get('key')}' — the in-container "
                f"install resolves scope '{SOURCE_SECRET_SCOPE}' key '{declared.key}', so pre-boot would "
                f"fail after the host-side step succeeded",
                (path,),
            )
        if host_pick is None and container_pick is not None:
            path = container_pick
            return CredentialProblem(
                declared,
                "filename",
                f"{path} declares scope '{SOURCE_SECRET_SCOPE}' key '{declared.key}' (the in-container "
                f"install would find it) but is not named {declared.key}{SECRET_SUFFIX} — the host-side "
                f"resolver matches on filename, so spawn's own staging steps would fail",
                (path,),
            )
        # Both rules are satisfied — by DIFFERENT files. The two resolvers would hand git
        # two different envelopes, which is worse than either failing: it is credential
        # confusion that neither consumer reports.
        if host_pick is None or container_pick is None:  # pragma: no cover - both-None is `missing`
            return CredentialProblem(declared, "missing", "no envelope satisfies either resolver")
        return CredentialProblem(
            declared,
            "split",
            f"the two resolvers would pick DIFFERENT envelopes: the host takes {host_pick} "
            f"(first filename match in sorted order) while the in-container install takes "
            f"{container_pick} (scope '{SOURCE_SECRET_SCOPE}' key '{declared.key}'). "
            f"One file must satisfy both rules",
            (host_pick, container_pick),
        )

    # Both resolvers pick the SAME file: check the two facts a resolver rejects it on.
    path = host_pick
    envelope = json.loads(path.read_text(encoding="utf-8"))
    kind = envelope.get("kind")
    if kind != GITHUB_PAT_KIND:
        return CredentialProblem(
            declared,
            "kind",
            f"{path} has kind {kind!r}, expected '{GITHUB_PAT_KIND}'",
            (path,),
        )
    token = (envelope.get("data") or {}).get("token")
    if not isinstance(token, str) or not token:
        return CredentialProblem(declared, "token", f"{path} has no non-empty data.token", (path,))
    return None


def check(entries: Iterable[dict[str, Any]], secrets_root: Path | None) -> list[CredentialProblem]:
    """Return every declared install credential this host cannot satisfy (empty ⇒ clean).

    Enumerate-all by contract: the caller learns about *all* unsatisfiable credentials in
    one verdict rather than one per attempt (`req-tap-plugin-arch-source-secret-7`). Takes
    install ENTRIES, not a record, so pre-boot — which already holds the enabled entry list —
    checks the same objects it is about to install rather than re-reading the record.
    """
    declared = declared_credentials(entries)
    if not declared:
        return []
    root = secrets_root or resolve_secrets_root()
    if root is None or not root.is_dir():
        where = f"{root} does not exist" if root else "TAP_SECRETS_ROOT is unset and no default store exists"
        return [CredentialProblem(d, "missing", f"no secrets store to resolve it from ({where})") for d in declared]
    return [p for p in (_check_one(d, root) for d in declared) if p is not None]


def unsatisfied_message(problems: list[CredentialProblem], *, profile_id: str, secrets_root: Path | None) -> str:
    """The one message for an unsatisfiable install credential — host and container alike.

    Carries what the bare resolver error never did: which plugins needed it, the envelope
    identity to provision, and the *other* road — that a public repo needs no credential at
    all, which is the likelier fault when a record was written against repos that have since
    been opened up or moved. Never contains a credential value.
    """
    root = secrets_root or resolve_secrets_root()
    lines = [
        f"boot profile '{profile_id}' declares {len(problems)} install credential(s) this host "
        f"cannot satisfy (checked offline, before any install):",
        "",
    ]
    for prob in problems:
        needed_by = ", ".join(prob.declared.slugs)
        lines.append(f"  {prob.declared.key} (kind {GITHUB_PAT_KIND}) — required by: {needed_by}")
        lines.append(f"      {prob.problem.upper()}: {prob.detail}")
        for url in prob.declared.urls:
            lines.append(f"      pulls: {redact_url_userinfo(url)}")
        lines.append("")
    lines += [
        "A git source's `credential` key IS the declaration that the credential is required",
        "(req-tap-plugin-arch-source-secret-5), so there are exactly two ways forward:",
        "",
        "  1. PROVISION it — run /provision-secrets, or place an envelope under",
        f"     {root or '$TAP_SECRETS_ROOT'} named <key>{SECRET_SUFFIX} declaring",
        f'     "scope": "{SOURCE_SECRET_SCOPE}", "key": "<key>", "kind": "{GITHUB_PAT_KIND}",',
        '     and a non-empty "data": {"token": ...}.',
        "",
        "  2. DROP the `credential` key — if the repo is public it needs no auth at all. Check",
        "     before provisioning; a record written when a repo was private (or lived in another",
        "     org) outlives that fact. Prove it with the host credential helper disabled:",
        "       GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 git ls-remote <url> <rev>",
        "     If that resolves, the record is over-declaring and the fix belongs in the record.",
    ]
    return "\n".join(lines)


def check_or_raise(entries: Iterable[dict[str, Any]], secrets_root: Path | None, *, profile_id: str) -> None:
    """Raise :class:`InstallCredentialError` with the full verdict if anything is unsatisfiable."""
    problems = check(entries, secrets_root)
    if problems:
        raise InstallCredentialError(unsatisfied_message(problems, profile_id=profile_id, secrets_root=secrets_root))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tap.install_credentials",
        description="Offline preflight: can this host satisfy a boot record's install credentials?",
    )
    parser.add_argument("--record", type=Path, help=f"path to a <id>{RECORD_SUFFIX} record")
    parser.add_argument("--profile", help="profile id, resolved against --boot-dir")
    parser.add_argument("--boot-dir", type=Path, default=Path("boot"), help="directory holding boot records")
    parser.add_argument(
        "--secrets-root",
        type=Path,
        default=None,
        help="secrets root to check against (default: $TAP_SECRETS_ROOT or ~/tap-secrets)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if bool(args.record) == bool(args.profile):
        print("error: give exactly one of --record <path> or --profile <id>", file=sys.stderr)
        return 1
    path = args.record if args.record else profile_path(args.boot_dir, args.profile)
    profile_id = path.name[: -len(RECORD_SUFFIX)] if path.name.endswith(RECORD_SUFFIX) else path.stem
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read boot record {path}: {exc}", file=sys.stderr)
        return 1

    # A HOST entry point, so the host default applies when the environment names no
    # store — the same resolution order `tap.boot_pointer` uses for the very steps this
    # call is predicting (`tap.secrets_root.host_default`).
    root = host_tool_secrets_root(args.secrets_root)
    problems = check(entries_of(record), root)
    if problems:
        print(unsatisfied_message(problems, profile_id=profile_id, secrets_root=root), file=sys.stderr)
        return EXIT_UNSATISFIED
    return 0


__all__ = [
    "EXIT_UNSATISFIED",
    "CredentialProblem",
    "DeclaredCredential",
    "InstallCredentialError",
    "check",
    "check_or_raise",
    "declared_credentials",
    "entries_of",
    "redact_url_userinfo",
    "unsatisfied_message",
]


if __name__ == "__main__":
    sys.exit(main())
