"""Unit tests for the pre-boot git-source credential resolver (tap/plugin_source_auth.py).

Covers credential-ref classification, conditional necessity (explicit=required /
default=optional / non-git=none), the github_pat data_schema enforcement, the
no-token-leak repr, and the GIT_ASKPASS protocol (username vs. password prompt).
Settings-free module — these run without Django configured.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tap.plugin_source_auth import (
    SOURCE_SECRET_SCOPE,
    GitCredential,
    SourceAuthError,
    credential_ref_for_source,
    git_askpass_env,
    resolve_git_credential,
)
from tap.secret_naming import SECRET_SUFFIX


def _pat_payload(key: str, data: dict[str, Any] | None = None, *, kind: str = "github_pat") -> dict[str, Any]:
    return {
        "scope": SOURCE_SECRET_SCOPE,
        "key": key,
        "kind": kind,
        "description": "Read-only PAT for the plugin repos.",
        "data": data if data is not None else {"token": "ghp_secret_value"},
    }


def _write_secret(root: Path, payload: dict[str, Any]) -> Path:
    path = root / f"{payload['key']}{SECRET_SUFFIX}"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _git_source(**over: object) -> dict[str, Any]:
    src: dict[str, Any] = {
        "type": "git",
        "url": "https://github.com/unified-systems-com/tap-plugin-x.git",
        "rev": "abc123",
    }
    src.update(over)
    return src


class TestCredentialRefForSource:
    def test_git_with_explicit_credential(self) -> None:
        assert credential_ref_for_source(_git_source(credential="acme")) == "acme"

    def test_git_without_credential_is_none(self) -> None:
        # No implicit default key — a git source with no `credential` is public.
        assert credential_ref_for_source(_git_source()) is None

    def test_editable_source_has_no_credential(self) -> None:
        assert credential_ref_for_source({"type": "editable", "path": "plugins/x"}) is None

    def test_path_source_has_no_credential(self) -> None:
        assert credential_ref_for_source({"type": "path", "path": "plugins/x"}) is None

    def test_non_mapping_is_none(self) -> None:
        assert credential_ref_for_source(None) is None  # type: ignore[arg-type]


class TestResolveGitCredential:
    def test_explicit_credential_resolves_with_defaults(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, _pat_payload("acme", {"token": "ghp_abc"}))
        cred = resolve_git_credential(tmp_path, _git_source(credential="acme"))
        assert cred == GitCredential(token="ghp_abc", host="github.com", username="x-access-token")

    def test_explicit_credential_honors_host_and_username_overrides(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, _pat_payload("ghe", {"token": "t", "host": "ghe.corp", "username": "svc"}))
        cred = resolve_git_credential(tmp_path, _git_source(credential="ghe"))
        assert cred is not None and cred.host == "ghe.corp" and cred.username == "svc"

    def test_explicit_credential_missing_secret_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SourceAuthError, match="declares credential 'nope'"):
            resolve_git_credential(tmp_path, _git_source(credential="nope"))

    def test_git_without_credential_is_none_even_with_secret_present(self, tmp_path: Path) -> None:
        # No implicit default: a public git source ignores any mounted secret.
        _write_secret(tmp_path, _pat_payload("source", {"token": "ghp_unused"}))
        assert resolve_git_credential(tmp_path, _git_source()) is None

    def test_non_git_source_is_none(self, tmp_path: Path) -> None:
        assert resolve_git_credential(tmp_path, {"type": "editable", "path": "plugins/x"}) is None

    def test_no_secrets_root_with_explicit_raises(self) -> None:
        with pytest.raises(SourceAuthError, match="TAP_SECRETS_ROOT is not set"):
            resolve_git_credential(None, _git_source(credential="acme"))

    def test_no_secrets_root_without_credential_is_none(self) -> None:
        assert resolve_git_credential(None, _git_source()) is None

    def test_wrong_kind_raises(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, _pat_payload("acme", kind="oidc_client"))
        with pytest.raises(SourceAuthError, match="kind 'oidc_client', expected 'github_pat'"):
            resolve_git_credential(tmp_path, _git_source(credential="acme"))

    def test_malformed_data_missing_token_raises(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, _pat_payload("acme", {"host": "github.com"}))
        with pytest.raises(SourceAuthError, match="malformed data block"):
            resolve_git_credential(tmp_path, _git_source(credential="acme"))

    def test_malformed_data_unknown_field_raises(self, tmp_path: Path) -> None:
        # additionalProperties:false — a repos-bearing collector schema must not pass here.
        _write_secret(tmp_path, _pat_payload("acme", {"token": "t", "repos": ["a/b"]}))
        with pytest.raises(SourceAuthError, match="malformed data block"):
            resolve_git_credential(tmp_path, _git_source(credential="acme"))


class TestGitCredentialRepr:
    def test_repr_omits_token(self) -> None:
        text = repr(GitCredential(token="ghp_topsecret", host="github.com", username="x-access-token"))
        assert "ghp_topsecret" not in text
        assert "redacted" in text
        assert "github.com" in text


class TestGitAskpassEnv:
    def test_overlay_shape_and_temp_script(self) -> None:
        cred = GitCredential(token="ghp_tok", host="github.com", username="x-access-token")
        with git_askpass_env(cred) as overlay:
            script = Path(overlay["GIT_ASKPASS"])
            assert script.is_file()
            assert overlay["GIT_TERMINAL_PROMPT"] == "0"
            assert overlay["TAP_GIT_USERNAME"] == "x-access-token"
            assert overlay["TAP_GIT_PASSWORD"] == "ghp_tok"
            # owner-only permissions (rwx------)
            assert stat.S_IMODE(script.stat().st_mode) == stat.S_IRWXU
            # the script body itself carries no secret
            assert "ghp_tok" not in script.read_text(encoding="utf-8")
        # cleaned up on exit
        assert not script.exists()

    def test_askpass_answers_username_and_password_prompts(self) -> None:
        cred = GitCredential(token="ghp_tok", host="github.com", username="x-access-token")
        with git_askpass_env(cred) as overlay:
            env = {**os.environ, **overlay}
            askpass = overlay["GIT_ASKPASS"]
            user = subprocess.run(
                [askpass, "Username for 'https://github.com': "], env=env, capture_output=True, text=True
            )
            pwd = subprocess.run(
                [askpass, "Password for 'https://x-access-token@github.com': "], env=env, capture_output=True, text=True
            )
            assert user.stdout == "x-access-token"
            assert pwd.stdout == "ghp_tok"
