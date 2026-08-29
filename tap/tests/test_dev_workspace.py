"""Unit tests for tap.dev_workspace (req-dev-workspace-spawn).

Pure-function coverage of the profile derivation: the slug is a selector into the base
profile's install list, and the git entry's url/rev/credential are the clone authority.
No network — the actual clone (clone_editable) is exercised by a separate host smoke.

The ``main()`` tests cover the spawn seam (req-dev-workspace-spawn-6/-7): the base
profile is resolved as ``<worktree>/boot/<id>.boot.json`` by id, with no
committed-vs-staged distinction — which is exactly what makes BOTH compositions work:
``--from`` + ``--dev-plugins`` (pointer record staged first) and ``--boot-file`` +
``--dev-plugins`` (local file staged under its basename id first); the derivation then
runs over the staged record either way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import tap.dev_workspace as dev_workspace
from tap.dev_workspace import DevWorkspaceError, derive_profile


def _profile(*plugins: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "description": "base", "install": {"plugins": list(plugins)}}


def _git(slug: str, rev: str = "v0.1.0") -> dict[str, Any]:
    return {
        "slug": slug,
        "enabled": True,
        "source": {
            "type": "git",
            "url": f"https://github.com/unified-systems-com/tap-plugin-{slug.replace('_', '-')}",
            "rev": rev,
            "credential": "github-plugins-ro",
        },
    }


def _editable(slug: str) -> dict[str, Any]:
    return {"slug": slug, "enabled": True, "source": {"type": "editable", "path": f"plugins/{slug}"}}


def test_flips_git_to_editable_and_returns_clone_spec() -> None:
    base = _profile(_git("compliance_core"), _git("fedramp_20x_ksi", rev="v0.2.0"))
    derived, specs = derive_profile(base, ["compliance_core"])

    # only the named slug is flipped
    by_slug = {p["slug"]: p for p in derived["install"]["plugins"]}
    assert by_slug["compliance_core"]["source"] == {"type": "editable", "path": "_dev-plugins/compliance_core"}
    assert by_slug["fedramp_20x_ksi"]["source"]["type"] == "git"

    assert len(specs) == 1
    spec = specs[0]
    assert spec.slug == "compliance_core"
    assert spec.url.endswith("tap-plugin-compliance-core")
    assert spec.rev == "v0.1.0"
    assert spec.credential == "github-plugins-ro"


def test_coupled_flips_both() -> None:
    base = _profile(_git("compliance_core"), _git("fedramp_20x_ksi"))
    derived, specs = derive_profile(base, ["compliance_core", "fedramp_20x_ksi"])
    assert {s.slug for s in specs} == {"compliance_core", "fedramp_20x_ksi"}
    assert all(p["source"]["type"] == "editable" for p in derived["install"]["plugins"])


def test_slug_not_in_profile_raises() -> None:
    base = _profile(_git("compliance_core"))
    with pytest.raises(DevWorkspaceError, match="not a plugin in the base profile"):
        derive_profile(base, ["nonexistent"])


def test_already_editable_is_left_as_is_and_not_cloned() -> None:
    base = _profile(_editable("grid_fixtures"))
    derived, specs = derive_profile(base, ["grid_fixtures"])
    assert specs == []  # nothing to clone
    assert derived["install"]["plugins"][0]["source"] == {"type": "editable", "path": "plugins/grid_fixtures"}


def test_non_git_non_editable_source_raises() -> None:
    base = _profile({"slug": "x", "source": {"type": "wheelhouse", "version": "0.1.0"}})
    with pytest.raises(DevWorkspaceError, match="expected 'git'"):
        derive_profile(base, ["x"])


def test_git_missing_rev_raises() -> None:
    base = _profile({"slug": "x", "source": {"type": "git", "url": "https://example/x"}})
    with pytest.raises(DevWorkspaceError, match="missing url/rev"):
        derive_profile(base, ["x"])


def test_does_not_mutate_the_input_profile() -> None:
    base = _profile(_git("compliance_core"))
    derive_profile(base, ["compliance_core"])
    # the original entry is untouched (deep copy)
    assert base["install"]["plugins"][0]["source"]["type"] == "git"


# ---------------------------------------------------------------------------
# main(): the spawn seam (req-dev-workspace-spawn-6)
# ---------------------------------------------------------------------------


def _stage_record(worktree: Path, record_id: str, profile: dict[str, Any]) -> Path:
    """Write *profile* into ``<worktree>/boot/<record_id>.boot.json`` — a staged,
    uncommitted record, exactly as spawn's --from stage-0 fetch leaves it."""
    boot_dir = worktree / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    path = boot_dir / f"{record_id}.boot.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    return path


def _store(worktree: Path, *keys: str) -> Path:
    """A secrets store satisfying *keys* — the precondition for any record whose git
    sources declare a credential (req-tap-plugin-arch-source-secret-7). Passed
    explicitly so these tests never depend on what is in the developer's ~/tap-secrets."""
    root = worktree / "secrets" / "tap_plugins"
    root.mkdir(parents=True, exist_ok=True)
    for key in keys:
        (root / f"{key}.secret.json").write_text(
            json.dumps(
                {
                    "scope": "tap_plugins.source",
                    "key": key,
                    "kind": "github_pat",
                    "description": "test PAT",
                    "data": {"token": "github_pat_EXAMPLE"},  # noqa: S106 — fixture value
                }
            ),
            encoding="utf-8",
        )
    return root.parent


def test_main_derives_over_a_staged_pointer_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A record staged into boot/ (never committed) is a valid base — the composition seam."""
    _stage_record(tmp_path, "samsite", _profile(_git("samsite", rev="v0.2.0"), _git("aws_core", rev="v0.4.0")))
    cloned: list[str] = []
    monkeypatch.setattr(dev_workspace, "clone_editable", lambda spec, worktree, root: cloned.append(spec.slug))

    rc = dev_workspace.main(
        [
            "--base-profile",
            "samsite",
            "--dev-plugins",
            "samsite",
            "--worktree",
            str(tmp_path),
            "--secrets-root",
            str(_store(tmp_path, "github-plugins-ro")),
        ]
    )

    assert rc == 0
    assert cloned == ["samsite"]
    derived_path = tmp_path / "boot" / "samsite__dev.boot.json"
    assert capsys.readouterr().out.strip() == str(derived_path)
    derived = json.loads(derived_path.read_text(encoding="utf-8"))
    by_slug = {p["slug"]: p for p in derived["install"]["plugins"]}
    assert by_slug["samsite"]["source"] == {"type": "editable", "path": "_dev-plugins/samsite"}
    assert by_slug["aws_core"]["source"]["type"] == "git"
    assert by_slug["aws_core"]["source"]["rev"] == "v0.4.0"


def test_main_slug_absent_from_staged_record_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A --dev-plugins slug the pointed-at record does not declare is an error naming
    the available slugs — no guessed clone (req-dev-workspace-spawn-5)."""
    _stage_record(tmp_path, "soak", _profile(_git("gryphon_playground")))

    rc = dev_workspace.main(["--base-profile", "soak", "--dev-plugins", "samsite", "--worktree", str(tmp_path)])

    assert rc == 1
    err = capsys.readouterr().err
    assert "'samsite' is not a plugin in the base profile's install list" in err
    assert "gryphon_playground" in err  # the error names what IS available


def test_main_missing_base_profile_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No boot/<id>.boot.json at all (e.g. a typo'd id, or --from never staged) fails with the path."""
    rc = dev_workspace.main(["--base-profile", "nope", "--dev-plugins", "x", "--worktree", str(tmp_path)])
    assert rc == 1
    assert "base profile not found" in capsys.readouterr().err


def test_main_unresolvable_credential_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A record entry naming a credential absent from the secrets root fails with an
    ``error:`` line, not a traceback — and fails in the PREFLIGHT, before any clone is
    attempted (req-tap-plugin-arch-source-secret-7). ``clone_editable`` is replaced with a
    tripwire: reaching it at all would mean the check ran too late to be worth having."""
    _stage_record(tmp_path, "soak", _profile(_git("gryphon_playground")))
    empty_secrets = tmp_path / "secrets"
    empty_secrets.mkdir()

    def _never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("clone_editable ran despite an unsatisfiable credential")

    monkeypatch.setattr(dev_workspace, "clone_editable", _never)

    rc = dev_workspace.main(
        [
            "--base-profile",
            "soak",
            "--dev-plugins",
            "gryphon_playground",
            "--worktree",
            str(tmp_path),
            "--secrets-root",
            str(empty_secrets),
        ]
    )

    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "github-plugins-ro" in err
    assert "gryphon_playground" in err  # names the plugin blocked by it
    assert "DROP the `credential` key" in err  # and the road out a public repo takes


def test_clone_editable_resolves_a_branch_rev(tmp_path: Path) -> None:
    """The fork-cutover dev flow pins rev to a BRANCH, not a tag — clone_editable's
    blobless clone + `checkout <rev>` must resolve branch names (and track the tip,
    which is the point of a dev branch pin)."""
    import subprocess

    origin = tmp_path / "origin"
    origin.mkdir()
    env_id = ["-c", "user.name=t", "-c", "user.email=t@t"]

    def git(*args: str, cwd: Path = origin) -> None:
        subprocess.run(["git", *env_id, *args], cwd=cwd, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (origin / "f.txt").write_text("v1", encoding="utf-8")
    git("add", "f.txt")
    git("commit", "-q", "-m", "one")
    git("checkout", "-q", "-b", "sam-dev-branch")
    (origin / "f.txt").write_text("branch-tip", encoding="utf-8")
    git("commit", "-q", "-am", "two")
    git("checkout", "-q", "main")  # origin HEAD elsewhere: checkout must find the branch

    worktree = tmp_path / "wt"
    worktree.mkdir()
    spec = dev_workspace.CloneSpec(slug="samsite", url=str(origin), rev="sam-dev-branch", credential=None)
    dest = dev_workspace.clone_editable(spec, worktree, None)

    assert dest == worktree / "_dev-plugins" / "samsite"
    assert (dest / "f.txt").read_text(encoding="utf-8") == "branch-tip"
