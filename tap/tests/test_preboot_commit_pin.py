"""Pre-boot installs git plugins by the pinned commit and reports tag drift (tap#512, epic tap#493).

Rulings (George, 2026-09-16/17): the commit decides what installs; a moved or missing tag is a
security ``AppFlaw``, a git source without ``commit`` a security ``InstanceFlaw`` — both
observe-continue, boot proceeds; an unreachable forge is not observable, neither verdict.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from tap import preboot
from tap.git_pin import TAG_MATCHES, TAG_MISSING, TAG_MOVED, TAG_NOT_OBSERVABLE, TagCheck

URL = "https://forge.example/org/tap-plugin-widget"
COMMIT = "3356301e676094523943f2bbb055be501a6b42d6"
OTHER = "7f08d0780d7468590507df2a5562fe730d76e8c8"


def _entry(**source: Any) -> dict[str, Any]:
    return {"slug": "widget", "enabled": True, "source": {"type": "git", "url": URL, "rev": "v1.0.0", **source}}


class _Dist:
    def __init__(self, commit_id: str) -> None:
        self._direct_url = json.dumps(
            {"url": URL, "vcs_info": {"vcs": "git", "commit_id": commit_id, "requested_revision": "v1.0.0"}}
        )

    def read_text(self, name: str) -> str | None:
        return self._direct_url if name == "direct_url.json" else None


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def records():
    handler = _Capture()
    preboot.logger.addHandler(handler)
    previous = preboot.logger.level
    preboot.logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        preboot.logger.removeHandler(handler)
        preboot.logger.setLevel(previous)


def _flaws(records: list[logging.LogRecord]) -> list[dict[str, Any]]:
    return [r.message_data for r in records if getattr(r, "message_code", None) == "FLAW"]  # type: ignore[attr-defined]


@pytest.mark.spec("req-boot-bootstrap-install-commit-pin")
class TestInstallByCommit:
    def test_the_install_argv_names_the_commit_not_the_tag(self) -> None:
        args = preboot._uv_install_args(_entry(commit=COMMIT))
        assert args[-1] == f"git+{URL}@{COMMIT}"

    def test_an_unpinned_source_still_installs_by_rev(self) -> None:
        assert preboot._uv_install_args(_entry())[-1] == f"git+{URL}@v1.0.0"

    def test_installed_at_the_pinned_commit_is_satisfied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """POSITIVE CONTROL for the idempotency bug: against the old `commit_id == rev`
        comparison this is False — a tag never equals a commit id, so every boot reinstalled."""
        monkeypatch.setattr(preboot, "_installed_plugin_distribution", lambda slug: _Dist(COMMIT))
        assert preboot._is_satisfied(_entry(commit=COMMIT)) is True

    def test_installed_at_another_commit_is_not_satisfied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(preboot, "_installed_plugin_distribution", lambda slug: _Dist(OTHER))
        assert preboot._is_satisfied(_entry(commit=COMMIT)) is False

    def test_a_reboot_at_the_pinned_commit_runs_no_install(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setattr(preboot, "_secrets_root", lambda: tmp_path / "absent")
        monkeypatch.setattr(preboot, "_installed_plugin_distribution", lambda slug: _Dist(COMMIT))
        monkeypatch.setattr(preboot, "check_pin", lambda *a, **k: TagCheck(TAG_MATCHES, observed=COMMIT))
        monkeypatch.setattr(preboot, "_run_install", lambda *a, **k: pytest.fail("reboot must be a no-op"))
        preboot._install_plugins([_entry(commit=COMMIT)], "someprofile")

    @pytest.mark.parametrize("bad", [COMMIT.upper(), COMMIT[:12], "v1.0.0", 7])
    def test_a_malformed_commit_aborts_before_anything_runs(self, bad: object) -> None:
        with pytest.raises(preboot.PrebootError, match=r"source\.commit"):
            preboot._install_plugin_specs({"install": {"plugins": [_entry(commit=bad)]}})


@pytest.mark.spec("req-boot-bootstrap-install-commit-pin")
class TestTagDriftIsReportedNotBlocking:
    def _check(self, monkeypatch: pytest.MonkeyPatch, result: TagCheck, entry: dict[str, Any]) -> None:
        monkeypatch.setattr(preboot, "check_pin", lambda *a, **k: result)
        preboot._check_git_pin(entry, None, {})

    @pytest.mark.parametrize("state", [TAG_MOVED, TAG_MISSING])
    def test_moved_or_missing_tag_is_a_security_app_flaw(
        self, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord], state: str
    ) -> None:
        self._check(
            monkeypatch,
            TagCheck(state, observed=OTHER if state == TAG_MOVED else None, detail="d"),
            _entry(commit=COMMIT),
        )
        (flaw,) = _flaws(records)
        assert flaw["flaw_class"] == "app"
        assert flaw["flaw_tags"] == ["security"]
        assert flaw["handling"] == "observe_continue"
        assert flaw["context"]["pinned_commit"] == COMMIT
        assert flaw["context"]["tag_state"] == state

    def test_no_commit_is_a_security_instance_flaw_and_asks_no_forge(
        self, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
    ) -> None:
        monkeypatch.setattr(preboot, "check_pin", lambda *a, **k: pytest.fail("nothing to compare against"))
        preboot._check_git_pin(_entry(), None, {})
        (flaw,) = _flaws(records)
        assert (flaw["flaw_class"], flaw["flaw_tags"], flaw["handling"]) == (
            "instance",
            ["security"],
            "observe_continue",
        )

    def test_a_matching_tag_emits_no_flaw(
        self, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
    ) -> None:
        self._check(monkeypatch, TagCheck(TAG_MATCHES, observed=COMMIT), _entry(commit=COMMIT))
        assert _flaws(records) == []

    def test_unobservable_is_a_warning_and_neither_verdict(
        self, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
    ) -> None:
        self._check(monkeypatch, TagCheck(TAG_NOT_OBSERVABLE, detail="offline"), _entry(commit=COMMIT))
        assert _flaws(records) == []
        warnings = [r for r in records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "could not verify" in warnings[0].getMessage()

    def test_a_moved_tag_still_installs_the_pinned_commit(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setattr(preboot, "_secrets_root", lambda: tmp_path / "absent")
        monkeypatch.setattr(preboot, "_is_satisfied", lambda entry: False)
        monkeypatch.setattr(preboot, "check_pin", lambda *a, **k: TagCheck(TAG_MOVED, observed=OTHER, detail="d"))
        ran: list[str] = []

        class _Ok:
            returncode = 0
            stderr = ""

        def _record(args: list[str], cred: object) -> _Ok:
            ran.append(args[-1])
            return _Ok()

        monkeypatch.setattr(preboot, "_run_install", _record)
        preboot._install_plugins([_entry(commit=COMMIT)], "someprofile")
        assert ran == [f"git+{URL}@{COMMIT}"]

    def test_an_unreachable_forge_costs_one_timeout_per_host_not_per_plugin(
        self, monkeypatch: pytest.MonkeyPatch, records: list[logging.LogRecord]
    ) -> None:
        calls: list[str] = []

        def offline(url: str, *a: Any, **k: Any) -> TagCheck:
            calls.append(url)
            return TagCheck(TAG_NOT_OBSERVABLE, detail="timed out")

        monkeypatch.setattr(preboot, "check_pin", offline)
        unreachable: dict[str, str] = {}
        other_forge = "https://elsewhere.example/org/tap-plugin-other"
        for entry in (_entry(commit=COMMIT), _entry(commit=COMMIT), _entry(url=other_forge, commit=COMMIT)):
            preboot._check_git_pin(entry, None, unreachable)
        assert calls == [URL, other_forge]
        assert _flaws(records) == []
        assert len([r for r in records if r.levelno == logging.WARNING]) == 3
