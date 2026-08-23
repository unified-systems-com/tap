"""Tests for tap_cares.secrets (spec-tap-cares-secrets.md).

Covers:
  req-tap-cares-secrets-files           — recursive `*.secret.json` discovery
  req-tap-cares-secrets-shape           — minimal JSON structural validation
  req-tap-cares-secrets-resilient-load  — bad files recorded, not crash-raised
  req-tap-cares-secrets-registry        — ScopedRegistry + SecretRef + resolve
  req-tap-cares-secrets-validation      — consumer-side kind + schema check
  req-tap-cares-secrets-redaction       — recursive sensitive-key redaction

All on-disk fixtures live in pytest's `tmp_path`. The repo never ships a real
or example `*.secret.json` file — operator-monitored alarms (filesystem and
git) should be able to assume any such file is a real leak.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from tap.registry import ScopedRegistry
from tap.secret_naming import SECRET_SUFFIX
from tap_cares.checks import check_secret_load_failures
from tap_cares.exceptions import (
    InvalidSecretRegistryKeyError,
    SecretLoadError,
    SecretNotFoundError,
    SecretValidationError,
)
from tap_cares.secrets import (
    Secret,
    SecretRef,
    load_secrets,
    redact,
    require_secret_kind,
    resolve_secret,
    secret_registry,
)
from tap_cares.secrets.loader import _check_basename_matches_key
from tap_cares.secrets.models import SecretLoadFailure
from tap_cares.secrets.registry import (
    SecretLoadReport,
    _validate_secret_token,
    secret_load_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "scope": "aws",
        "key": "prod-readonly",
        "kind": "aws_static_access_key",
        "description": "Read-only AWS credentials for inventory collector.",
        "data": {
            "access_key_id": "AKIA-FAKE",
            "secret_access_key": "FAKE",
            "region": "us-east-1",
        },
        "metadata": {"account_id": "123456789012"},
    }
    base.update(overrides)
    return base


def _write_secret(
    root: Path,
    *,
    subdir: str = "",
    basename: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Path:
    """Write a `<key>.secret.json` file under `root` (optionally nested).

    Basename defaults to `<payload['key']>.secret.json` when the payload
    declares a key, and otherwise falls back to `unnamed.secret.json` so
    tests that intentionally omit `key` still produce a file the loader
    will pick up and reject for the right reason.
    """
    payload = payload if payload is not None else _valid_payload()
    if basename is None:
        derived = payload.get("key", "unnamed")
        basename = f"{derived}{SECRET_SUFFIX}"
    target_dir = root / subdir if subdir else root
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / basename
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _fresh_registry() -> ScopedRegistry[Secret]:
    """Build an isolated registry so tests never touch the process-wide one.

    Names are uniquified because ScopedRegistry self-registers into
    `meta_registry`, which rejects duplicate names across the process.
    """
    return ScopedRegistry(
        f"secret_test_{uuid.uuid4().hex}",
        validate_key=_validate_secret_token,
        validate_scope=_validate_secret_token,
        title="Secret Test Registry",
        description="Per-test isolated secret registry.",
    )


def _load_recorded(root: Path, **kwargs: Any) -> tuple[list[SecretRef], SecretLoadReport]:
    """Load `root` into isolated registry+report and return (refs, report)."""
    report = SecretLoadReport()
    refs = load_secrets(root, registry=_fresh_registry(), report=report, **kwargs)
    return refs, report


@pytest.fixture(autouse=True)
def isolate_secret_registry():
    """Snapshot/restore the global registry around each test.

    Most tests pass `registry=` to `load_secrets` and don't touch the global,
    but `resolve_secret` reads from the global. Snapshotting keeps tests
    independent even if one accidentally registers.
    """
    saved = secret_registry.all()
    secret_registry._reset_for_testing()
    yield
    secret_registry._reset_for_testing(saved)


@pytest.fixture(autouse=True)
def isolate_secret_load_report():
    """Reset the global load report around each test.

    The system-check / health surfaces read the process-wide
    `secret_load_report`; a few tests populate it directly, so reset before and
    after to keep tests independent regardless of order.
    """
    secret_load_report.reset()
    yield
    secret_load_report.reset()


# ---------------------------------------------------------------------------
# Loader — req-tap-cares-secrets-files / -shape
# ---------------------------------------------------------------------------


class TestLoaderDiscovery:
    def test_missing_root_is_noop(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        registry = _fresh_registry()
        loaded = load_secrets(missing, registry=registry)
        assert loaded == []
        assert registry.keys() == []

    def test_none_root_is_noop(self) -> None:
        registry = _fresh_registry()
        assert load_secrets(None, registry=registry) == []
        assert registry.keys() == []

    def test_empty_root_is_noop(self, tmp_path: Path) -> None:
        registry = _fresh_registry()
        loaded = load_secrets(tmp_path, registry=registry)
        assert loaded == []
        assert registry.keys() == []

    def test_non_directory_root_raises(self, tmp_path: Path) -> None:
        file_root = tmp_path / "not-a-dir"
        file_root.write_text("x", encoding="utf-8")
        with pytest.raises(SecretLoadError, match="not a directory"):
            load_secrets(file_root, registry=_fresh_registry())

    def test_loads_single_file(self, tmp_path: Path) -> None:
        _write_secret(tmp_path)
        registry = _fresh_registry()
        refs = load_secrets(tmp_path, registry=registry)
        assert refs == [SecretRef("aws", "prod-readonly")]
        secret = registry.get("prod-readonly", scope="aws")
        assert secret.kind == "aws_static_access_key"
        assert secret.data["access_key_id"] == "AKIA-FAKE"
        assert secret.metadata["account_id"] == "123456789012"

    def test_recursive_discovery_under_nested_dirs(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, subdir="aws", payload=_valid_payload(key="prod-readonly"))
        _write_secret(
            tmp_path,
            subdir="aws",
            payload=_valid_payload(key="dev-sandbox"),
        )
        _write_secret(
            tmp_path,
            subdir="github",
            payload=_valid_payload(
                scope="github",
                key="fedramp-source",
                kind="github_pat",
                data={"token": "ghp_fake"},
                metadata={},
            ),
        )
        registry = _fresh_registry()
        refs = load_secrets(tmp_path, registry=registry)
        assert {r.qualified for r in refs} == {
            "aws:prod-readonly",
            "aws:dev-sandbox",
            "github:fedramp-source",
        }

    def test_directories_are_non_semantic(self, tmp_path: Path) -> None:
        """File can live in any directory; identity comes from JSON, not path."""
        _write_secret(
            tmp_path,
            subdir="completely/unrelated/path",
            payload=_valid_payload(scope="aws", key="prod-readonly"),
        )
        registry = _fresh_registry()
        load_secrets(tmp_path, registry=registry)
        assert registry.get("prod-readonly", scope="aws").ref.scope == "aws"

    def test_non_matching_suffix_ignored(self, tmp_path: Path) -> None:
        """`.secret.example.json` and bare `.json` files must not load."""
        (tmp_path / "prod-readonly.secret.example.json").write_text(json.dumps(_valid_payload()), encoding="utf-8")
        (tmp_path / "config.json").write_text(json.dumps(_valid_payload()), encoding="utf-8")
        registry = _fresh_registry()
        refs = load_secrets(tmp_path, registry=registry)
        assert refs == []
        assert registry.keys() == []

    def test_dotfiles_ignored(self, tmp_path: Path) -> None:
        (tmp_path / ".hidden.secret.json").write_text(json.dumps(_valid_payload()), encoding="utf-8")
        registry = _fresh_registry()
        assert load_secrets(tmp_path, registry=registry) == []


class TestLoaderShape:
    """Structural faults are recorded as degraded failures, not crash-raised.

    req-tap-cares-secrets-resilient-load: one bad file must never abort
    startup. Each test asserts the loader returns no ref for the bad file and
    records exactly one non-blocking failure with a recognizable reason.
    """

    def test_malformed_json_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "prod-readonly.secret.json"
        path.write_text("{ not valid json", encoding="utf-8")
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert len(report.failures) == 1
        assert "invalid JSON" in report.failures[0].reason
        assert report.degraded and not report.blocking

    def test_non_object_root_recorded(self, tmp_path: Path) -> None:
        path = tmp_path / "prod-readonly.secret.json"
        path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert "must contain a JSON object" in report.failures[0].reason

    @pytest.mark.parametrize("missing_field", ["scope", "key", "kind", "description", "data"])
    def test_missing_required_field_recorded(self, tmp_path: Path, missing_field: str) -> None:
        payload = _valid_payload()
        del payload[missing_field]
        _write_secret(tmp_path, payload=payload)
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert missing_field in report.failures[0].reason
        assert report.degraded and not report.blocking

    def test_empty_description_recorded(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, payload=_valid_payload(description="   "))
        _, report = _load_recorded(tmp_path)
        assert "description" in report.failures[0].reason

    def test_data_must_be_object_recorded(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, payload=_valid_payload(data=["x"]))
        _, report = _load_recorded(tmp_path)
        assert "data must be a JSON object" in report.failures[0].reason

    def test_metadata_optional(self, tmp_path: Path) -> None:
        payload = _valid_payload()
        del payload["metadata"]
        _write_secret(tmp_path, payload=payload)
        registry = _fresh_registry()
        load_secrets(tmp_path, registry=registry, report=SecretLoadReport())
        secret = registry.get("prod-readonly", scope="aws")
        assert dict(secret.metadata) == {}

    def test_basename_mismatch_recorded(self, tmp_path: Path) -> None:
        _write_secret(
            tmp_path,
            basename="mismatched.secret.json",
            payload=_valid_payload(key="prod-readonly"),
        )
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        failure = report.failures[0]
        assert "does not match" in failure.reason
        # scope:key is still recoverable from the parseable (if mis-keyed) file.
        assert failure.qualified == "aws:prod-readonly"

    def test_check_basename_helper_rejects_wrong_suffix(self, tmp_path: Path) -> None:
        path = tmp_path / "x.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(SecretLoadError, match="does not end with"):
            _check_basename_matches_key(path, "x")

    def test_duplicate_scope_key_across_dirs_recorded(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, subdir="a", payload=_valid_payload(key="prod-readonly"))
        _write_secret(tmp_path, subdir="b", payload=_valid_payload(key="prod-readonly"))
        refs, report = _load_recorded(tmp_path)
        # First registers; the duplicate is recorded, not raised.
        assert refs == [SecretRef("aws", "prod-readonly")]
        assert len(report.failures) == 1
        failure = report.failures[0]
        assert "Duplicate" in failure.reason and failure.qualified == "aws:prod-readonly"

    def test_invalid_scope_token_recorded(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, payload=_valid_payload(scope="not a valid scope"))
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert len(report.failures) == 1
        assert report.degraded and not report.blocking


class TestRequiredForBoot:
    """req-tap-cares-secrets-resilient-load: `required_for_boot` escalation."""

    def test_malformed_required_file_is_blocking(self, tmp_path: Path) -> None:
        """A required_for_boot file that fails to load is a BLOCKING failure."""
        _write_secret(
            tmp_path,
            basename="mismatched.secret.json",
            payload=_valid_payload(key="prod-readonly", metadata={"required_for_boot": True}),
        )
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert len(report.blocking) == 1
        assert not report.degraded
        assert report.blocking[0].qualified == "aws:prod-readonly"

    def test_malformed_without_flag_is_degraded(self, tmp_path: Path) -> None:
        _write_secret(
            tmp_path,
            basename="mismatched.secret.json",
            payload=_valid_payload(key="prod-readonly"),
        )
        _, report = _load_recorded(tmp_path)
        assert report.degraded and not report.blocking

    def test_required_for_boot_must_be_bool(self, tmp_path: Path) -> None:
        """A non-boolean flag is itself a load failure — and cannot escalate."""
        _write_secret(tmp_path, payload=_valid_payload(metadata={"required_for_boot": "yes"}))
        refs, report = _load_recorded(tmp_path)
        assert refs == []
        assert "required_for_boot must be a boolean" in report.failures[0].reason
        # A non-literal-true flag must not be trusted to escalate.
        assert report.degraded and not report.blocking

    def test_valid_required_for_boot_loads_cleanly(self, tmp_path: Path) -> None:
        _write_secret(tmp_path, payload=_valid_payload(metadata={"required_for_boot": True}))
        refs, report = _load_recorded(tmp_path)
        assert refs == [SecretRef("aws", "prod-readonly")]
        assert report.failures == []


class TestSecretLoadSystemCheck:
    """req-tap-cares-secrets-resilient-load: the strict check surface."""

    def test_clean_report_emits_no_messages(self) -> None:
        secret_load_report.reset()
        assert check_secret_load_failures(None) == []

    def test_blocking_failure_emits_error(self) -> None:
        secret_load_report.reset()
        secret_load_report.failures.append(
            SecretLoadFailure(
                path="/x/a.secret.json", reason="basename mismatch", required_for_boot=True, qualified="aws:a"
            )
        )
        messages = check_secret_load_failures(None)
        assert len(messages) == 1
        assert messages[0].id == "tap_cares.E001"
        assert "aws:a" in messages[0].msg

    def test_degraded_failure_emits_warning(self) -> None:
        secret_load_report.reset()
        secret_load_report.failures.append(
            SecretLoadFailure(path="/x/b.secret.json", reason="invalid JSON", required_for_boot=False, qualified=None)
        )
        messages = check_secret_load_failures(None)
        assert len(messages) == 1
        assert messages[0].id == "tap_cares.W001"
        assert "/x/b.secret.json" in messages[0].msg


class TestSecretsHealthProbe:
    """req-tap-cares-secrets-resilient-load-5: the running-instance health surface.

    `probe_secrets()` is registered into the `tap_health` registry from
    tap_cares's own `ready()`; here we exercise the report → ProbeResult mapping
    directly (the coverage the parked `/healthz` endpoint test used to provide).
    """

    def test_healthy_when_no_failures(self) -> None:
        from tap_cares.health import probe_secrets

        secret_load_report.reset()
        assert probe_secrets().status.value == "healthy"

    def test_degraded_on_nonblocking_failure(self) -> None:
        from tap_cares.health import probe_secrets

        secret_load_report.reset()
        secret_load_report.failures.append(
            SecretLoadFailure(
                path="/x/b.secret.json", reason="invalid JSON", required_for_boot=False, qualified="aws:b"
            )
        )
        result = probe_secrets()
        assert result.status.value == "degraded"
        assert result.code == "secrets.load_failed"
        assert result.context["failed"] == ["aws:b"]

    def test_unhealthy_on_required_for_boot_failure(self) -> None:
        from tap_cares.health import probe_secrets

        secret_load_report.reset()
        secret_load_report.failures.append(
            SecretLoadFailure(
                path="/x/a.secret.json", reason="basename mismatch", required_for_boot=True, qualified="aws:a"
            )
        )
        result = probe_secrets()
        assert result.status.value == "unhealthy"
        assert result.code == "secrets.required_for_boot_failed"
        assert result.context["failed"] == ["aws:a"]


# ---------------------------------------------------------------------------
# Registry + resolve_secret — req-tap-cares-secrets-registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_secret_ref_qualified_and_str(self) -> None:
        ref = SecretRef("aws", "prod-readonly")
        assert ref.qualified == "aws:prod-readonly"
        assert str(ref) == "aws:prod-readonly"

    def test_secret_repr_omits_data_and_metadata(self, tmp_path: Path) -> None:
        _write_secret(tmp_path)
        registry = _fresh_registry()
        load_secrets(tmp_path, registry=registry)
        secret = registry.get("prod-readonly", scope="aws")
        text = repr(secret)
        assert "AKIA-FAKE" not in text
        assert "account_id" not in text
        assert "aws:prod-readonly" in text
        assert "aws_static_access_key" in text

    def test_secret_data_is_immutable(self, tmp_path: Path) -> None:
        _write_secret(tmp_path)
        registry = _fresh_registry()
        load_secrets(tmp_path, registry=registry)
        secret = registry.get("prod-readonly", scope="aws")
        with pytest.raises(TypeError):
            secret.data["new"] = "x"  # type: ignore[index]

    def test_resolve_secret_returns_registered(self, tmp_path: Path) -> None:
        _write_secret(tmp_path)
        load_secrets(tmp_path)  # global registry
        secret = resolve_secret(SecretRef("aws", "prod-readonly"))
        assert secret.kind == "aws_static_access_key"

    def test_resolve_secret_missing_raises(self) -> None:
        with pytest.raises(SecretNotFoundError, match="aws:missing"):
            resolve_secret(SecretRef("aws", "missing"))

    def test_resolve_secret_invalid_ref_raises(self) -> None:
        with pytest.raises(InvalidSecretRegistryKeyError):
            resolve_secret(SecretRef("bad scope", "prod-readonly"))


# ---------------------------------------------------------------------------
# Redaction — req-tap-cares-secrets-redaction
# ---------------------------------------------------------------------------


class TestRedaction:
    def test_scalar_passthrough(self) -> None:
        assert redact("hello") == "hello"
        assert redact(42) == 42
        assert redact(None) is None

    @pytest.mark.parametrize(
        "key",
        [
            "secret",
            "Secret",
            "SECRET_ACCESS_KEY",
            "api_token",
            "PASSWORD",
            "private_key",
            "privateKey",
            "user_credential",
            "api_key",
            "apikey",
        ],
    )
    def test_sensitive_key_value_redacted(self, key: str) -> None:
        result = redact({key: "leak"})
        assert result == {key: "***REDACTED***"}

    def test_non_sensitive_keys_preserved(self) -> None:
        result = redact({"region": "us-east-1", "account_id": "123"})
        assert result == {"region": "us-east-1", "account_id": "123"}

    def test_nested_structure_recursed(self) -> None:
        payload = {
            "outer": {
                "region": "us-east-1",
                "secret_access_key": "leak",
                "nested": [{"token": "leak"}, {"region": "us-west-2"}],
            },
            "tuples": ({"password": "leak"}, "ok"),
        }
        result = redact(payload)
        assert result["outer"]["region"] == "us-east-1"
        assert result["outer"]["secret_access_key"] == "***REDACTED***"
        assert result["outer"]["nested"][0]["token"] == "***REDACTED***"
        assert result["outer"]["nested"][1]["region"] == "us-west-2"
        assert isinstance(result["tuples"], tuple)
        assert result["tuples"][0]["password"] == "***REDACTED***"

    def test_custom_mask(self) -> None:
        assert redact({"token": "x"}, mask="<gone>") == {"token": "<gone>"}

    def test_extra_sensitive(self) -> None:
        result = redact({"account_id": "leak"}, extra_sensitive=["account_id"])
        assert result == {"account_id": "***REDACTED***"}

    def test_redact_does_not_mutate_input(self) -> None:
        original = {"token": "leak", "nested": {"region": "us-east-1"}}
        redact(original)
        assert original == {"token": "leak", "nested": {"region": "us-east-1"}}


# ---------------------------------------------------------------------------
# Consumer validation — req-tap-cares-secrets-validation
# ---------------------------------------------------------------------------


AWS_STATIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["access_key_id", "secret_access_key"],
    "properties": {
        "access_key_id": {"type": "string", "minLength": 1},
        "secret_access_key": {"type": "string", "minLength": 1},
        "session_token": {"type": "string"},
        "region": {"type": "string"},
    },
    "additionalProperties": False,
}


def _load_and_get(tmp_path: Path, payload: dict[str, Any] | None = None) -> Secret:
    _write_secret(tmp_path, payload=payload)
    registry = _fresh_registry()
    load_secrets(tmp_path, registry=registry)
    key = (payload or _valid_payload())["key"]
    scope = (payload or _valid_payload())["scope"]
    return registry.get(key, scope=scope)


class TestRequireSecretKind:
    def test_kind_matches_no_schema(self, tmp_path: Path) -> None:
        secret = _load_and_get(tmp_path)
        require_secret_kind(secret, "aws_static_access_key")

    def test_kind_mismatch_raises(self, tmp_path: Path) -> None:
        secret = _load_and_get(tmp_path)
        with pytest.raises(SecretValidationError, match="expected 'github_pat'"):
            require_secret_kind(secret, "github_pat")

    def test_schema_pass(self, tmp_path: Path) -> None:
        secret = _load_and_get(tmp_path)
        require_secret_kind(secret, "aws_static_access_key", data_schema=AWS_STATIC_SCHEMA)

    def test_schema_failure_redacts_offending_value(self, tmp_path: Path) -> None:
        payload = _valid_payload(
            data={
                "access_key_id": "AKIA-FAKE",
                "secret_access_key": "VERY-SENSITIVE-LEAK-VALUE",
                "stowaway_field": "VERY-SENSITIVE-LEAK-VALUE",
            }
        )
        secret = _load_and_get(tmp_path, payload=payload)
        with pytest.raises(SecretValidationError) as excinfo:
            require_secret_kind(secret, "aws_static_access_key", data_schema=AWS_STATIC_SCHEMA)
        message = str(excinfo.value)
        assert "VERY-SENSITIVE-LEAK-VALUE" not in message
        assert "aws:prod-readonly" in message

    def test_schema_missing_required_field(self, tmp_path: Path) -> None:
        payload = _valid_payload(data={"access_key_id": "AKIA-FAKE"})
        secret = _load_and_get(tmp_path, payload=payload)
        with pytest.raises(SecretValidationError):
            require_secret_kind(secret, "aws_static_access_key", data_schema=AWS_STATIC_SCHEMA)
