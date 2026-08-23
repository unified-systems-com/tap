"""Proof of the read-only search write-detection backstop (req-grid-search-readonly.sec-6).

The ``search_readonly`` connection runs ``default_transaction_read_only=on``, so a
write is rejected by PostgreSQL (SQLSTATE 25006). That rejection is the *integrity*
half — it prevents the write. On its own it is silent, indistinguishable from a
malformed query. This guard adds the *detection* half: a `security` Flaw (the
response-triggering alert) fires before the rejection propagates, while the write
stays blocked.

Uses ``transaction=True`` + the ``search_readonly`` alias so the real read-only
session is exercised (not a rolled-back inline transaction), matching the DB-marker
convention in spec-tap-testing.md.
"""

from __future__ import annotations

import logging

import pytest
from django.db import InternalError, connections

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])


def _attempt_write_expecting_rejection() -> None:
    """Run a write on the read-only search connection; the DB rejects it.

    Closes the connection afterwards so the aborted read-only transaction does not
    linger into pytest-django's ``transaction=True`` teardown.
    """
    conn = connections["search_readonly"]
    try:
        with conn.cursor() as cursor:
            # A no-op DELETE is still a write statement — PostgreSQL rejects it in a
            # read-only transaction before touching any row.
            cursor.execute("DELETE FROM tap_entity WHERE 1=0")
    finally:
        conn.close()


def test_write_on_readonly_connection_is_rejected():
    """Integrity half: the read-only session refuses the write at the DB level."""
    with pytest.raises(InternalError):
        _attempt_write_expecting_rejection()


def test_write_on_readonly_connection_emits_security_flaw(caplog):
    """Detection half: a `security` FLAW fires before the rejection propagates."""
    with caplog.at_level(logging.ERROR):
        with pytest.raises(InternalError):
            _attempt_write_expecting_rejection()

    flaws = [r for r in caplog.records if getattr(r, "message_code", None) == "FLAW"]
    assert flaws, "expected a FLAW record from the read-only write guard"
    md = flaws[-1].message_data
    assert md["flaw_tags"] == ["security"]
    assert md["invariant_id"] == "search_readonly_write_blocked"
    assert md["handling"] == "abort_operation"
    # Blame class is decided by the offending callsite; this test frame is
    # first-party TAP, so the Flaw is classed `code` (a core executor defect).
    assert md["flaw_class"] == "code"


def test_read_on_readonly_connection_emits_no_flaw(caplog):
    """No false alert: a normal read on the connection must not trip the guard."""
    with caplog.at_level(logging.ERROR):
        conn = connections["search_readonly"]
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    flaws = [
        r
        for r in caplog.records
        if getattr(r, "message_code", None) == "FLAW"
        and getattr(r, "message_data", {}).get("invariant_id") == "search_readonly_write_blocked"
    ]
    assert not flaws, "a read must not emit a read-only-write FLAW"
