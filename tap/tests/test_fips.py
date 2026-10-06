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
    monkeypatch.setattr(fips, "_assert_single_openssl_core", lambda: None)
    monkeypatch.setattr(fips, "_approved_python_hash_works", lambda: None)
    monkeypatch.setattr(fips, "_md5_for_security_refused", lambda: True)  # refused → enforced
    monkeypatch.setattr(fips, "_cryptography_positive_control", lambda *, expect_enforced: None)
    monkeypatch.setattr(fips, "_cryptography_md5_refused", lambda: None)
    assert fips.assert_declared_mode() == "1"


def test_mode_1_aborts_when_md5_not_refused(monkeypatch) -> None:
    """The L1 fail-open trap: image declares FIPS but the config didn't take effect."""
    monkeypatch.setattr(fips, "declared_mode", lambda: "1")
    monkeypatch.setattr(fips, "_assert_single_openssl_core", lambda: None)
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


# --- tap#933: two OpenSSL cores in one process -------------------------------------------------

_ONE_CORE = (
    "7f0000000000-7f0000100000 r--p 00000000 00:2a 123 /usr/lib/libcrypto.so.4\n"
    "7f0000100000-7f0000400000 r-xp 00100000 00:2a 123 /usr/lib/libcrypto.so.4\n"
    "7f0000500000-7f0000600000 r--p 00000000 00:2a 456 /usr/lib/libssl.so.4\n"
    "7f0000700000-7f0000800000 rw-p 00000000 00:00 0 \n"
)
_TWO_CORES = _ONE_CORE + "7f0000900000-7f0000a00000 r-xp 00000000 00:2a 789 /usr/lib/libcrypto.so.3\n"
_BUNDLED = _ONE_CORE + (
    "7f0000900000-7f0000a00000 r-xp 00000000 00:2a 790 "
    "/app/.venv/lib/python3.14/site-packages/cryptography.libs/libcrypto-1a2b3c4d.so.3\n"
)


@pytest.mark.spec("req-fips-single-openssl-core-3")
def test_one_library_mapped_in_several_segments_is_one_core() -> None:
    assert fips.openssl_cores(_ONE_CORE) == {"/usr/lib/libcrypto.so.4"}


@pytest.mark.spec("req-fips-single-openssl-core-1")
def test_a_second_libcrypto_is_a_second_core() -> None:
    assert fips.openssl_cores(_TWO_CORES) == {"/usr/lib/libcrypto.so.3", "/usr/lib/libcrypto.so.4"}


@pytest.mark.spec("req-fips-single-openssl-core-1")
def test_single_core_passes_and_two_cores_abort_naming_both() -> None:
    """Both branches: tap#933's exact shape (a 3.6-built wheel beside 4.0's CPython) must refuse."""
    fips._assert_single_openssl_core(_ONE_CORE)
    with pytest.raises(fips.FipsSelfCheckError, match="libcrypto.so.3.*libcrypto.so.4"):
        fips._assert_single_openssl_core(_TWO_CORES)


@pytest.mark.spec("req-fips-single-openssl-core-2")
def test_the_core_check_runs_before_any_crypto(monkeypatch) -> None:
    """In the two-core case the first positive control is what dies, so the check must come first."""
    calls: list[str] = []
    monkeypatch.setattr(fips, "declared_mode", lambda: "1")

    def _two_cores() -> None:
        calls.append("cores")
        raise fips.FipsSelfCheckError("two cores")

    monkeypatch.setattr(fips, "_assert_single_openssl_core", _two_cores)
    monkeypatch.setattr(fips, "_cryptography_positive_control", lambda *, expect_enforced: calls.append("crypto"))
    with pytest.raises(fips.FipsSelfCheckError, match="two cores"):
        fips.assert_declared_mode()
    assert calls == ["cores"]


@pytest.mark.spec("req-fips-single-openssl-core-4")
def test_a_wheel_bundling_its_own_openssl_is_a_second_core() -> None:
    """auditwheel names a bundled copy `libcrypto-<hash>.so.N`; the L17 road must be caught too."""
    cores = fips.openssl_cores(_BUNDLED)
    assert len(cores) == 2
    with pytest.raises(fips.FipsSelfCheckError, match="libcrypto-1a2b3c4d"):
        fips._assert_single_openssl_core(_BUNDLED)


@pytest.mark.spec("req-fips-single-openssl-core-4")
def test_an_unreadable_maps_file_fails_closed(monkeypatch) -> None:
    """Under a FIPS declaration, not being able to look is not a pass."""
    import builtins

    real_open = builtins.open

    def _deny(path, *args, **kwargs):
        if path == "/proc/self/maps":
            raise PermissionError("denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _deny)
    with pytest.raises(fips.FipsSelfCheckError, match="cannot read /proc/self/maps"):
        fips._assert_single_openssl_core()
