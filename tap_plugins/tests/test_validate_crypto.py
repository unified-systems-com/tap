"""Conformance verification of the manifest [fips] declaration against the crypto-BOM scan.

The "declare" half of declare-vs-decide (req-fips-crypto-bom / req-tap-plugin-manifest-v0-fips): a plugin
that ships a non-validated crypto provider must NOT be able to pass conformance by falsely claiming
`compatible`; an honest `uses-nonvalidated` passes; and an undeclared leak warns.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tap_plugins.manifest import FipsDeclaration
from tap_plugins.validate.service import ValidationResult, _check_crypto_providers


def _plugin_with_nonfips_so(tmp_path: Path) -> Path:
    # A plugin shipping a native lib whose bytes carry a non-validated provider signature (libsodium).
    (tmp_path / "vendored.so").write_bytes(b"\x7fELF ... sodium_init ... blob")
    return tmp_path


def _result() -> ValidationResult:
    return ValidationResult(ok=True, level="structure", plugin_path="x", strict=False)


def _crypto_check(result: ValidationResult):
    return next(c for c in result.checks if c.id == "crypto-providers")


def test_false_compatible_declaration_fails(tmp_path: Path) -> None:
    result = _result()
    manifest = SimpleNamespace(fips=FipsDeclaration(status="compatible", reason=None, providers=[]))
    _check_crypto_providers(_plugin_with_nonfips_so(tmp_path), manifest, result)
    assert _crypto_check(result).status == "fail"


def test_honest_uses_nonvalidated_passes(tmp_path: Path) -> None:
    result = _result()
    manifest = SimpleNamespace(
        fips=FipsDeclaration(
            status="uses-nonvalidated", reason="libsodium for a non-security checksum", providers=["libsodium"]
        )
    )
    _check_crypto_providers(_plugin_with_nonfips_so(tmp_path), manifest, result)
    check = _crypto_check(result)
    assert check.status == "pass"  # honest declaration → not a failure/warning
    assert any("uses-nonvalidated" in m.text for m in check.messages)


def test_undeclared_leak_warns(tmp_path: Path) -> None:
    result = _result()
    manifest = SimpleNamespace(fips=None)
    _check_crypto_providers(_plugin_with_nonfips_so(tmp_path), manifest, result)
    assert _crypto_check(result).status == "warn"


def test_pure_python_compatible_verifies(tmp_path: Path) -> None:
    result = _result()
    manifest = SimpleNamespace(fips=FipsDeclaration(status="compatible", reason=None, providers=[]))
    _check_crypto_providers(tmp_path, manifest, result)  # empty plugin dir → no crypto
    check = _crypto_check(result)
    assert check.status == "pass"
    assert any("verified" in m.text for m in check.messages)


# --- one verdict: conformance says what the plugin's own `ci` stack will do at boot (tap#377) --------


def _package_with_record(tmp_path: Path, slug: str, waivers: list[dict[str, Any]] | None) -> Path:
    """A package-mode plugin root (tap_plugin/<slug>/tap-plugin.toml + boot/ci.boot.json)."""
    package = tmp_path / "tap_plugin" / slug
    (package / "boot").mkdir(parents=True)
    (package / "tap-plugin.toml").write_text(f'slug = "{slug}"\n', encoding="utf-8")
    record: dict[str, Any] = {"description": "test stack", "install": {"plugins": [{"slug": slug}]}}
    if waivers is not None:
        record["fips_waivers"] = waivers
    (package / "boot" / "ci.boot.json").write_text(json.dumps(record), encoding="utf-8")
    return tmp_path


def _posture(result: ValidationResult) -> dict[str, Any]:
    details = _crypto_check(result).details or {}
    posture: dict[str, Any] = details["fips_posture"]
    return posture


def test_undeclared_native_binary_makes_the_ci_stack_abort(tmp_path: Path) -> None:
    root = _package_with_record(tmp_path, "vendor", waivers=None)
    _plugin_with_nonfips_so(root)
    result = _result()
    _check_crypto_providers(root, SimpleNamespace(slug="vendor", fips=None), result)
    check = _crypto_check(result)
    assert check.status == "warn"  # --strict promotes to a failure (req-tap-plugin-validate-strict)
    assert any("TAP-ABORT" in m.text and "libsodium" in m.text for m in check.messages)
    assert _posture(result) == {
        "found": ["libsodium"],
        "waived": [],
        "declared_unwaived": [],
        "unobservable": [],
        "ci_verdict": "abort",
    }


def test_declared_provider_needs_a_ci_record_waiver(tmp_path: Path) -> None:
    # zizmor's shape: honest [fips] declaration, binary not on disk here, record without a waiver.
    root = _package_with_record(tmp_path, "zz", waivers=None)
    manifest = SimpleNamespace(
        slug="zz", fips=FipsDeclaration(status="uses-nonvalidated", reason="linter TLS", providers=["boringssl"])
    )
    result = _result()
    _check_crypto_providers(root, manifest, result)
    check = _crypto_check(result)
    assert check.status == "warn"
    assert any("TAP-ABORT" in m.text and "boringssl (declared" in m.text for m in check.messages)
    assert _posture(result)["declared_unwaived"] == ["boringssl"]


def test_declared_provider_waived_on_the_ci_record_boots(tmp_path: Path) -> None:
    root = _package_with_record(
        tmp_path, "zz", waivers=[{"artifact": "*/bin/zizmor", "provider": "boringssl", "reason": "lints local YAML"}]
    )
    manifest = SimpleNamespace(
        slug="zz", fips=FipsDeclaration(status="uses-nonvalidated", reason="linter TLS", providers=["boringssl"])
    )
    result = _result()
    _check_crypto_providers(root, manifest, result)
    check = _crypto_check(result)
    assert check.status == "pass"
    assert _posture(result)["ci_verdict"] == "boots" and _posture(result)["waived"] == ["boringssl"]
    assert any(m.text.startswith("fips-posture: ") for m in check.messages)


def test_malformed_waiver_on_the_ci_record_fails(tmp_path: Path) -> None:
    root = _package_with_record(tmp_path, "zz", waivers=[{"artifact": "*/bin/zizmor", "provider": "boringssl"}])
    result = _result()
    _check_crypto_providers(root, SimpleNamespace(slug="zz", fips=None), result)
    check = _crypto_check(result)
    assert check.status == "fail"
    assert any("malformed fips_waivers" in m.text for m in check.messages)


def test_uninstalled_dependency_is_named_unobservable_not_clean(tmp_path: Path) -> None:
    root = _package_with_record(tmp_path, "dep", waivers=None)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "dep"\ndependencies = ["no-such-distribution-xyz>=1"]\n', encoding="utf-8"
    )
    result = _result()
    _check_crypto_providers(root, SimpleNamespace(slug="dep", fips=None), result)
    check = _crypto_check(result)
    assert check.status == "pass"
    assert _posture(result)["unobservable"] == ["no-such-distribution-xyz"]
    assert any("unobservable at authoring time" in m.text for m in check.messages)
