"""The session-author scope (req-dev-multisession-session-author-scope).

`scripts/pr_session_identity.py` decides whether a pull request's AUTHENTICATED author is one of
the maintainer's session accounts. Three checks (`check-pr-title`, `check-issue-link`,
`check-pr-opened-by`) enforce session conventions only for those accounts, so an outside
contributor never meets them. These tests pin the list's contract and the three-way verdict:
SESSION, OUTSIDE, and UNKNOWN, which callers enforce rather than exempt.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import jsonschema
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIST = REPO_ROOT / "tap" / "tap.pr-session-authors.json"
SCHEMA = REPO_ROOT / "tap" / "schemas" / "pr-session-authors.schema.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr_session_identity", REPO_ROOT / "scripts" / "pr_session_identity.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["pr_session_identity"] = module
    spec.loader.exec_module(module)
    return module


ident = _module()


@pytest.mark.spec("req-dev-multisession-session-author-scope-1")
def test_the_list_validates_against_its_schema_and_the_stdlib_reader_agrees() -> None:
    data = json.loads(LIST.read_text(encoding="utf-8"))
    jsonschema.validate(data, json.loads(SCHEMA.read_text(encoding="utf-8")))
    loaded = ident.load_session_authors(LIST)
    assert loaded == {entry["id"]: entry["login"] for entry in data["authors"]}
    # Scoped initially to the one working account, by ruling (2026-10-09); criticalsec is absent.
    assert loaded == {286052: "notgeorge"}


@pytest.mark.spec("req-dev-multisession-session-author-scope-1")
@pytest.mark.parametrize(
    ("author_id", "author_type", "verdict"),
    [
        ("286052", "User", "session"),
        ("286052", "Bot", "outside"),
        ("25269251", "User", "outside"),
        ("583231", "User", "outside"),
        ("315114127", "Bot", "outside"),
        ("", "User", "unknown"),
        ("not-a-number", "User", "unknown"),
        ("0", "User", "unknown"),
    ],
)
def test_classification_is_by_authenticated_id_and_type(author_id: str, author_type: str, verdict: str) -> None:
    got, _reason = ident.classify(author_id, author_type, "whoever", ident.load_session_authors(LIST))
    assert got == verdict


@pytest.mark.spec("req-dev-multisession-session-author-scope-1")
def test_a_login_alone_never_makes_a_session_account() -> None:
    """Logins are mutable text: notgeorge's login with another id is an outsider."""
    got, _ = ident.classify("424242", "User", "notgeorge", ident.load_session_authors(LIST))
    assert got == "outside"


@pytest.mark.spec("req-dev-multisession-session-author-scope-1")
def test_no_identity_at_all_is_a_local_run_and_enforces() -> None:
    assert ident.decide([])[0] == "session"


@pytest.mark.spec("req-dev-multisession-session-author-scope-1")
@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps({"authors": []}),
        json.dumps({"authors": [{"login": "x", "id": "286052", "type": "User"}]}),
        json.dumps({"authors": [{"login": "x", "id": 286052, "type": "Bot"}]}),
        json.dumps({"authors": [{"login": "x", "id": 1, "type": "User"}, {"login": "y", "id": 1, "type": "User"}]}),
    ],
)
def test_a_malformed_list_fails_closed(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "authors.json"
    path.write_text(bad, encoding="utf-8")
    with pytest.raises(ident.SessionAuthorsError):
        ident.load_session_authors(path)
