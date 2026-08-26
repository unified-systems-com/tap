"""Bootstrap pointer parsing + stage-0 fetch tests (spec-tap-boot-bootstrap).

The fetch tests build a real local git repo fixture (a plugin package with in-package boot
records + a ``[[boot.records]]`` manifest) and drive ``stage0_fetch`` against a ``git+file://``
source-ref — exercising the actual blobless clone / ``git show`` / integrity-verify path with
no network. Pure stdlib + git; no Django, no DB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tap import boot_pointer
from tap.boot_pointer import BootPointerError, parse_git_ref, parse_pointer, stage0_fetch
from tap.boot_records import canonical_digest_bytes

# --- parsing ----------------------------------------------------------------


def test_parse_pointer_record_only() -> None:
    p = parse_pointer("git+https://h/r@v0.1.0#soak")
    assert p.source_ref == "git+https://h/r@v0.1.0"
    assert p.record == "soak"
    assert p.digest is None


def test_parse_pointer_default_record() -> None:
    p = parse_pointer("git+https://h/r@v0.1.0")
    assert p.record is None and p.digest is None


def test_parse_pointer_digest() -> None:
    p = parse_pointer("foo#soak@sha256:abc123")
    assert p.record == "soak" and p.digest == "sha256:abc123"


def test_parse_git_ref_ok() -> None:
    ref = parse_git_ref("git+https://github.com/o/r@v0.1.0")
    assert ref is not None and ref.url == "https://github.com/o/r" and ref.rev == "v0.1.0"


def test_parse_git_ref_non_git_is_none() -> None:
    assert parse_git_ref("/some/local.boot.json") is None


def test_parse_git_ref_malformed_raises() -> None:
    with pytest.raises(BootPointerError):
        parse_git_ref("git+https://github.com/o/r")  # no @rev


# --- fixture: a real local git artifact -------------------------------------


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _make_git_artifact(tmp_path: Path, slug: str, records: dict[str, bytes], *, declare_default: bool = False) -> Path:
    """Create a git repo with tap_plugin/<slug>/boot/*.boot.json + a coherent tap-plugin.toml, tagged v0.1.0."""
    repo = tmp_path / f"repo-{slug}"
    pkg = repo / "tap_plugin" / slug
    boot = pkg / "boot"
    boot.mkdir(parents=True)
    for name, body in records.items():
        (boot / f"{name}.boot.json").write_bytes(body)

    toml_lines = [f'slug = "{slug}"\n', 'manifest_version = "0"\n']
    for name, body in records.items():
        toml_lines += [
            "\n[[boot.records]]\n",
            f'name = "{name}"\n',
            'description = "d"\n',
            f'sha256 = "{canonical_digest_bytes(body)}"\n',
        ]
    (pkg / "tap-plugin.toml").write_text("".join(toml_lines), encoding="utf-8")

    _run(["git", "init", "-q", "-b", "main"], repo)
    _run(["git", "config", "user.email", "t@t"], repo)
    _run(["git", "config", "user.name", "t"], repo)
    _run(["git", "add", "-A"], repo)
    _run(["git", "commit", "-q", "-m", "seed"], repo)
    _run(["git", "tag", "v0.1.0"], repo)
    return repo


def _ptr(repo: Path, record: str | None) -> boot_pointer.Pointer:
    frag = f"#{record}" if record else ""
    return parse_pointer(f"git+file://{repo}@v0.1.0{frag}")


def test_stage0_fetches_named_record(tmp_path: Path) -> None:
    play = b'{"version": 1, "flavor": "playground"}'
    soak = b'{"version": 1, "flavor": "soak"}'
    repo = _make_git_artifact(tmp_path, "foo", {"playground": play, "soak": soak})
    out = tmp_path / "out"

    staged = stage0_fetch(_ptr(repo, "soak"), out)
    assert staged == out / "soak.boot.json"
    # Byte-identical recipe fetched; and only the staged record persists (clone discarded).
    assert canonical_digest_bytes(staged.read_bytes()) == canonical_digest_bytes(soak)
    assert not list(out.glob("tap-stage0-*"))


def test_stage0_missing_record_fails_closed_with_available(tmp_path: Path) -> None:
    repo = _make_git_artifact(tmp_path, "foo", {"playground": b'{"a":1}', "soak": b'{"a":2}'})
    with pytest.raises(BootPointerError) as exc:
        stage0_fetch(_ptr(repo, "nope"), tmp_path / "out")
    assert "playground" in str(exc.value) and "soak" in str(exc.value)


def test_stage0_no_default_fails_closed(tmp_path: Path) -> None:
    repo = _make_git_artifact(tmp_path, "foo", {"playground": b'{"a":1}'})
    with pytest.raises(BootPointerError) as exc:
        stage0_fetch(_ptr(repo, None), tmp_path / "out")
    assert "no default record" in str(exc.value)


def test_stage0_integrity_mismatch_fails_closed(tmp_path: Path) -> None:
    """If the artifact's declared sha256 disagrees with the record content, fail closed."""
    repo = _make_git_artifact(tmp_path, "foo", {"soak": b'{"a":1}'})
    # Corrupt the committed record content so it no longer matches the declared digest.
    rec = repo / "tap_plugin" / "foo" / "boot" / "soak.boot.json"
    rec.write_bytes(b'{"a":999}')
    _run(["git", "commit", "-q", "-am", "tamper"], repo)
    _run(["git", "tag", "-f", "v0.1.0"], repo)
    with pytest.raises(BootPointerError) as exc:
        stage0_fetch(_ptr(repo, "soak"), tmp_path / "out")
    assert "integrity check FAILED" in str(exc.value)


def test_stage0_digest_reserved(tmp_path: Path) -> None:
    with pytest.raises(BootPointerError) as exc:
        stage0_fetch(parse_pointer("git+https://h/r@v0.1.0#soak@sha256:abc"), tmp_path / "out")
    assert "reserved" in str(exc.value)


def test_stage0_local_path_arm_returns_as_is(tmp_path: Path) -> None:
    local = tmp_path / "scratch.boot.json"
    local.write_bytes(b'{"version": 1}')
    staged = stage0_fetch(parse_pointer(str(local)), tmp_path / "out")
    assert staged == local


# --- credential envelope (stage-0's reduced-but-not-absent validation) --------


def _write_envelope(tmp_path: Path, key: str, *, kind: str = "github_pat", data: dict[str, str] | None = None) -> Path:
    import json

    root = tmp_path / "secrets"
    root.mkdir(exist_ok=True)
    path = root / f"{key}.secret.json"
    payload = {
        "scope": "tap_plugins.source",
        "key": key,
        "kind": kind,
        "description": "test envelope",
        "data": data if data is not None else {"token": "ghp_stage0_token"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_resolve_token_accepts_the_github_pat_kind(tmp_path: Path) -> None:
    root = _write_envelope(tmp_path, "src")
    resolved = boot_pointer._resolve_token("src", root)
    assert resolved is not None
    token, host, username = resolved
    assert token == "ghp_stage0_token"
    # Defaults come from the shared tap.git_invocation constants, not local literals.
    assert (host, username) == ("github.com", "x-access-token")


def test_resolve_token_rejects_a_foreign_kind(tmp_path: Path) -> None:
    """Credential confusion: an envelope of another kind must never have its token
    handed to the git host, even when it carries a `data.token` field."""
    root = _write_envelope(tmp_path, "notapat", kind="aws_assumed_role")
    with pytest.raises(BootPointerError) as exc:
        boot_pointer._resolve_token("notapat", root)
    assert "kind" in str(exc.value)
    # The refusal must not echo the secret it refused to use.
    assert "ghp_stage0_token" not in str(exc.value)


def test_resolve_token_still_requires_a_token_field(tmp_path: Path) -> None:
    root = _write_envelope(tmp_path, "empty", data={"not_a_token": "x"})
    with pytest.raises(BootPointerError) as exc:
        boot_pointer._resolve_token("empty", root)
    assert "data.token" in str(exc.value)


def test_stage0_credential_machinery_is_stdlib_only() -> None:
    """The host tools run under bare `python3` during spawn-session, BEFORE the
    container exists. If the shared credential leaf (or anything it pulls) ever
    needs a venv package, spawn breaks at the worst possible moment — so this
    walks the actual import graph of the host-runnable modules.

    The pre-commit secret scan is held to the same floor for the same reason: it
    runs on the developer's host, where a session worktree has no `.venv` at all,
    so a third-party import there makes the hook fail (or silently skip) on a
    normal machine.
    """
    import ast
    import sys

    repo_root = Path(__file__).resolve().parents[2]
    # docker/seed_manifest.py is container-side, not host-side, but shares the exact
    # constraint: it runs under bare python3 BEFORE `uv sync` creates the venv
    # (req-cicd-supply-chain-provenance-2), so it rides the same stdlib-only walk.
    host_modules = [
        "tap/git_invocation.py",
        "tap/secrets_root.py",
        "tap/boot_pointer.py",
        "tap/dev_workspace.py",
        ".githooks/precommit_secret_scan.py",
        "docker/seed_manifest.py",
    ]
    seen: set[str] = set()
    non_stdlib: dict[str, list[str]] = {}

    def walk(rel: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        tree = ast.parse((repo_root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                root_pkg = name.split(".")[0]
                if root_pkg == "tap":
                    # Follow first-party imports — the boundary is transitive.
                    sub = name.replace(".", "/") + ".py"
                    if (repo_root / sub).is_file():
                        walk(sub)
                    continue
                if root_pkg not in sys.stdlib_module_names and root_pkg != "__future__":
                    non_stdlib.setdefault(rel, []).append(name)

    for module in host_modules:
        walk(module)

    assert not non_stdlib, (
        "host-runnable modules must import only stdlib (they run under bare python3 "
        f"before the container exists): {non_stdlib}"
    )
