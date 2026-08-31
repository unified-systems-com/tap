"""The enrollment routes accept only a well-formed invitation public id.

`Invitation.public_id` is `secrets.token_hex(8)` and its help text calls it "the
log-safe lookup handle". That was true of the MINTED value and false of the one
arriving off the wire: Django's `<str:>` converter is `[^/]+`, which in Python's
`re` matches a newline, so `/auth/enroll/abc%0A<forged line>/` reached the view
and was logged verbatim — an UNAUTHENTICATED caller writing arbitrary lines into
TAP's log stream (CWE-117, SonarCloud pythonsecurity:S5145).

Constraining the route is the fix, so these tests assert at the boundary: a
malformed id must never reach a view, a logger, or the database.
"""

import json
import logging

import pytest
from _pytest.logging import LogCaptureFixture
from django.test import Client
from django.urls import NoReverseMatch, reverse

from tap_auth import invitations, views_enroll

WELL_FORMED = "a1b2c3d4e5f60718"  # 16 lowercase hex chars — token_hex(8)

MALFORMED = [
    pytest.param("abc%0A2026-01-01 CRITICAL forged", id="newline-injection"),
    pytest.param("abc%0D%0Aforged", id="crlf-injection"),
    pytest.param("A1B2C3D4E5F60718", id="uppercase-hex"),
    pytest.param("a1b2c3d4e5f6071", id="too-short"),
    pytest.param("a1b2c3d4e5f607189", id="too-long"),
    pytest.param("a1b2c3d4e5f6071z", id="non-hex-char"),
    pytest.param("../../etc/passwd", id="traversal"),
]

SUFFIXES = ["", "options/", "verify/"]

# The views hit the Invitation table on a well-formed id.
pytestmark = pytest.mark.django_db


@pytest.fixture
def anon() -> Client:
    return Client(SERVER_NAME="localhost")


# Derived from the modules rather than spelled out, so a rename moves the filter too.
ENROLLMENT_LOGGERS = (invitations.__name__, views_enroll.__name__)


class _AuthLogs:
    """The records the ENROLLMENT modules emitted during a request.

    Scoped deliberately. Two other loggers legitimately name the requested path on a
    rejected request — Django's ``django.request`` ("Not Found") and TAP's
    ``tap_auth.policy`` (authz denied) — and neither forges a line, because Django
    escapes the path before it reaches them: the hostile newline arrives as the
    literal two characters ``\n``. The property under test is narrower and sharper —
    that the enrollment code itself never sees the value at all.
    """

    def __init__(self, caplog: LogCaptureFixture) -> None:
        self._caplog = caplog

    @property
    def records(self) -> list[logging.LogRecord]:
        return [r for r in self._caplog.records if r.name in ENROLLMENT_LOGGERS]

    @property
    def text(self) -> str:
        return "\n".join(r.getMessage() for r in self.records)


@pytest.fixture
def captured_auth_logs(caplog: LogCaptureFixture) -> _AuthLogs:
    caplog.set_level(logging.INFO)
    return _AuthLogs(caplog)


@pytest.mark.parametrize("public_id", MALFORMED)
@pytest.mark.parametrize("suffix", SUFFIXES)
def test_malformed_public_id_never_reaches_the_enrollment_view(
    anon, captured_auth_logs, caplog, public_id, suffix
) -> None:
    """The route does not match, so the request dies before any view runs.

    Asserted as "did not reach the view" rather than a literal 404: an unmatched
    path under ``/auth/`` is answered by the login wall (403) rather than the URL
    resolver (404), and which one replies is not the property under test. What
    matters is that no enrollment view — and therefore no logger and no query —
    ever saw the value.
    """
    response = anon.post(
        f"/auth/enroll/{public_id}/{suffix}",
        data=json.dumps({"secret": "x"}),
        content_type="application/json",
    )
    assert response.status_code in (403, 404), f"reached a view with {public_id!r}"
    assert captured_auth_logs.records == []
    # Nothing anywhere may carry a real line break — that is what forging would mean.
    assert not any("\n" in r.getMessage() for r in caplog.records)


def test_newline_in_public_id_cannot_forge_a_log_line(anon, captured_auth_logs) -> None:
    """The finding itself: an anonymous caller must not be able to write a log line."""
    anon.post(
        "/auth/enroll/abc%0A2026-01-01 CRITICAL FORGED-ADMIN-LOGIN/options/",
        data=json.dumps({"secret": "x"}),
        content_type="application/json",
    )
    assert "FORGED-ADMIN-LOGIN" not in captured_auth_logs.text
    # And no record carries a real line break, which is what "forging" would mean.
    assert not any("\n" in r.getMessage() for r in captured_auth_logs.records)


def test_well_formed_public_id_still_reaches_the_view(anon, captured_auth_logs) -> None:
    """Positive control: the constraint must not break redemption.

    Without this, every assertion above would pass just as well against a route
    that had been deleted.
    """
    response = anon.post(
        f"/auth/enroll/{WELL_FORMED}/options/",
        data=json.dumps({"secret": "x"}),
        content_type="application/json",
    )
    assert response.status_code == 400  # reached the view; unknown invitation
    assert WELL_FORMED in captured_auth_logs.text


@pytest.mark.parametrize("name", ["passkey_enroll", "passkey_enroll_options", "passkey_enroll_verify"])
def test_reverse_still_builds_enrollment_urls(name) -> None:
    """Enrollment links are built by reverse(); a converter that could not round-trip
    a minted id would break MINTING rather than redemption, and silently."""
    assert WELL_FORMED in reverse(name, kwargs={"public_id": WELL_FORMED})


def test_reverse_refuses_a_malformed_id() -> None:
    """The converter is enforced in both directions."""
    with pytest.raises(NoReverseMatch):
        reverse("passkey_enroll_options", kwargs={"public_id": "not-a-hex-token"})
