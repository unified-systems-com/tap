"""Tests for implementation claims (`spec-tap-requirement-traceability.md`).

Every detector is exercised against a synthetic tree carrying a *deliberate* violation it
must reject. A guard that cannot fail is a false green — pytest's own `--strict`
deprecation silently reverted for two major versions for exactly this reason.

This module is listed in `spec_trace._CONVENTION_MODULES`, so the claim strings it builds
as fixtures are never mistaken for real claims against the live tree.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.implements_uniqueness import undeclared_duplicates
from tap.spec_trace import (
    CLAIM_ROLES,
    CODE_HASH_PLACEHOLDER,
    Claim,
    code_hash_of,
    collect_claims,
    drifted_claims,
    duplicate_claim_groups,
    invalid_claims,
    load_corpus,
    malformed_claims,
    python_scan_roots,
    stale_claims,
)

_TOKEN = "TAP-" + "IMPLEMENTS"

_SPEC = """\
### Alpha
----
RID: `req-example-alpha`
Status: `Implemented`

Alpha derives a fact exactly once.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | --- | --- |
| req-example-alpha-1 | First | Implemented | A testable condition. |
"""


def _tree(tmp_path: Path, modules: dict[str, str]) -> Path:
    (tmp_path / "specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "specs" / "spec-example.md").write_text(_SPEC, encoding="utf-8")
    pkg = tmp_path / "tap"
    pkg.mkdir(parents=True, exist_ok=True)
    for name, source in modules.items():
        (pkg / name).write_text(source, encoding="utf-8")
    return tmp_path


def _hash_of(tree: Path, rid: str = "req-example-alpha") -> str:
    return load_corpus(tree).requirements[rid].content_hash


def _module(claim: str, body: str = "") -> str:
    return f'def thing():\n    """Does a thing.\n\n    {claim}\n    """\n{body}'


def _thing_code_hash(source: str) -> str:
    """The claimed scope's code hash, computed the way the collector does.

    Docstrings are excluded from the digest, so the hash is independent of the claim
    text that will sit inside it — which is what lets a test (and the mint flow) stamp
    a hash into a docstring without changing the thing being hashed.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "thing":
            return code_hash_of(node)
    raise AssertionError("fixture module has no `thing`")


def _stamped(tree: Path, body: str = "") -> str:
    """A module whose claim carries the current spec hash AND its real code hash."""
    source = _module(f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine.", body)
    return source.replace(CODE_HASH_PLACEHOLDER, _thing_code_hash(source))


# --- shape ---------------------------------------------------------------------------


def test_well_formed_claim_is_parsed(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — the one place."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")

    claims, malformed = collect_claims(tree, python_scan_roots(tree))
    assert malformed == []
    assert len(claims) == 1
    assert (claims[0].rid, claims[0].role, claims[0].qualname) == (
        "req-example-alpha",
        "derivation",
        "thing",
    )
    assert claims[0].unstamped
    assert claims[0].code_hash  # the collector computed the scope's current digest


def test_near_miss_fails_closed(tmp_path: Path) -> None:
    """A misspelled tag must FAIL, not be skipped — the clippy `SAFTEY:` hole."""
    tree = _tree(tmp_path, {"a.py": _module("TAP-IMPLEMENT: req-example-alpha (derivation)")})
    offenders = malformed_claims(tree)
    assert len(offenders) == 1
    assert "TAP-IMPLEMENT:" in offenders[0].text


def test_claim_missing_its_hash_is_malformed(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": _module(f"{_TOKEN}: req-example-alpha (derivation) — no hash.")})
    assert len(malformed_claims(tree)) == 1


def test_single_hash_claim_is_malformed(tmp_path: Path) -> None:
    """The pre-code-hash grammar fails closed — a claim without a code fingerprint asserts
    nothing about the code it sits on, and silently accepting it would fail open."""
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)} (derivation) — old format."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")
    assert len(malformed_claims(tree)) == 1


# --- integrity -----------------------------------------------------------------------


def test_claim_on_unknown_requirement_is_invalid(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-absent-thing@{'0' * 12}/{CODE_HASH_PLACEHOLDER} (derivation) — nope."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")

    problems = invalid_claims(tree)
    assert len(problems) == 1
    assert "does not exist" in problems[0][1]


def test_claim_with_unknown_role_is_invalid(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (invented) — bad role."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")

    problems = invalid_claims(tree)
    assert len(problems) == 1
    assert "not one of" in problems[0][1]


def test_role_vocabulary_is_closed() -> None:
    assert CLAIM_ROLES == {"derivation", "enforcement", "surface"}


# --- uniqueness ----------------------------------------------------------------------


def test_duplicate_claim_across_modules_is_detected(tmp_path: Path) -> None:
    """One requirement-and-role, two modules — the anti-pattern this convention targets."""
    tree = _tree(tmp_path, {"a.py": "", "b.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine."
    for name in ("a.py", "b.py"):
        (tree / "tap" / name).write_text(_module(claim), encoding="utf-8")

    duplicates = duplicate_claim_groups(tree)
    assert list(duplicates) == [("req-example-alpha", "derivation")]
    assert len(duplicates[("req-example-alpha", "derivation")]) == 2


def test_same_requirement_different_roles_is_not_a_duplicate(tmp_path: Path) -> None:
    """A requirement realized at two layers is legitimate — that is why roles exist."""
    tree = _tree(tmp_path, {"a.py": "", "b.py": ""})
    digest = _hash_of(tree)
    (tree / "tap" / "a.py").write_text(
        _module(f"{_TOKEN}: req-example-alpha@{digest}/{CODE_HASH_PLACEHOLDER} (derivation) — computes it."),
        encoding="utf-8",
    )
    (tree / "tap" / "b.py").write_text(
        _module(f"{_TOKEN}: req-example-alpha@{digest}/{CODE_HASH_PLACEHOLDER} (enforcement) — guards it."),
        encoding="utf-8",
    )
    assert duplicate_claim_groups(tree) == {}


def test_repeated_claim_within_one_module_is_not_a_duplicate(tmp_path: Path) -> None:
    """Conditional definitions declare the same claim twice in one file, legitimately."""
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine."
    (tree / "tap" / "a.py").write_text(_module(claim) + "\n\n" + _module(claim), encoding="utf-8")
    assert duplicate_claim_groups(tree) == {}


def _claim_at(tmp_path: Path, module: str) -> Claim:
    return Claim(
        rid="req-example-alpha",
        recorded_hash="0" * 12,
        recorded_code_hash=CODE_HASH_PLACEHOLDER,
        role="derivation",
        qualname="thing",
        path=tmp_path / module,
        lineno=1,
        code_hash="1" * 12,
    )


def test_duplicate_is_permitted_when_both_sites_share_a_known_dupe_group(tmp_path: Path) -> None:
    duplicates = {("req-example-alpha", "derivation"): [_claim_at(tmp_path, "a.py"), _claim_at(tmp_path, "b.py")]}
    tagged = {"a.py": {"shared-group"}, "b.py": {"shared-group"}}
    assert undeclared_duplicates(duplicates, tagged, tmp_path) == []


def test_duplicate_still_fails_when_the_groups_differ(tmp_path: Path) -> None:
    """Two unrelated exemptions that happen to coincide are not a declaration about this pair."""
    duplicates = {("req-example-alpha", "derivation"): [_claim_at(tmp_path, "a.py"), _claim_at(tmp_path, "b.py")]}
    tagged = {"a.py": {"group-one"}, "b.py": {"group-two"}}
    assert len(undeclared_duplicates(duplicates, tagged, tmp_path)) == 1


def test_duplicate_fails_when_only_one_site_is_tagged(tmp_path: Path) -> None:
    duplicates = {("req-example-alpha", "derivation"): [_claim_at(tmp_path, "a.py"), _claim_at(tmp_path, "b.py")]}
    assert len(undeclared_duplicates(duplicates, {"a.py": {"shared-group"}}, tmp_path)) == 1


# --- staleness -----------------------------------------------------------------------


def test_stale_claim_is_detected_after_the_requirement_changes(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")
    assert stale_claims(tree) == []

    spec = tree / "specs" / "spec-example.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "Alpha derives a fact exactly once.", "Alpha derives a materially different fact."
        ),
        encoding="utf-8",
    )

    stale = stale_claims(tree)
    assert len(stale) == 1
    assert stale[0][1] == _hash_of(tree)  # the expected hash is the requirement's new one


def test_status_change_does_not_stale_a_claim(tmp_path: Path) -> None:
    """Status is derived and moves on its own lifecycle — it must not churn every claim."""
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")

    spec = tree / "specs" / "spec-example.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace("Status: `Implemented`", "Status: `Verified`"),
        encoding="utf-8",
    )
    assert stale_claims(tree) == []


def test_claim_on_missing_requirement_is_not_double_reported(tmp_path: Path) -> None:
    """A dangling claim is an integrity finding; reporting it as stale too would double-count."""
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-absent-thing@{'0' * 12}/{CODE_HASH_PLACEHOLDER} (derivation) — nope."
    (tree / "tap" / "a.py").write_text(_module(claim), encoding="utf-8")

    assert stale_claims(tree) == []
    assert len(invalid_claims(tree)) == 1


# --- code staleness (`req-tap-traceability-code-staleness`) --------------------------


def test_stamped_claim_on_unchanged_code_is_not_drifted(tmp_path: Path) -> None:
    tree = _tree(tmp_path, {"a.py": ""})
    (tree / "tap" / "a.py").write_text(_stamped(tree, body="    return 1\n"), encoding="utf-8")
    assert drifted_claims(tree) == []


def test_unstamped_claim_is_drifted(tmp_path: Path) -> None:
    """The mint placeholder must fail closed — otherwise the --resync step is forgettable."""
    tree = _tree(tmp_path, {"a.py": ""})
    claim = f"{_TOKEN}: req-example-alpha@{_hash_of(tree)}/{CODE_HASH_PLACEHOLDER} (derivation) — mine."
    (tree / "tap" / "a.py").write_text(_module(claim, body="    return 1\n"), encoding="utf-8")

    drifted = drifted_claims(tree)
    assert len(drifted) == 1
    assert drifted[0].unstamped


def test_semantic_edit_drifts_the_claim(tmp_path: Path) -> None:
    """Rewriting the claimed scope orphans the claim — the code end of the Doorstop model."""
    tree = _tree(tmp_path, {"a.py": ""})
    module = tree / "tap" / "a.py"
    module.write_text(_stamped(tree, body="    return 1\n"), encoding="utf-8")
    assert drifted_claims(tree) == []

    module.write_text(module.read_text(encoding="utf-8").replace("return 1", "return 2"), encoding="utf-8")
    drifted = drifted_claims(tree)
    assert len(drifted) == 1
    assert not drifted[0].unstamped
    assert drifted[0].recorded_code_hash != drifted[0].code_hash


def test_cosmetic_edits_do_not_drift_the_claim(tmp_path: Path) -> None:
    """Comments, blank lines and docstring edits are outside the digest by construction."""
    tree = _tree(tmp_path, {"a.py": ""})
    module = tree / "tap" / "a.py"
    module.write_text(_stamped(tree, body="    return 1\n"), encoding="utf-8")

    text = module.read_text(encoding="utf-8")
    text = text.replace("    return 1", "    # a new comment\n\n    return 1")
    text = text.replace("Does a thing.", "Does a thing, reworded at length.")
    module.write_text(text, encoding="utf-8")
    assert drifted_claims(tree) == []


def test_restamping_the_claim_does_not_change_the_hash(tmp_path: Path) -> None:
    """The fixpoint property: the claim line lives in the docstring, and docstrings are
    excluded from the digest — so stamping a hash never invalidates the hash being stamped."""
    source_placeholder = _module(
        f"{_TOKEN}: req-example-alpha@{'0' * 12}/{CODE_HASH_PLACEHOLDER} (derivation) — mine.",
        body="    return 1\n",
    )
    source_stamped = source_placeholder.replace(CODE_HASH_PLACEHOLDER, "a" * 12)
    assert _thing_code_hash(source_placeholder) == _thing_code_hash(source_stamped)
