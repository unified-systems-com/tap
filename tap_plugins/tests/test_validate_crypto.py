"""Conformance verification of the manifest [fips] declaration against the crypto-BOM scan.

The "declare" half of declare-vs-decide (req-fips-crypto-bom / req-tap-plugin-manifest-v0-fips): a plugin
that ships a non-validated crypto provider must NOT be able to pass conformance by falsely claiming
`compatible`; an honest `uses-nonvalidated` passes; and an undeclared leak warns.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
