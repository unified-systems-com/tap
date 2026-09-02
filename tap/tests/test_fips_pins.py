"""The FIPS pins derivation and the claims it verifies (req-fips-pin-currency-8, decision D17).

The real build script is read here on purpose: these tests are the per-commit proof that the
pin, the CMVP table, the crypto-BOM boundary, and the public claims still agree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tap import fips_pins
from tap.crypto_providers import Boundary, system_openssl_boundary
from tap.fips_pins import PinsUnreadable, Posture, Validation, check_claims, read_pins

VALIDATED = Validation("4282", "140-2", "2026-09-21")


def _script(
    tmp_path: Path, version: str, table: str = "3.0.9=4282/140-2/2026-09-21 3.1.2=4985/140-3/2030-03-10"
) -> Path:
    p = tmp_path / "build-openssl-fips.sh"
    p.write_text(
        f'#!/bin/sh\n# prose\nOSSL_VERSION={version}\nOSSL_SHA256={"e" * 64}\nOSSL_SIGNING_PRIMARY={"A" * 40}\n'
        f'OSSL_CMVP_VALIDATED="{table}"\n',
        encoding="utf-8",
    )
    return p


@pytest.mark.spec("req-fips-pin-currency-2")
def test_real_pins_are_readable_and_internally_consistent() -> None:
    pins = read_pins()
    assert pins.version and len(pins.sha256) == 64 and len(pins.signing_primary) == 40
    assert "3.0.9" in pins.validated and pins.validated["3.0.9"].certificate == "4282"
    assert "3.1.2" in pins.validated and pins.validated["3.1.2"].certificate == "4985"
    assert pins.posture in (Posture.VALIDATED, Posture.UNVALIDATED_BUILD)


@pytest.mark.spec("req-fips-pin-currency-8")
def test_validated_pin_derives_certificate_and_validated_boundary(tmp_path: Path) -> None:
    pins = read_pins(_script(tmp_path, "3.0.9"))
    assert pins.validation == VALIDATED and pins.posture is Posture.VALIDATED
    assert "CMVP #4282 (FIPS 140-2, sunset 2026-09-21)" in pins.status_clause()


@pytest.mark.spec("req-fips-pin-currency-8")
def test_unvalidated_pin_is_the_distinct_state_not_validated(tmp_path: Path) -> None:
    """A version with no certificate is FIPS_MODE_UNVALIDATED_BUILD — never VALIDATED, never a failure."""
    pins = read_pins(_script(tmp_path, "3.0.22"))
    assert pins.validation is None and pins.posture is Posture.UNVALIDATED_BUILD
    assert "not CMVP-validated as shipped" in pins.status_clause() and "D17" in pins.status_clause()
    assert "3.0.9/#4282" in pins.status_clause()


@pytest.mark.spec("req-fips-pin-currency-3")
def test_unreadable_or_malformed_pins_are_not_observable(tmp_path: Path) -> None:
    with pytest.raises(PinsUnreadable):
        read_pins(tmp_path / "missing.sh")
    with pytest.raises(PinsUnreadable, match="OSSL_CMVP_VALIDATED"):
        read_pins(_script(tmp_path, "3.0.9", table="3.0.9=4282"))  # entry missing standard/sunset
    bad = tmp_path / "noversion.sh"
    bad.write_text('OSSL_CMVP_VALIDATED="3.0.9=4282/140-2/2026-09-21"\n', encoding="utf-8")
    with pytest.raises(PinsUnreadable, match="OSSL_VERSION"):
        read_pins(bad)


@pytest.mark.spec("req-fips-pin-currency-8")
def test_claims_that_disagree_with_the_pin_fail(tmp_path: Path) -> None:
    doc = tmp_path / "README.md"
    doc.write_text("ships CMVP #4282 provider\nand a FIPS-validated build\n", encoding="utf-8")
    assert check_claims(read_pins(_script(tmp_path, "3.0.9")), [doc]) == []
    problems = check_claims(read_pins(_script(tmp_path, "3.1.2")), [doc])
    assert any("claims CMVP #4282" in p and "#4985" in p for p in problems)
    problems = check_claims(read_pins(_script(tmp_path, "3.0.22")), [doc])
    assert any("claims CMVP #4282 but OpenSSL 3.0.22 is not a validated build" in p for p in problems)
    assert any("says 'FIPS-validated'" in p for p in problems)
    assert any("not readable" in p for p in check_claims(read_pins(_script(tmp_path, "3.0.9")), [tmp_path / "gone.md"]))


@pytest.mark.spec("req-fips-pin-currency-8")
def test_system_openssl_boundary_follows_the_running_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fips_pins, "PIN_SCRIPT", _script(tmp_path, "3.0.22"))
    monkeypatch.setattr(fips_pins.read_pins, "__defaults__", (fips_pins.PIN_SCRIPT,))
    # No provider observable → the pin is the fact: 3.0.22 is an unvalidated build.
    monkeypatch.setattr(fips_pins, "observed_provider_version", lambda: None)
    boundary, rationale = system_openssl_boundary()
    assert boundary is Boundary.FIPS_MODE_UNVALIDATED_BUILD and "D17" in rationale and "pinned version" in rationale
    # An older validated image running newer code: classified by what RUNS, drift named.
    monkeypatch.setattr(fips_pins, "observed_provider_version", lambda: "3.0.9")
    boundary, rationale = system_openssl_boundary()
    assert boundary is Boundary.VALIDATED and "#4282" in rationale and "image and code differ" in rationale
    assert fips_pins.running_version(read_pins(fips_pins.PIN_SCRIPT)) == ("3.0.9", "active")
    monkeypatch.setattr(fips_pins.read_pins, "__defaults__", (tmp_path / "missing.sh",))
    boundary, rationale = system_openssl_boundary()
    assert boundary is None and "NOT OBSERVABLE" in rationale


@pytest.mark.spec("req-fips-pin-currency-8")
def test_observed_provider_version_parses_the_fips_block_and_reports_unobservable() -> None:
    out = (
        "Providers:\n  base\n    name: OpenSSL Base Provider\n    version: 3.6.4\n    status: active\n"
        "  fips\n    name: OpenSSL FIPS Provider\n    version: 3.0.9\n    status: active\n"
    )

    def ok(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, out, "")

    def no_fips(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, "Providers:\n  base\n    version: 3.6.4\n", "")

    def broken(*a, **k):
        raise OSError("no openssl")

    assert fips_pins.observed_provider_version(ok) == "3.0.9"
    assert fips_pins.observed_provider_version(no_fips) is None
    assert fips_pins.observed_provider_version(broken) is None
