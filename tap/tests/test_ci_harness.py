"""tap.ci_harness — the plugin PR lane's harness is the declared floor (req-tap-plugin-extdev-repo-ci-7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.ci_harness import HarnessResolutionError, floor_of, main, resolve

_TAGS = {"v0.1.5": "a" * 40, "v0.1.4": "b" * 40, "main": "c" * 40}


def _fake_resolver(repo_url: str, ref: str) -> str | None:
    assert repo_url == "https://github.com/unified-systems-com/tap.git"
    return _TAGS.get(ref)


def _manifest(tmp_path: Path, requires_tap: str | None) -> Path:
    body = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "p"\nname = "P"\n'
    if requires_tap is not None:
        body += f'requires_tap = "{requires_tap}"\n'
    path = tmp_path / "tap-plugin.toml"
    path.write_text(body)
    return path


class TestFloorOf:
    @pytest.mark.parametrize(
        ("spec", "floor"),
        [(">=0.1.5", "0.1.5"), (">=0.1.4,<0.2", "0.1.4"), ("~=0.1.5", "0.1.5"), ("==0.1.5", "0.1.5")],
    )
    def test_lower_bound(self, spec: str, floor: str) -> None:
        assert floor_of(spec) == floor

    def test_no_lower_bound_is_refused(self) -> None:
        with pytest.raises(HarnessResolutionError, match="no lower bound"):
            floor_of("<0.2")

    def test_two_lower_bounds_are_refused(self) -> None:
        with pytest.raises(HarnessResolutionError, match="more than one"):
            floor_of(">=0.1.2,>=0.1.4")


class TestResolve:
    def test_floor_resolves_to_the_release_tag_sha(self, tmp_path: Path) -> None:
        out = resolve(_manifest(tmp_path, ">=0.1.5,<0.2"), repo="unified-systems-com/tap", resolver=_fake_resolver)
        assert out == {"ref": "a" * 40, "source": "floor", "floor": "0.1.5"}

    def test_unreleased_floor_fails_naming_the_tag(self, tmp_path: Path) -> None:
        with pytest.raises(HarnessResolutionError, match="not a released core: no tag v0.1.9"):
            resolve(_manifest(tmp_path, ">=0.1.9"), repo="unified-systems-com/tap", resolver=_fake_resolver)

    def test_no_floor_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(HarnessResolutionError, match="declares no requires_tap"):
            resolve(_manifest(tmp_path, None), repo="unified-systems-com/tap", resolver=_fake_resolver)

    def test_override_wins_and_is_labelled(self, tmp_path: Path) -> None:
        out = resolve(
            _manifest(tmp_path, None), repo="unified-systems-com/tap", override="main", resolver=_fake_resolver
        )
        assert out == {"ref": "c" * 40, "source": "override", "floor": ""}

    def test_unresolvable_override_fails(self, tmp_path: Path) -> None:
        with pytest.raises(HarnessResolutionError, match="does not resolve"):
            resolve(_manifest(tmp_path, None), repo="unified-systems-com/tap", override="nope", resolver=_fake_resolver)


class TestCli:
    def test_writes_outputs_and_exit_codes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        import tap.ci_harness as mod

        monkeypatch.setattr(mod, "ls_remote", _fake_resolver)
        out_file = tmp_path / "out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))
        manifest = _manifest(tmp_path, ">=0.1.4")
        assert main(["--manifest", str(manifest), "--repo", "unified-systems-com/tap"]) == 0
        assert "ref=" + "b" * 40 in out_file.read_text()
        assert "source=floor" in capsys.readouterr().out
        assert main(["--manifest", str(_manifest(tmp_path, None)), "--repo", "unified-systems-com/tap"]) == 1
        assert "declares no requires_tap" in capsys.readouterr().err


class TestInputHygiene:
    def test_override_that_is_not_a_plain_ref_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(HarnessResolutionError, match="not a plain git ref"):
            resolve(
                _manifest(tmp_path, None),
                repo="unified-systems-com/tap",
                override="--upload-pack=x",
                resolver=_fake_resolver,
            )

    def test_repo_must_be_owner_name(self, tmp_path: Path) -> None:
        with pytest.raises(HarnessResolutionError, match="owner/name"):
            resolve(_manifest(tmp_path, ">=0.1.5"), repo="-x", resolver=_fake_resolver)

    def test_manifest_must_be_a_plugin_manifest(self, tmp_path: Path) -> None:
        other = tmp_path / "pyproject.toml"
        other.write_text("")
        with pytest.raises(HarnessResolutionError, match="not a plugin manifest"):
            resolve(other, repo="unified-systems-com/tap", resolver=_fake_resolver)


class TestLsRemoteSink:
    def test_ls_remote_validates_at_the_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tap.ci_harness as mod

        called: list[list[str]] = []

        class _Proc:
            stdout = b"c" * 40 + b"\trefs/heads/main\n"

        def fake_run_git(args: list[str], env: dict[str, str], *, error_cls: type[Exception]) -> _Proc:
            called.append(args)
            return _Proc()

        monkeypatch.setattr(mod, "run_git", fake_run_git)
        with pytest.raises(HarnessResolutionError, match="not a plain https clone URL"):
            mod.ls_remote("--upload-pack=x", "main")
        with pytest.raises(HarnessResolutionError, match="not a plain git ref"):
            mod.ls_remote("https://github.com/unified-systems-com/tap.git", "--upload-pack=x")
        assert called == []
        assert mod.ls_remote("https://github.com/unified-systems-com/tap.git", "main") == "c" * 40
        assert called == [["ls-remote", "https://github.com/unified-systems-com/tap.git", "main"]]
