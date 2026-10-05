"""CollectorBase.submit_grift rejection contract (no DB, no tap_grid).

Covers req-tap-cares-collector-grift-import-9..11: GRIFT rejects a batch
atomically; a rejected batch is in neither imported_batches nor
skipped_batches, only result.errors. submit_grift owns the safe default
(on_rejection="abort": record GRIFT_BATCH_REJECTED + raise
GriftRejectedError) so no collector copies a guard; "return" is the
explicit partial-success opt-out.
"""

from __future__ import annotations

import uuid

import pytest

from tap_cares.collectors.base import CollectorBase
from tap_cares.collectors.config import CollectorConfig
from tap_cares.exceptions import GriftRejectedError


class _Collector(CollectorBase):
    def run(self) -> None:  # abstract; unused — we call submit_grift directly
        raise NotImplementedError


def _make() -> _Collector:
    return _Collector(
        CollectorConfig(
            collector_entity_id=uuid.uuid7(),
            collection_job_entity_id=uuid.uuid7(),
        )
    )


class _Issue:
    code = "duplicate_entity_id"
    message = "Duplicate entity_id 'deadbeef'"


class _Counts:
    batches_imported = 0


class _RejectedResult:
    imported_batches: list = []
    skipped_batches: list = []
    errors = [_Issue()]
    counts = _Counts()


class _Batch:
    def __init__(self, bid: str) -> None:
        self.batch_entity_id = bid
        self.skips: list[object] = []  # mirrors GriftImportedBatch: a clean import skipped no edge
        self.authority: list[object] = []  # and made no authority claim


class _CleanCounts:
    batches_imported = 1


class _CleanResult:
    imported_batches = [_Batch("b-1")]
    skipped_batches: list = []
    errors: list = []
    counts = _CleanCounts()


def _stub_import(monkeypatch, result) -> None:
    # submit_grift does `from tap_grid.grift import grift_import` locally.
    monkeypatch.setattr("tap_grid.grift.grift_import", lambda *a, **k: result)


class TestSubmitGriftRejectionContract:
    def test_abort_is_default_raises_and_records(self, monkeypatch):
        _stub_import(monkeypatch, _RejectedResult())
        c = _make()
        with pytest.raises(GriftRejectedError):
            c.submit_grift({"batches": []})  # on_rejection defaults to "abort"
        errs = [e for e in c.results["error"] if e["message_code"] == "GRIFT_BATCH_REJECTED"]
        assert len(errs) == 1
        assert "duplicate_entity_id" in errs[0]["message"]
        assert "nothing landed" in errs[0]["message"]
        assert errs[0]["message_data"] == {"error_count": 1, "batches_imported": 0}

    def test_return_opt_out_does_not_raise_or_record(self, monkeypatch):
        _stub_import(monkeypatch, _RejectedResult())
        c = _make()
        result = c.submit_grift({"batches": []}, on_rejection="return")
        assert result.errors  # caller now owns this
        assert c.results["error"] == []  # base did not record/raise

    def test_clean_import_returns_and_accumulates(self, monkeypatch):
        _stub_import(monkeypatch, _CleanResult())
        c = _make()
        result = c.submit_grift({"batches": []})
        assert result.counts.batches_imported == 1
        assert c.results["error"] == []
        assert c._produced_batches == [("b-1", "imported")]
