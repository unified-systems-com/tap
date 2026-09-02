"""Unit tests for tap.install_credentials (req-tap-plugin-arch-source-secret-7).

The install half of boot resolves its source credentials INSIDE the install loop, one
entry at a time. This module front-runs that: enumerate every credential the record's
enabled entries declare, check them offline against the store, and report all of them in
one verdict before anything is installed or cloned. These tests hold that contract —
enumerate-all, enabled-scoped, both resolver rules, and never a value in the message.

Pure stdlib + tmp_path; no network, no Django, no venv assumptions (the module itself runs
under bare python3 during spawn, so its tests must not need more than it does).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tap.git_invocation import GITHUB_PAT_KIND, SOURCE_SECRET_SCOPE
from tap.install_credentials import (
    EXIT_UNSATISFIED,
    InstallCredentialError,
    check,
    check_or_raise,
    declared_credentials,
    entries_of,
    main,
    unsatisfied_message,
)

TOKEN = "github_pat_EXAMPLE_NOT_A_REAL_TOKEN"  # noqa: S105 — fixture value, never a live credential


def _git(slug: str, credential: str | None = "github-plugins-ro", **over: Any) -> dict[str, Any]:
    source: dict[str, Any] = {
        "type": "git",
        "url": f"https://github.com/unified-systems-com/tap-plugin-{slug.replace('_', '-')}",
        "rev": "v0.1.0",
    }
    if credential is not None:
        source["credential"] = credential
    entry = {"slug": slug, "enabled": True, "source": source}
    entry.update(over)
    return entry


def _record(*plugins: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "install": {"plugins": list(plugins)}}


def _store(tmp_path: Path, *keys: str, **over: Any) -> Path:
    """A secrets store holding a well-formed source envelope for each key."""
    root = tmp_path / "secrets"
    (root / "tap_plugins").mkdir(parents=True, exist_ok=True)
    for key in keys:
        envelope = {
            "scope": SOURCE_SECRET_SCOPE,
            "key": key,
            "kind": GITHUB_PAT_KIND,
            "description": "read-only PAT for the plugin repos",
            "data": {"token": TOKEN},
        }
        envelope.update(over)
        (root / "tap_plugins" / f"{key}.secret.json").write_text(json.dumps(envelope), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# Enumeration — what the record declares
# ---------------------------------------------------------------------------


def test_public_git_source_declares_nothing() -> None:
    """No `credential` key ⇒ public ⇒ nothing required (req-tap-plugin-arch-source-secret-5)."""
    assert declared_credentials(entries_of(_record(_git("grid_fixtures", credential=None)))) == []


def test_editable_and_path_sources_never_declare() -> None:
    entries = [
        {"slug": "a", "enabled": True, "source": {"type": "editable", "path": "plugins/a"}},
        {"slug": "b", "enabled": True, "source": {"type": "path", "path": "/opt/b"}},
    ]
    assert declared_credentials(entries) == []


def test_disabled_entry_is_not_required() -> None:
    """A disabled entry is never installed, so its credential must not block a boot —
    the same enabled-scoping the population preflight uses (req-boot-required-secrets-5)."""
    entries = entries_of(_record(_git("a", credential="never-provisioned") | {"enabled": False}))
    assert declared_credentials(entries) == []


def test_one_credential_collects_every_consuming_slug() -> None:
    """Shared keys collapse to one row carrying all its consumers — the report says
    which plugins are blocked, which the per-entry error never could."""
    declared = declared_credentials(entries_of(_record(_git("grid_fixtures"), _git("gryphon_playground"))))
    assert len(declared) == 1
    assert declared[0].key == "github-plugins-ro"
    assert declared[0].slugs == ("grid_fixtures", "gryphon_playground")
    assert len(declared[0].urls) == 2


def test_distinct_credentials_stay_distinct_in_record_order() -> None:
    declared = declared_credentials(entries_of(_record(_git("a", "org-a-ro"), _git("b", "org-b-ro"))))
    assert [d.key for d in declared] == ["org-a-ro", "org-b-ro"]


# ---------------------------------------------------------------------------
# Checking — can this host satisfy them
# ---------------------------------------------------------------------------


def test_satisfied_store_is_clean(tmp_path: Path) -> None:
    entries = entries_of(_record(_git("grid_fixtures"), _git("gryphon_playground")))
    assert check(entries, _store(tmp_path, "github-plugins-ro")) == []


def test_missing_credential_is_reported_with_both_lookup_rules(tmp_path: Path) -> None:
    root = _store(tmp_path)  # store exists, envelope does not
    problems = check(entries_of(_record(_git("grid_fixtures"))), root)
    assert [p.problem for p in problems] == ["missing"]
    assert "github-plugins-ro.secret.json" in problems[0].detail
    assert SOURCE_SECRET_SCOPE in problems[0].detail


def test_absent_store_reports_every_declared_credential(tmp_path: Path) -> None:
    """No store at all is a provisioning gap for ALL of them, not a mystery on the first."""
    problems = check(entries_of(_record(_git("a", "org-a-ro"), _git("b", "org-b-ro"))), tmp_path / "nope")
    assert [p.declared.key for p in problems] == ["org-a-ro", "org-b-ro"]


def test_enumerate_all_reports_every_unsatisfiable_credential_at_once(tmp_path: Path) -> None:
    """THE contract: three bad credentials produce three findings in one verdict. The old
    per-entry resolve surfaced only the first, so each fix bought one more failed spawn."""
    root = _store(tmp_path, "org-b-ro")
    entries = entries_of(_record(_git("a", "org-a-ro"), _git("b", "org-b-ro"), _git("c", "org-c-ro")))
    assert [p.declared.key for p in check(entries, root)] == ["org-a-ro", "org-c-ro"]


def test_wrong_kind_is_credential_confusion_and_fails(tmp_path: Path) -> None:
    """Material for service A must never be handed to service B — the kind check the
    resolvers already make, made visible before the install rather than during it."""
    root = _store(tmp_path, "github-plugins-ro", kind="aws_iam_user")
    problems = check(entries_of(_record(_git("a"))), root)
    assert [p.problem for p in problems] == ["kind"]
    assert "aws_iam_user" in problems[0].detail


def test_empty_token_fails(tmp_path: Path) -> None:
    root = _store(tmp_path, "github-plugins-ro", data={"token": ""})
    assert [p.problem for p in check(entries_of(_record(_git("a"))), root)] == ["token"]


def test_unreadable_envelope_is_named_not_swallowed(tmp_path: Path) -> None:
    root = _store(tmp_path)
    (root / "tap_plugins" / "github-plugins-ro.secret.json").write_text("{not json", encoding="utf-8")
    problems = check(entries_of(_record(_git("a"))), root)
    assert [p.problem for p in problems] == ["unreadable"]


def test_a_corrupt_unrelated_envelope_is_not_this_credentials_problem(tmp_path: Path) -> None:
    root = _store(tmp_path, "github-plugins-ro")
    (root / "somebody-elses.secret.json").write_text("{not json", encoding="utf-8")
    assert check(entries_of(_record(_git("a"))), root) == []


# --- the two-resolver seam -------------------------------------------------


def test_right_filename_wrong_identity_is_caught(tmp_path: Path) -> None:
    """The trap this check exists for: the host resolver finds it by FILENAME and the
    spawn sails on, then pre-boot resolves by scope/key in-container and dies minutes
    later. Both rules are checked here so the divergence is a host-side verdict."""
    root = _store(tmp_path, "github-plugins-ro", scope="github_core")
    problems = check(entries_of(_record(_git("a"))), root)
    assert [p.problem for p in problems] == ["identity"]
    assert "github_core" in problems[0].detail
    assert "pre-boot would fail after the host-side step succeeded" in problems[0].detail


def test_right_identity_wrong_filename_is_caught(tmp_path: Path) -> None:
    """The mirror image: the container would resolve it, spawn's own staging steps would not."""
    root = _store(tmp_path)
    (root / "tap_plugins" / "misnamed.secret.json").write_text(
        json.dumps(
            {
                "scope": SOURCE_SECRET_SCOPE,
                "key": "github-plugins-ro",
                "kind": GITHUB_PAT_KIND,
                "description": "d",
                "data": {"token": TOKEN},
            }
        ),
        encoding="utf-8",
    )
    problems = check(entries_of(_record(_git("a"))), root)
    assert [p.problem for p in problems] == ["filename"]


def test_example_templates_are_never_treated_as_credentials(tmp_path: Path) -> None:
    """A committed `*.secret.example.json` is a placeholder, never a credential
    (tap.secret_naming) — satisfying a preflight with one would be a trap."""
    root = _store(tmp_path)
    (root / "tap_plugins" / "github-plugins-ro.secret.example.json").write_text(
        json.dumps(
            {
                "scope": SOURCE_SECRET_SCOPE,
                "key": "github-plugins-ro",
                "kind": GITHUB_PAT_KIND,
                "description": "template",
                "data": {"token": "REPLACE_ME"},
            }
        ),
        encoding="utf-8",
    )
    assert [p.problem for p in check(entries_of(_record(_git("a"))), root)] == ["missing"]


def test_two_files_each_satisfying_one_rule_is_a_split_not_a_pass(tmp_path: Path) -> None:
    """The hole an AI reviewer found in this check on the day it was written.

    `by_filename` and `by_identity` can BOTH be non-empty and yet share no file: one
    envelope carries the right filename under the wrong scope, another carries the right
    scope/key under a different filename. Each resolver then finds something — a DIFFERENT
    something — so the host feeds git one envelope and pre-boot feeds it another. Reporting
    that as satisfiable is worse than either rule failing: it is credential confusion no
    consumer reports.
    """
    root = _store(tmp_path)
    # right filename, wrong scope — the host-side resolver matches this one
    (root / "tap_plugins" / "github-plugins-ro.secret.json").write_text(
        json.dumps(
            {
                "scope": "github_core",
                "key": "collector",
                "kind": GITHUB_PAT_KIND,
                "description": "d",
                "data": {"token": TOKEN},
            }
        ),
        encoding="utf-8",
    )
    # right scope+key, different filename — the container resolves THIS one
    (root / "tap_plugins" / "elsewhere.secret.json").write_text(
        json.dumps(
            {
                "scope": SOURCE_SECRET_SCOPE,
                "key": "github-plugins-ro",
                "kind": GITHUB_PAT_KIND,
                "description": "d",
                "data": {"token": TOKEN},
            }
        ),
        encoding="utf-8",
    )

    problems = check(entries_of(_record(_git("a"))), root)

    assert [p.problem for p in problems] == ["split"]
    assert "github-plugins-ro.secret.json" in problems[0].detail
    assert "elsewhere.secret.json" in problems[0].detail


def test_kind_and_token_are_checked_on_the_file_satisfying_both_rules(tmp_path: Path) -> None:
    """A decoy that satisfies only the filename rule must not stand in for the real one."""
    root = _store(tmp_path, "github-plugins-ro")  # correct envelope, correct name
    (root / "decoy").mkdir()
    (root / "decoy" / "github-plugins-ro.secret.json").write_text(
        json.dumps({"scope": "somewhere_else", "key": "x", "kind": "aws_iam_user", "description": "d", "data": {}}),
        encoding="utf-8",
    )
    # Both rules are satisfiable by the real envelope, so the decoy's wrong kind must not
    # be what gets reported — and the pair must not be read as agreement either.
    assert [p.problem for p in check(entries_of(_record(_git("a"))), root)] == ["split"]


# ---------------------------------------------------------------------------
# The message — what the operator is told
# ---------------------------------------------------------------------------


def test_message_never_contains_the_token(tmp_path: Path) -> None:
    """Refs, kinds, paths and problems only — the population preflight's rule
    (req-boot-required-secrets-5), for the same reason."""
    root = _store(tmp_path, "github-plugins-ro", kind="wrong_kind")
    problems = check(entries_of(_record(_git("a"))), root)
    message = unsatisfied_message(problems, profile_id="playground", secrets_root=root)
    assert TOKEN not in message


def test_message_names_consumers_identity_and_both_roads(tmp_path: Path) -> None:
    """The bare resolver error named only the key. This must also say who needs it, what
    envelope to write, and that a PUBLIC repo needs no credential at all — the road that
    was missed when a record outlived its repos' privacy."""
    problems = check(entries_of(_record(_git("grid_fixtures"), _git("gryphon_playground"))), tmp_path / "nope")
    message = unsatisfied_message(problems, profile_id="playground", secrets_root=tmp_path / "nope")
    assert "grid_fixtures, gryphon_playground" in message
    assert SOURCE_SECRET_SCOPE in message
    assert "/provision-secrets" in message
    assert "DROP the `credential` key" in message
    assert "git ls-remote" in message


def test_a_url_with_embedded_userinfo_is_redacted_from_the_message(tmp_path: Path) -> None:
    """A record's `url` is authored elsewhere and can arrive by pointer fetch, so a
    credential someone else embedded must not be republished by OUR error message."""
    entry = _git("a")
    entry["source"]["url"] = "https://someone:ghp_REALLOOKINGTOKEN@github.com/org/repo"
    problems = check(entries_of(_record(entry)), tmp_path / "nope")
    message = unsatisfied_message(problems, profile_id="p", secrets_root=tmp_path / "nope")
    assert "ghp_REALLOOKINGTOKEN" not in message
    assert "someone" not in message
    assert "https://github.com/org/repo" in message


def test_check_or_raise_is_quiet_when_satisfied(tmp_path: Path) -> None:
    check_or_raise(entries_of(_record(_git("a"))), _store(tmp_path, "github-plugins-ro"), profile_id="p")


def test_check_or_raise_raises_the_full_verdict(tmp_path: Path) -> None:
    with pytest.raises(InstallCredentialError) as excinfo:
        check_or_raise(entries_of(_record(_git("a"))), _store(tmp_path), profile_id="playground")
    assert "playground" in str(excinfo.value)


# ---------------------------------------------------------------------------
# CLI — the seam spawn calls (req-tap-plugin-arch-source-secret-8)
# ---------------------------------------------------------------------------


def _write_record(boot_dir: Path, record_id: str, record: dict[str, Any]) -> None:
    boot_dir.mkdir(parents=True, exist_ok=True)
    (boot_dir / f"{record_id}.boot.json").write_text(json.dumps(record), encoding="utf-8")


def test_cli_clean_record_exits_zero(tmp_path: Path) -> None:
    boot_dir = tmp_path / "boot"
    _write_record(boot_dir, "playground", _record(_git("a")))
    argv = [
        "--profile",
        "playground",
        "--boot-dir",
        str(boot_dir),
        "--secrets-root",
        str(_store(tmp_path, "github-plugins-ro")),
    ]
    assert main(argv) == 0


def test_cli_unsatisfiable_exits_with_its_own_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A distinct exit status so spawn can tell a provisioning gap from a broken argv."""
    boot_dir = tmp_path / "boot"
    _write_record(boot_dir, "playground", _record(_git("a")))
    rc = main(["--profile", "playground", "--boot-dir", str(boot_dir), "--secrets-root", str(_store(tmp_path))])
    assert rc == EXIT_UNSATISFIED
    assert "cannot satisfy" in capsys.readouterr().err


def test_cli_record_path_form(tmp_path: Path) -> None:
    boot_dir = tmp_path / "boot"
    _write_record(boot_dir, "playground", _record(_git("a", credential=None)))
    assert main(["--record", str(boot_dir / "playground.boot.json")]) == 0


def test_cli_requires_exactly_one_addressing_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    assert "exactly one" in capsys.readouterr().err


def test_cli_unreadable_record_is_a_usage_error_not_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 1, not EXIT_UNSATISFIED — a broken record is not a provisioning gap."""
    assert main(["--record", str(tmp_path / "absent.boot.json")]) == 1
    assert "cannot read boot record" in capsys.readouterr().err
