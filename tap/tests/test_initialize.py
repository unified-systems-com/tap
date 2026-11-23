"""The initializer: classify the stores, mint once, apply from the stored values, hand on.

Spec: `specs/spec-tap-baked-instance.md` (`req-tap-bake-initializer`, `req-tap-bake-activate`,
`req-tap-bake-installation-identity`). The database side runs against fakes here: a real run
re-keys the owning role, and the stack these tests run in shares that role. The real-database
behaviour (the lock under a race, the re-key, a restart) was proven on a product-image compose
stack and is recorded in tap#1328.
"""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
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
    state: dict[str, Any] = {
        "relations": 0, "tap_schema": False, "stamp": "", "rekeys": [], "stamps": [], "tried": [],
        "fail_rekey": False, "locks": 0,
    }  # fmt: skip

    def connect(target: Any, passwords: list[str], dbname: str | None = None, **_: Any) -> _FakeConn:
        state["tried"].append([p for p in passwords if p])
        return _FakeConn()

    @contextmanager
    def lock(conn: Any, dbname: str):
        state["locked"] = dbname
        state["locks"] += 1
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    def rekey(conn: Any, user: str, password: str) -> None:
        if state["fail_rekey"]:
            raise RuntimeError("killed during the re-key")
        state["rekeys"].append((user, password))

    monkeypatch.setattr(initialize, "connect", connect)
    monkeypatch.setattr(initialize, "installation_lock", lock)

    def stamp(conn: Any, dbname: str, activation_id: str) -> None:
        state["stamp"] = initialize.STAMP_PREFIX + activation_id
        state["stamps"].append(activation_id)

    monkeypatch.setattr(
        initialize, "database_contents", lambda conn: (state["relations"], state["tap_schema"], state["stamp"])
    )
    monkeypatch.setattr(initialize, "apply_owner_password", rekey)
    monkeypatch.setattr(initialize, "apply_stamp", stamp)
    return state


def _handoff(path: Path) -> dict[str, str]:
    return {k: shlex.split(v)[0] for k, v in (line.split("=", 1) for line in path.read_text().splitlines())}


@pytest.mark.spec("req-tap-bake-initializer-7")
@pytest.mark.parametrize(
    ("identity", "relations", "tap_schema", "stamp", "road"),
    [
        (None, 0, False, "", initialize.ROAD_ACTIVATE),
        (None, 0, False, "a comment someone else wrote", initialize.ROAD_ACTIVATE),
        ({"status": "pending", "activation_id": "A", "progress": {}}, 0, False, "", initialize.ROAD_RESUME),
        ({"status": "active", "activation_id": "A", "progress": {}}, 0, False, "tap-installation:A", initialize.ROAD_FINISH),
        (
            {"status": "active", "activation_id": "A", "progress": {"finish": "done"}},
            50, True, "tap-installation:A", initialize.ROAD_FINISH,
        ),
        # A concurrent start in flight: the cache table exists, migrate has not run yet.
        ({"status": "active", "activation_id": "A", "progress": {}}, 1, False, "tap-installation:A", initialize.ROAD_FINISH),
        ({"status": "pending", "activation_id": "A", "progress": {}}, 0, False, "tap-installation:A", initialize.ROAD_RESUME),
    ],
)  # fmt: skip
def test_each_store_state_has_one_road(identity: Any, relations: int, tap_schema: bool, stamp: str, road: str) -> None:
    assert initialize.classify(identity, relations, tap_schema, stamp) == road


@pytest.mark.spec("req-tap-bake-initializer-7")
@pytest.mark.parametrize(
    ("identity", "relations", "tap_schema", "stamp", "refused"),
    [
        (None, 1, False, "", "no TAP schema"),
        (None, 40, False, "", "no TAP schema"),  # a Django database that is not TAP's
        (None, 50, True, "tap-installation:B", "volume is missing"),
        (None, 1, True, "", "made without the initializer"),  # a lone tap_entity is not adopted
        ({"status": "active", "activation_id": "A", "progress": {"finish": "done"}}, 0, False, "tap-installation:A",
         "stores disagree"),
        ({"status": "active", "activation_id": "A", "progress": {}}, 50, True, "tap-installation:B",
         "different installations"),
        ({"status": "active", "activation_id": "A", "progress": {}}, 50, True, "", "no stamp from this installation"),
        ({"status": "active", "activation_id": "A", "progress": {"finish": "done"}}, 40, False, "tap-installation:A",
         "not TAP's"),
        ({"status": "pending", "activation_id": "A", "progress": {}}, 40, False, "", "no stamp of its own"),
        ({"status": "pending", "activation_id": "A", "progress": {}}, 50, True, "", "no stamp of its own"),
    ],
)  # fmt: skip
def test_unknown_or_mismatched_stores_are_refused(
    identity: Any, relations: int, tap_schema: bool, stamp: str, refused: str
) -> None:
    with pytest.raises(initialize.InitializeError, match=refused):
        initialize.classify(identity, relations, tap_schema, stamp)


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
    cluster.update(relations=50, tap_schema=True, rekeys=[], stamps=[])
    minted: list[int] = []

    def must_not_mint() -> dict[str, Any]:
        minted.append(1)
        return initialize.mint_identity()

    assert initialize.run(store, initialize.Target(URL), handoff=handoff, minter=must_not_mint) == "finish"
    assert minted == [] and cluster["rekeys"] == [] and cluster["stamps"] == [] and store.read() == first
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


@pytest.mark.spec("req-tap-bake-initializer-7")
def test_a_tap_database_without_an_identity_is_refused_not_adopted(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    cluster.update(relations=50, tap_schema=True)
    handoff = tmp_path / "installation.env"
    with pytest.raises(initialize.InitializeError, match="made without the initializer"):
        initialize.run(store, initialize.Target(URL), handoff=handoff)
    assert store.read() is None and not handoff.exists() and cluster["rekeys"] == []


@pytest.mark.spec("req-tap-bake-initializer-2")
def test_a_start_killed_while_issuing_the_link_never_issues_a_second(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    issued: list[str] = []

    def dies_after_minting(argv: list[str]) -> int:
        if argv[2] == "enroll_admin":
            issued.append("link")
            raise KeyboardInterrupt("killed after the link was printed")
        return 0

    with pytest.raises(KeyboardInterrupt):
        initialize.finish(store, initialize.Target(URL), runner=dies_after_minting)
    identity = store.read()
    assert identity is not None and identity["first_login"] == "issuing"
    initialize.finish(store, initialize.Target(URL), runner=dies_after_minting)
    assert issued == ["link"], "the restart boots but mints no second link"


@pytest.mark.spec("req-tap-bake-installation-identity")
def test_the_installation_volume_must_be_a_durable_mount() -> None:
    text = (Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    start = text.index('awk -v p="${TAP_INSTALLATION_DIR}" \'') + len('awk -v p="${TAP_INSTALLATION_DIR}" \'')
    program = text[start : text.index("' /proc/self/mountinfo", start)]
    mountinfo = (
        "36 25 0:41 / /var/lib/tap/installation rw,relatime - ext4 /dev/sda1 rw\n"
        "37 25 0:42 / /var/lib/tap/ram rw,relatime - tmpfs tmpfs rw\n"
    )
    for path, ok in (("/var/lib/tap/installation", True), ("/var/lib/tap/ram", False), ("/absent", False)):
        rc = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — the entrypoint's own awk on fixed input  # nosec B603 B607  # noqa: S603, S607
            ["awk", "-v", f"p={path}", program], input=mountinfo, text=True, capture_output=True
        ).returncode
        assert (rc == 0) is ok, path


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
def test_the_entrypoint_runs_the_initializer_before_any_setting_and_finish_fails_closed() -> None:
    text = (Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    init = text.index("python -m tap.initialize run")
    assert init < text.index("scripts/codespace-env") and init < text.index("python -m tap.preboot")
    assert "mounted, durable volume; the installation's identity must outlive the container" in text
    block = text[text.index("==> Installation: Finish") :]
    block = block[: block.index("\nfi\n")]
    assert "if ! /app/.venv/bin/python -m tap.initialize finish; then" in block and "exit 1" in block
    assert "enroll_admin" not in block, "the link is minted under the lock, inside tap.initialize finish"


@pytest.mark.spec("req-tap-bake-initializer")
def test_the_module_imports_without_django() -> None:
    """Settings-free is the security model: the module must load before any setting exists."""
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    probe = (
        "import sys, tap.initialize; print(sorted(m for m in sys.modules if m == 'django' or m.startswith('django.')))"
    )
    # The probe runs this interpreter on a fixed literal; a fresh process is the point of the test.
    out = subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit — fixed argv, no shell  # nosec B603  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, cwd=Path(__file__).resolve().parents[2]
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


@pytest.mark.spec("req-tap-bake-initializer-1")
def test_finish_boots_and_issues_the_first_link_once_under_the_lock(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    calls: list[tuple[str, bool]] = []

    def runner(argv: list[str]) -> int:
        calls.append((argv[2], cluster["held"]))
        return 0

    initialize.finish(store, initialize.Target(URL), runner=runner)
    assert calls == [("boot", True), ("enroll_admin", True)], "boot and the link both run inside the lock"
    identity = store.read()
    assert identity is not None and identity["progress"]["finish"] == "done" and identity["first_login"] == "issued"
    calls.clear()
    initialize.finish(store, initialize.Target(URL), runner=runner)
    assert calls == [("boot", True)], "a second Finish boots again but issues no second link"


@pytest.mark.spec("req-tap-bake-initializer")
def test_a_failed_boot_is_fatal_and_records_no_finish(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    with pytest.raises(initialize.InitializeError, match="boot failed"):
        initialize.finish(store, initialize.Target(URL), runner=lambda argv: 1)
    identity = store.read()
    assert identity is not None and "finish" not in identity["progress"] and identity["first_login"] == "pending"


@pytest.mark.spec("req-tap-bake-initializer-1")
def test_schema_steps_run_under_the_lock(store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path) -> None:
    initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    seen: list[bool] = []

    def runner(argv: list[str]) -> int:
        seen.append(cluster["held"])
        return 3

    assert (
        initialize.locked(store, initialize.Target(URL), ["uv", "run", "python", "manage.py", "migrate"], runner=runner)
        == 3
    )
    assert seen == [True], "the step ran inside the lock and its exit status is passed back"
    text = (Path(__file__).resolve().parents[2] / "docker" / "entrypoint.sh").read_text()
    for step in ("manage.py createcachetable", 'manage.py "$MIGRATE_COMMAND"'):
        line = next(ln for ln in text.splitlines() if step in ln and not ln.lstrip().startswith(("#", "echo")))
        assert line.startswith('"${TAP_LOCKED[@]}" uv run python'), line


@pytest.mark.spec("req-tap-bake-initializer-2")
def test_a_failed_link_mint_is_never_retried_automatically(
    store: initialize.StateStore, cluster: dict[str, Any], tmp_path: Path
) -> None:
    initialize.run(store, initialize.Target(URL), handoff=tmp_path / "a.env")
    minted: list[int] = []

    def enroll_fails(argv: list[str]) -> int:
        if argv[2] == "enroll_admin":
            minted.append(1)
            return 1
        return 0

    initialize.finish(store, initialize.Target(URL), runner=enroll_fails)
    initialize.finish(store, initialize.Target(URL), runner=enroll_fails)
    identity = store.read()
    assert identity is not None and identity["first_login"] == "issuing"
    assert minted == [1], "a failed enroll_admin may have printed a link, so it is not run again"
