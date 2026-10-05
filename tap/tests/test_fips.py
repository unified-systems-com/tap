"""Unit tests for tap.fips — the fail-closed FIPS boot self-check (req-cicd-base-image-lifecycle-6).

The self-check's *decision logic* is tested deterministically by monkeypatching the crypto
probes, so the tests pass regardless of whether the host/container is actually in FIPS mode
(the real enforcement is validated by booting the FIPS image, not here). Mode parsing is
tested directly.
"""

from __future__ import annotations

import pytest

from tap import fips


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", "1"),
        (" 1 ", "1"),  # whitespace-tolerant
        ("0", "0"),
        ("", "0"),  # unset/blank is NOT FIPS — never infer FIPS from silence
        ("true", "0"),  # only the exact "1" means FIPS on
        ("yes", "0"),
    ],
)
def test_declared_mode_parsing(monkeypatch, raw: str, expected: str) -> None:
    monkeypatch.setenv(fips.MODE_ENV, raw)
    assert fips.declared_mode() == expected


def test_declared_mode_defaults_to_off_when_unset(monkeypatch) -> None:
    monkeypatch.delenv(fips.MODE_ENV, raising=False)
    assert fips.declared_mode() == "0"


def test_mode_1_passes_when_enforced(monkeypatch) -> None:
    monkeypatch.setattr(fips, "declared_mode", lambda: "1")
    monkeypatch.setattr(fips, "_approved_python_hash_works", lambda: None)
    monkeypatch.setattr(fips, "_md5_for_security_refused", lambda: True)  # refused → enforced
    monkeypatch.setattr(fips, "_cryptography_positive_control", lambda *, expect_enforced: None)
    monkeypatch.setattr(fips, "_cryptography_md5_refused", lambda: None)
    assert fips.assert_declared_mode() == "1"


def test_mode_1_aborts_when_md5_not_refused(monkeypatch) -> None:
    """The L1 fail-open trap: image declares FIPS but the config didn't take effect."""
    monkeypatch.setattr(fips, "declared_mode", lambda: "1")
    monkeypatch.setattr(fips, "_approved_python_hash_works", lambda: None)
    monkeypatch.setattr(fips, "_md5_for_security_refused", lambda: False)  # NOT refused
    with pytest.raises(fips.FipsSelfCheckError, match="did not take effect"):
        fips.assert_declared_mode()


def test_mode_0_passes_when_not_enforced(monkeypatch) -> None:
    monkeypatch.setattr(fips, "declared_mode", lambda: "0")
    monkeypatch.setattr(fips, "_md5_for_security_refused", lambda: False)  # md5 works → non-FIPS
    monkeypatch.setattr(fips, "_cryptography_positive_control", lambda *, expect_enforced: None)
    assert fips.assert_declared_mode() == "0"


def test_mode_0_aborts_on_posture_mismatch(monkeypatch) -> None:
    """Declares FIPS off but MD5 is actually refused — the image lies about its posture."""
    monkeypatch.setattr(fips, "declared_mode", lambda: "0")
    monkeypatch.setattr(fips, "_md5_for_security_refused", lambda: True)  # unexpectedly refused
    with pytest.raises(fips.FipsSelfCheckError, match="does not match the declared mode"):
        fips.assert_declared_mode()


def test_main_returns_nonzero_on_failure(monkeypatch, capsys) -> None:
    def _boom() -> str:
        raise fips.FipsSelfCheckError("declared mode not enforced")

    monkeypatch.setattr(fips, "assert_declared_mode", _boom)
    assert fips.main() == 1
    assert "TAP-ABORT: fips:" in capsys.readouterr().err


def test_main_returns_zero_on_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(fips, "assert_declared_mode", lambda: "1")
    assert fips.main() == 0
    assert "FIPS self-check OK" in capsys.readouterr().out
