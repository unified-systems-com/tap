"""The initializer: classify the stores, mint once, apply from the stored values, hand on.

Spec: `specs/spec-tap-baked-instance.md` (`req-tap-bake-initializer`, `req-tap-bake-activate`,
`req-tap-bake-installation-identity`). The database side runs against fakes here: a real run
re-keys the owning role, and the stack these tests run in shares that role. The real-database
behaviour (the lock under a race, the re-key, a restart) was proven on a product-image compose
stack and is recorded in tap#1328.
"""

from __future__ import annotations

import shlex
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from tap import initialize

URL = "postgres://tap:boot%2Fstrap@db:5432/tap"


@pytest.fixture
def store(tmp_path: Path) -> initialize.StateStore:
    root = tmp_path / "installation"
    root.mkdir(mode=0o700)
    return initialize.StateStore(root)


class _FakeConn:
    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def cluster(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A fake cluster: what the database holds, the passwords tried, and every owner re-key."""
    state: dict[str, Any] = {"relations": 0, "tap_schema": False, "rekeys": [], "tried": [], "fail_rekey": False}

    def connect(target: Any, passwords: list[str], dbname: str | None = None, **_: Any) -> _FakeConn:
        state["tried"].append([p for p in passwords if p])
        return _FakeConn()

    @contextmanager
    def lock(conn: Any, dbname: str):
        state["locked"] = dbname
        yield

    def rekey(conn: Any, user: str, password: str) -> None:
        if state["fail_rekey"]:
            raise RuntimeError("killed during the re-key")
        state["rekeys"].append((user, password))

    monkeypatch.setattr(initialize, "connect", connect)
    monkeypatch.setattr(initialize, "installation_lock", lock)
    monkeypatch.setattr(initialize, "database_contents", lambda conn: (state["relations"], state["tap_schema"]))
    monkeypatch.setattr(initialize, "apply_owner_password", rekey)
    return state


def _handoff(path: Path) -> dict[str, str]:
    return {k: shlex.split(v)[0] for k, v in (line.split("=", 1) for line in path.read_text().splitlines())}


@pytest.mark.spec("req-tap-bake-initializer-7")
@pytest.mark.parametrize(
    ("identity", "relations", "tap_schema", "road"),
    [
        (None, 0, False, initialize.ROAD_ACTIVATE),
        (None, 50, True, initialize.ROAD_LEGACY),
        ({"status": "pending", "progress": {}}, 0, False, initialize.ROAD_RESUME),
        ({"status": "active", "progress": {}}, 0, False, initialize.ROAD_FINISH),
        ({"status": "active", "progress": {"finish": "done"}}, 50, True, initialize.ROAD_FINISH),
    ],
)
def test_each_store_state_has_one_road(identity: Any, relations: int, tap_schema: bool, road: str) -> None:
    assert initialize.classify(identity, relations, tap_schema) == road


@pytest.mark.spec("req-tap-bake-initializer-7")
def test_unknown_stores_are_refused() -> None:
    with pytest.raises(initialize.InitializeError, match="no TAP schema"):
        initialize.classify(None, 1, False)
    with pytest.raises(initialize.InitializeError, match="stores disagree"):
        initialize.classify({"status": "active", "progress": {"finish": "done"}}, 0, False)


@pytest.mark.spec("req-tap-bake-initializer-7")
def test_a_refusal_writes_nothing(store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path) -> None:
    cluster["relations"] = 1
    handoff = tmp_path / "installation.env"
    with pytest.raises(initialize.InitializeError):
        initialize.run(store, initialize.Target(URL), handoff=handoff)
    assert list(store.root.iterdir()) == [] and not handoff.exists() and cluster["rekeys"] == []


@pytest.mark.spec("req-tap-bake-installation-identity-1")
def test_activation_mints_stores_and_hands_on(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    handoff = tmp_path / "installation.env"
    assert initialize.run(store, initialize.Target(URL), handoff=handoff) == "activated"
    identity = store.read()
    assert identity is not None and identity["status"] == "active"
    assert cluster["rekeys"] == [("tap", identity["owner_password"])]
    env = _handoff(handoff)
    assert env["SECRET_KEY"] == identity["secret_key"]
    assert env["TAP_GRID_ID"] == identity["grid_id"]
    assert env["TAP_SEARCH_READONLY_PASSWORD"] == identity["search_password"]
    assert env["DATABASE_URL"].startswith("postgres://tap:") and "boot%2Fstrap" not in env["DATABASE_URL"]
    assert stat.S_IMODE(store.identity_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(handoff.stat().st_mode) == 0o600


@pytest.mark.spec("req-tap-bake-installation-identity-2")
def test_two_installations_share_nothing() -> None:
    a, b = initialize.mint_identity(), initialize.mint_identity()
    for key in ("secret_key", "owner_password", "search_password", "grid_id", "activation_id"):
        assert a[key] != b[key], key
    assert len(a["secret_key"]) >= 80


@pytest.mark.spec("req-tap-bake-activate-3")
def test_a_restart_never_mints_again(store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path) -> None:
    handoff = tmp_path / "installation.env"
    initialize.run(store, initialize.Target(URL), handoff=handoff)
    first = store.read()
    assert first is not None
    cluster.update(relations=50, tap_schema=True, rekeys=[])
    minted: list[int] = []

    def must_not_mint() -> dict[str, Any]:
        minted.append(1)
        return initialize.mint_identity()

    assert initialize.run(store, initialize.Target(URL), handoff=handoff, minter=must_not_mint) == "finish"
    assert minted == [] and cluster["rekeys"] == [] and store.read() == first
    assert cluster["tried"][-1][0] == first["owner_password"], (
        "an activated installation connects with its own password"
    )


@pytest.mark.spec("req-tap-bake-activate-5")
def test_an_interrupted_activation_reuses_its_values(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    cluster["fail_rekey"] = True
    with pytest.raises(RuntimeError, match="killed"):
        initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    pending = store.read()
    assert pending is not None and pending["status"] == "pending", "values are stored before anything is applied"
    cluster["fail_rekey"] = False

    def must_not_mint() -> dict[str, Any]:
        raise AssertionError("a resumed activation mints nothing")

    assert (
        initialize.run(store, initialize.Target(URL), handoff=tmp_path / "b.env", minter=must_not_mint) == "activated"
    )
    active = store.read()
    assert active is not None and active["status"] == "active"
    for key in ("secret_key", "owner_password", "grid_id", "activation_id"):
        assert active[key] == pending[key], key
    assert cluster["rekeys"] == [("tap", pending["owner_password"])]


@pytest.mark.spec("req-tap-bake-initializer-6")
def test_a_legacy_installation_is_left_to_its_deploy_config(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    cluster.update(relations=50, tap_schema=True)
    handoff = tmp_path / "installation.env"
    assert initialize.run(store, initialize.Target(URL), handoff=handoff) == initialize.ROAD_LEGACY
    assert store.read() is None and not handoff.exists() and cluster["rekeys"] == []


def test_the_target_url_is_rebuilt_with_a_quoted_password() -> None:
    target = initialize.Target(URL)
    assert (target.user, target.bootstrap_password, target.dbname) == ("tap", "boot/strap", "tap")
    assert target.with_password("a/b:c@d", "postgres") == "postgres://tap:a%2Fb%3Ac%40d@db:5432/postgres"


def test_the_store_must_be_an_absolute_writable_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for bad in ("", "relative/dir", "/var/../etc", str(tmp_path / "absent")):
        monkeypatch.setenv("TAP_INSTALLATION_DIR", bad)
        with pytest.raises(initialize.InitializeError):
            initialize._store_from_env()
    monkeypatch.setenv("TAP_INSTALLATION_DIR", str(tmp_path))
    assert initialize._store_from_env().root == tmp_path


@pytest.mark.spec("req-tap-bake-initializer")
def test_the_entrypoint_runs_the_initializer_before_any_setting_and_boot_after() -> None:
    text = (Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    init = text.index("python -m tap.initialize run")
    assert init < text.index("scripts/codespace-env") and init < text.index("python -m tap.preboot")
    assert "mounted volume; the installation's identity must outlive the container" in text
    boot = text.index('if [ -n "${TAP_INITIALIZED}" ]; then')
    assert text.index("tap.initialize mark finish", boot) < text.index("tap.initialize mark first-login", boot)
