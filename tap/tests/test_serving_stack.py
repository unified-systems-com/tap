"""The artifact serves under gunicorn, and serves its static without collecting it.

Three properties, each of which was untrue before tap#462 and each of which would be
invisible if it silently became untrue again:

1.  The server is gunicorn with SYNC workers, over `tap.wsgi.application`, in BOTH
    profiles. The worker class is load-bearing, not stylistic — the connection budget
    is arithmetic on one-connection-per-worker-per-alias.
2.  The worker count is named configuration, readable at runtime, never a library
    default: it is the input the budget derives from.
3.  Static is WhiteNoise over the finders, with no `collectstatic` anywhere and no
    knob that branches on `DEBUG`.

The assertions that read source text do so because what they forbid is something a
later change would ADD, not something present today: a `runserver` invocation, a
`collectstatic` step, a `DEBUG`-derived static setting. A test that only exercised the
current configuration would pass while any of them was reintroduced.

Spec: `specs/spec-tap-serving.md` req-tap-serving-server, req-tap-serving-static,
req-tap-serving-static-unhashed, req-tap-serving-delta.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.conf import settings

from tap import serving

_REPO_ROOT = Path(settings.BASE_DIR)
_ENTRYPOINT = _REPO_ROOT / "docker" / "entrypoint.sh"
_GUNICORN_CONF = _REPO_ROOT / "docker" / "gunicorn.conf.py"


# ---------------------------------------------------------------------------
# req-tap-serving-server — the server
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-serving-server-1")
def test_the_entrypoint_serves_the_wsgi_application_under_gunicorn() -> None:
    """`WSGI_APPLICATION` was declared and served by nothing. Now it is served."""
    entrypoint = _ENTRYPOINT.read_text()
    assert "exec uv run gunicorn" in entrypoint
    assert "tap.wsgi:application" in entrypoint
    assert settings.WSGI_APPLICATION == "tap.wsgi.application"


@pytest.mark.spec("req-tap-serving-server-1")
def test_no_environment_invokes_the_development_server() -> None:
    """No `runserver` / `runserver_nocache` invocation survives anywhere we start a server.

    Checked as an invocation (`manage.py runserver`), not as the bare word: the word
    legitimately appears in prose explaining WHY the development server is not a
    deployment target, and a test that forbade the explanation would delete the reason.
    """
    searched = [_ENTRYPOINT, _GUNICORN_CONF, _REPO_ROOT / "docker-compose.yml"]
    for path in searched:
        text = path.read_text()
        for invocation in ("manage.py runserver", "manage.py runserver_nocache"):
            offending = [line for line in text.splitlines() if invocation in line and not line.lstrip().startswith("#")]
            assert not offending, f"{path.name}: {offending}"


@pytest.mark.spec("req-tap-serving-server-4")
def test_the_no_cache_command_is_retired() -> None:
    """`runserver_nocache` is gone; WhiteNoise's `max-age=0` absorbed its job."""
    assert not (_REPO_ROOT / "tap_grid" / "management" / "commands" / "runserver_nocache.py").exists()


@pytest.mark.spec("req-tap-serving-server-2")
def test_the_worker_class_is_sync() -> None:
    """Async / gevent workers forfeit one-connection-per-worker, which is the budget."""
    assert serving.WORKER_CLASS == "sync"
    assert "worker_class = serving.WORKER_CLASS" in _GUNICORN_CONF.read_text()


@pytest.mark.spec("req-tap-serving-server-3")
def test_the_worker_count_is_explicit_named_configuration() -> None:
    """Readable at runtime, from the same function the gunicorn master reads."""
    assert settings.TAP_WEB_WORKERS == serving.DEFAULT_WORKERS
    with mock.patch.dict(os.environ, {"TAP_WEB_WORKERS": "7"}):
        assert serving.worker_count() == 7


@pytest.mark.spec("req-tap-serving-server-3")
@pytest.mark.parametrize("bad", ["0", "-1", "two", "  "])
def test_a_bad_worker_count_refuses_rather_than_falling_back(bad: str) -> None:
    """A typo must not quietly become the default — that is a budget input.

    "  " is included deliberately: whitespace strips to empty, which IS unset, so it
    legitimately takes the default rather than raising.
    """
    with mock.patch.dict(os.environ, {"TAP_WEB_WORKERS": bad}):
        if bad.strip() == "":
            assert serving.worker_count() == serving.DEFAULT_WORKERS
            return
        with pytest.raises(ValueError):
            serving.worker_count()


# ---------------------------------------------------------------------------
# req-tap-serving-delta — the profile, and what it may decide
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-serving-delta-2")
def test_the_profile_defaults_to_production_when_unset() -> None:
    """Fail-safe: an operator who never heard of the variable gets no reloader."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TAP_SERVE_PROFILE", None)
        assert serving.serve_profile() == serving.PROFILE_PRODUCTION
        assert serving.is_development() is False


@pytest.mark.spec("req-tap-serving-delta-2")
def test_an_unknown_profile_refuses_rather_than_coercing() -> None:
    """A typo'd profile would otherwise silently take the reloader away with no message."""
    with mock.patch.dict(os.environ, {"TAP_SERVE_PROFILE": "dev"}):
        with pytest.raises(ValueError):
            serving.serve_profile()


@pytest.mark.spec("req-tap-serving-delta-2")
def test_the_reloader_is_the_only_thing_the_profile_gives_gunicorn() -> None:
    """Both columns of the delta run the same server, class and worker count."""
    conf = _GUNICORN_CONF.read_text()
    assert "reload = serving.is_development()" in conf
    # Nothing else in the config may consult the profile: the delta is one row.
    profile_lines = [ln for ln in conf.splitlines() if "is_development" in ln and not ln.lstrip().startswith("#")]
    assert profile_lines == ["reload = serving.is_development()"]


# ---------------------------------------------------------------------------
# req-tap-serving-static — WhiteNoise, finders, both profiles
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-serving-static-1")
def test_whitenoise_serves_static_ahead_of_the_login_wall() -> None:
    """Static reaches the browser through WhiteNoise, in every profile, unauthenticated.

    Position matters twice: after SecurityMiddleware (WhiteNoise's own contract) and
    before the default-deny login wall, so assets are served without ever reaching
    authorization rather than by an exempt-prefix list that has to stay correct.
    """
    mw = settings.MIDDLEWARE
    whitenoise = mw.index("whitenoise.middleware.WhiteNoiseMiddleware")
    assert whitenoise == mw.index("django.middleware.security.SecurityMiddleware") + 1
    assert whitenoise < mw.index("tap_auth.middleware.TapLoginRequiredMiddleware")


@pytest.mark.spec("req-tap-serving-static-2")
def test_nothing_is_collected_and_nothing_expects_it_to_be() -> None:
    """No `collectstatic` at build or boot, and `STATIC_ROOT` says so honestly.

    A declared-but-never-populated `STATIC_ROOT` is the presence-not-correctness shape:
    it reads as "assets are collected here" while nothing collects, and WhiteNoise would
    warn about the missing directory on every start in the production profile.
    """
    assert settings.WHITENOISE_USE_FINDERS is True
    assert settings.STATIC_ROOT is None
    for path in (_ENTRYPOINT, _REPO_ROOT / "Dockerfile"):
        collecting = [
            line
            for line in path.read_text().splitlines()
            if "collectstatic" in line and not line.lstrip().startswith("#")
        ]
        assert not collecting, f"{path.name}: {collecting}"


@pytest.mark.spec("req-tap-serving-static-3")
def test_development_serves_static_without_caching_and_production_briefly() -> None:
    """`max-age=0` in development is what retired `runserver_nocache`."""
    import tap.settings as tap_settings

    for profile, expected_autorefresh, expected_max_age in (
        (serving.PROFILE_DEVELOPMENT, True, 0),
        (serving.PROFILE_PRODUCTION, False, 60),
    ):
        with mock.patch.dict(os.environ, {"TAP_SERVE_PROFILE": profile}):
            reloaded = importlib.reload(tap_settings)
            try:
                assert reloaded.WHITENOISE_AUTOREFRESH is expected_autorefresh, profile
                assert reloaded.WHITENOISE_MAX_AGE == expected_max_age, profile
            finally:
                importlib.reload(tap_settings)


@pytest.mark.spec("req-tap-serving-static-unhashed-1")
def test_the_staticfiles_backend_does_not_hash_filenames() -> None:
    """Hashing splits the tap_viz ES-module graph across two cache generations.

    `layout-loader.js` resolves a module URL from GRID DATA, so no build step can
    rewrite it — the prohibition is a consequence of the projection system's design.
    """
    backend = settings.STORAGES["staticfiles"]["BACKEND"]
    assert "Manifest" not in backend, backend
    assert "Hashed" not in backend, backend


@pytest.mark.spec("req-tap-serving-debug-scope-1")
def test_no_static_or_serving_setting_is_derived_from_debug() -> None:
    """The coupling this forbids is the one the whole spec exists to undo.

    WhiteNoise's OWN defaults for `autorefresh`, `max_age` and `use_finders` read
    `settings.DEBUG`. Declaring all three explicitly is what keeps the profile — not the
    debug flag — in charge, so this asserts the declarations exist, not merely that
    today's values happen to be right.
    """
    source = (_REPO_ROOT / "tap" / "settings.py").read_text()
    for setting in ("WHITENOISE_USE_FINDERS", "WHITENOISE_AUTOREFRESH", "WHITENOISE_MAX_AGE"):
        assert hasattr(settings, setting), setting
        declaration = [ln for ln in source.splitlines() if ln.startswith(f"{setting} =")]
        assert len(declaration) == 1, (setting, declaration)
        assert "DEBUG" not in declaration[0], declaration


# ---------------------------------------------------------------------------
# req-tap-serving-server-5 — no load-bearing behaviour from an unchosen default
# ---------------------------------------------------------------------------
#
# These read the LOADED config, not its source text: the question is what gunicorn
# would actually be handed. The assertions are deliberately few — one per setting
# that carries a correctness argument something else can break — because asserting
# that every line is present would test presence while the value went wrong.


def _load_gunicorn_conf(profile: str | None = None) -> Any:
    """Import `docker/gunicorn.conf.py` the way the gunicorn master does."""
    env = {} if profile is None else {"TAP_SERVE_PROFILE": profile}
    with mock.patch.dict(os.environ, env):
        spec = importlib.util.spec_from_file_location("_tap_gunicorn_conf", _GUNICORN_CONF)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


@pytest.mark.spec("req-tap-serving-server-5")
def test_preloading_is_never_on_while_the_reloader_is() -> None:
    """The two are incompatible, and the reloader is the inner loop.

    `preload_app` forks workers from an already-imported application, which is exactly
    what `--reload` cannot do — gunicorn refuses the combination. The plausible future
    change is someone turning preloading on to save memory or shave worker boot; this is
    what makes that land as a red test instead of as a development stack that silently
    stops picking up edits.
    """
    for profile in (serving.PROFILE_DEVELOPMENT, serving.PROFILE_PRODUCTION):
        conf = _load_gunicorn_conf(profile)
        assert conf.preload_app is False, profile
        assert not (conf.reload and conf.preload_app), profile
    assert _load_gunicorn_conf(serving.PROFILE_DEVELOPMENT).reload is True


@pytest.mark.spec("req-tap-serving-server-5")
def test_every_gunicorn_setting_is_either_assigned_or_acknowledged() -> None:
    """The enumeration that makes "no unchosen default" falsifiable instead of asserted.

    Without this, "every production-relevant knob is stated" is a claim no one can check:
    a reader cannot distinguish a setting that was considered and left alone from one
    nobody had heard of, and a gunicorn upgrade that ADDS a setting changes behaviour with
    no diff in this repository at all.

    So the partition is asserted against gunicorn's OWN registry — `KNOWN_SETTINGS`, the
    installed version's, not a list copied into this test. Every name must be either
    assigned in `docker/gunicorn.conf.py` or listed in its `LIBRARY_DEFAULTS_ACKNOWLEDGED`
    map under a reason. A new setting in a future release lands here by name, and someone
    has to decide which group it belongs in.

    Both directions matter: an acknowledged name that gunicorn no longer has is a stale
    entry whose reason nobody re-read, and a name that is both assigned and acknowledged is
    two answers to one question.
    """
    from gunicorn.config import KNOWN_SETTINGS

    conf = vars(_load_gunicorn_conf())
    known = {setting.name for setting in KNOWN_SETTINGS}
    acknowledged_groups = conf["LIBRARY_DEFAULTS_ACKNOWLEDGED"]
    acknowledged = {name for group in acknowledged_groups.values() for name in group}
    assigned = {name for name in conf if name in known}

    assert not (acknowledged - known), f"acknowledged but gone from gunicorn: {sorted(acknowledged - known)}"
    assert not (acknowledged & assigned), f"both assigned and acknowledged: {sorted(acknowledged & assigned)}"
    unaccounted = known - assigned - acknowledged
    assert not unaccounted, (
        f"gunicorn settings neither assigned nor acknowledged: {sorted(unaccounted)} — "
        "assign each in docker/gunicorn.conf.py with the reason for its value, or add it to "
        "LIBRARY_DEFAULTS_ACKNOWLEDGED under the group that explains why its default stands."
    )


@pytest.mark.spec("req-tap-serving-server-5")
def test_the_request_parsing_and_proxy_trust_knobs_stay_strict() -> None:
    """These five loosen HTTP parsing and one decides whom to believe about the scheme.

    Asserted as VALUES, not as presence, because every one of them is a knob whose only
    direction of travel is looser: accepting an unconventional method or version, obsolete
    line folding, or a space before a header colon are each documented request-smuggling
    primitives when a proxy and an origin disagree about them.

    `forwarded_allow_ips` is here for a different reason: gunicorn's default READS AN
    ENVIRONMENT VARIABLE (`FORWARDED_ALLOW_IPS`), so proxy trust could be widened to `*`
    from outside this repository. Pinning it is what takes that lever away — and it is what
    keeps `secure_scheme_headers` unreachable, since `gunicorn/http/message.py` consults
    those headers only for a peer inside this list.
    """
    conf = _load_gunicorn_conf()
    assert conf.casefold_http_method is False
    assert conf.permit_unconventional_http_method is False
    assert conf.permit_unconventional_http_version is False
    assert conf.permit_obsolete_folding is False
    assert conf.strip_header_spaces is False
    assert conf.header_map in {"drop", "refuse"}, conf.header_map
    assert conf.proxy_protocol is False
    assert "*" not in conf.forwarded_allow_ips
    assert "*" not in conf.proxy_allow_ips


@pytest.mark.spec("req-tap-serving-server-5")
def test_worker_recycling_never_runs_without_jitter() -> None:
    """Un-jittered recycling retires every worker at once — a self-inflicted outage.

    Workers fork together, so they reach the same request count together. gunicorn adds
    `randint(0, max_requests_jitter)` per worker at fork; with jitter at its default of 0
    that spread is zero and a 3-worker stack has, briefly, no workers at all.
    """
    conf = _load_gunicorn_conf()
    if conf.max_requests > 0:
        assert conf.max_requests_jitter > 0, "recycling is enabled with no jitter"
        assert conf.max_requests_jitter <= conf.max_requests


# ---------------------------------------------------------------------------
# req-tap-serving-budgets — the four timers, and the order they must hold in
# ---------------------------------------------------------------------------
#
# Scope of these assertions: they compare CONFIGURATION VALUES. None drives a
# slow request, a reload, or a shutdown, so none observes the LIFECYCLE
# BEHAVIOUR the values are meant to produce. They catch an incoherent set of
# numbers — which is what went wrong — and they do not catch a coherent set that
# behaves differently in practice.


@pytest.mark.spec("req-tap-serving-budgets-1")
def test_the_watchdog_outlives_a_single_statement_bound() -> None:
    """The arbiter must not kill a worker while PostgreSQL still permits its statement.

    A sync worker heartbeats BETWEEN requests, so the watchdog doubles as the request
    deadline. If it were at or below `statement_timeout`, a query running the time the
    database explicitly allows it would be killed as a hung worker, and the failure would
    present as a mysterious worker death rather than as the statement timeout it is.

    What this does NOT assert — and what the earlier version of this test was mistakenly
    read as asserting — is that a whole REQUEST fits inside the watchdog. `statement_timeout`
    is per statement and one graph response issues several, so the sum can exceed it
    (tap#530). This is an inequality between two numbers, nothing more.
    """
    bound = serving.postgres_duration_seconds(settings.SEARCH_STATEMENT_TIMEOUT)
    assert bound is not None, "a disabled statement timeout leaves nothing to derive from"
    assert _load_gunicorn_conf().timeout > bound


@pytest.mark.spec("req-tap-serving-budgets-1")
def test_the_watchdog_follows_the_statement_bound_instead_of_disagreeing_with_it() -> None:
    """One lever, two readers: derived, so the two numbers cannot drift apart.

    The defect this closes is not a wrong number — it is two independently authored ones.
    An operator raising `TAP_SEARCH_STATEMENT_TIMEOUT` used to silently invalidate a fixed
    gunicorn timeout derived from its old value.
    """
    with mock.patch.dict(os.environ, {"TAP_SEARCH_STATEMENT_TIMEOUT": "60s"}):
        assert serving.search_statement_timeout() == "60s"
        assert serving.worker_timeout() == 60 + serving.REQUEST_OVERHEAD_HEADROOM_SECONDS
    with mock.patch.dict(os.environ, {"TAP_SEARCH_STATEMENT_TIMEOUT": "5s"}):
        assert serving.worker_timeout() == 5 + serving.REQUEST_OVERHEAD_HEADROOM_SECONDS


@pytest.mark.spec("req-tap-serving-budgets-1")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30s", 30.0),
        ("500ms", 0.5),
        ("2min", 120.0),
        ("1h", 3600.0),
        ("250", 0.25),  # bare integer is MILLISECONDS, per PostgreSQL
        ("0", None),  # disabled — the third state, not "zero seconds"
    ],
)
def test_postgres_durations_are_parsed_in_the_units_postgres_accepts(raw: str, expected: float | None) -> None:
    """Deriving from a setting means reading it the way its owner reads it.

    The first version accepted only integer seconds, which would have mis-derived — or
    crashed on — every other form PostgreSQL permits.
    """
    assert serving.postgres_duration_seconds(raw) == expected


@pytest.mark.spec("req-tap-serving-budgets-1")
def test_an_unparseable_or_disabled_statement_bound_refuses_rather_than_guessing() -> None:
    """Three states: a duration derives, `0` (disabled) refuses, nonsense refuses."""
    with pytest.raises(ValueError):
        serving.postgres_duration_seconds("soon")
    with mock.patch.dict(os.environ, {"TAP_SEARCH_STATEMENT_TIMEOUT": "0"}):
        with pytest.raises(ValueError, match="disabled"):
            serving.worker_timeout()


@pytest.mark.spec("req-tap-serving-budgets-1")
def test_an_explicit_timeout_that_contradicts_the_statement_bound_is_refused() -> None:
    """The override exists, but it may not recreate the disagreement it replaced."""
    with mock.patch.dict(os.environ, {"TAP_WEB_TIMEOUT": "10", "TAP_SEARCH_STATEMENT_TIMEOUT": "30s"}):
        with pytest.raises(ValueError, match="does not exceed"):
            serving.worker_timeout()
    with mock.patch.dict(os.environ, {"TAP_WEB_TIMEOUT": "90", "TAP_SEARCH_STATEMENT_TIMEOUT": "30s"}):
        assert serving.worker_timeout() == 90


@pytest.mark.spec("req-tap-serving-budgets-2")
def test_the_shutdown_pair_is_ordered_so_the_outer_one_does_not_truncate_the_inner() -> None:
    """Docker's 10s default was silently truncating a 30s drain — budget 3 was fiction.

    Also asserts the deliberate inversion: the drain is SHORTER than the watchdog, so a
    shutdown may cut short a request that was permitted to run. That is a recorded decision
    (`serving.GRACEFUL_DRAIN_SECONDS`), so it is asserted rather than left to be rediscovered
    as a surprise.
    """
    conf = _load_gunicorn_conf()
    assert conf.graceful_timeout == serving.GRACEFUL_DRAIN_SECONDS
    assert serving.CONTAINER_STOP_GRACE_SECONDS > serving.GRACEFUL_DRAIN_SECONDS
    assert serving.GRACEFUL_DRAIN_SECONDS < conf.timeout


@pytest.mark.spec("req-tap-serving-budgets-2")
def test_compose_declares_the_container_stop_allowance_the_drain_needs() -> None:
    """The outermost budget lives in YAML, so it is verified against its Python author.

    Absent this key the value is Docker's 10s default — a budget nobody chose, truncating
    one that was chosen. This asserts the declaration exists AND agrees; it does not observe
    a shutdown.
    """
    lines = [
        line.strip()
        for line in (_REPO_ROOT / "docker-compose.yml").read_text().splitlines()
        if line.strip().startswith("stop_grace_period:")
    ]
    assert lines == [f"stop_grace_period: {serving.CONTAINER_STOP_GRACE_SECONDS}s"], lines


@pytest.mark.spec("req-tap-serving-delta-2")
def test_only_the_reloader_differs_between_the_two_profiles() -> None:
    """None of the server knobs are dev/prod deltas — the delta is one enumerated row.

    Asserted over the loaded config rather than its source text, so a value that *derives*
    from the profile indirectly — through a helper, an env read, a conditional — is caught
    the same way a literal branch would be.
    """
    dev = vars(_load_gunicorn_conf(serving.PROFILE_DEVELOPMENT))
    prod = vars(_load_gunicorn_conf(serving.PROFILE_PRODUCTION))
    differing = {
        name
        for name in set(dev) | set(prod)
        if not name.startswith("_") and not callable(dev.get(name)) and dev.get(name) != prod.get(name)
    }
    assert differing == {"reload"}, differing


# ---------------------------------------------------------------------------
# req-tap-serving-server-5 — the heartbeat lives in RAM, and says so honestly
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-serving-server-5")
def test_the_heartbeat_directory_exists_where_the_workers_run() -> None:
    """A missing mount is the whole failure mode, so it is checked where it is mounted.

    Every worker rewrites this file's mtime on every heartbeat and the arbiter stats it to
    decide whether the worker is alive. `serving.worker_tmp_dir()` refuses a missing
    directory, so this exercises that refusal's happy path AND proves the compose mount is
    real in the environment the suite runs in.
    """
    assert serving.worker_tmp_dir() == serving.WORKER_TMP_DIR
    assert Path(serving.WORKER_TMP_DIR).is_dir()


@pytest.mark.spec("req-tap-serving-server-5")
def test_a_missing_heartbeat_directory_refuses_rather_than_falling_back(tmp_path: Path) -> None:
    """Fail closed, at config load, not at first fork.

    The alternative to refusing is serving with the heartbeat silently back on the
    disk-backed overlay — a configuration that reads as fixed and is not.
    """
    with mock.patch.dict(os.environ, {"TAP_WORKER_TMP_DIR": str(tmp_path / "absent")}):
        with pytest.raises(RuntimeError, match="does not exist"):
            serving.worker_tmp_dir()


@pytest.mark.spec("req-tap-serving-server-5")
def test_a_directory_that_exists_but_is_not_ram_is_refused_too(tmp_path: Path) -> None:
    """Existence is not the property this setting is for — the filesystem type is.

    A directory that merely exists passes a presence check while sitting on the
    disk-backed overlay `worker_tmp_dir` exists to leave, and `TAP_WORKER_TMP_DIR` puts
    that one environment variable away: a deployment could look configured and be exactly
    what the setting was added to prevent. So the claim is verified against its source —
    `/proc/self/mountinfo` — rather than inferred from the path being there.
    """
    observed = serving.filesystem_type(str(tmp_path))
    if observed is None:
        pytest.skip("filesystem type is not observable here — the third state, not a failure")
    if observed in serving.RAM_BACKED_FILESYSTEMS:
        pytest.skip(f"pytest's tmp_path is itself {observed}; this test needs a disk-backed one")
    with mock.patch.dict(os.environ, {"TAP_WORKER_TMP_DIR": str(tmp_path)}):
        with pytest.raises(RuntimeError, match="not RAM"):
            serving.worker_tmp_dir()


@pytest.mark.spec("req-tap-serving-server-5")
def test_the_heartbeat_mount_is_observably_ram_backed() -> None:
    """The positive half: the mount compose declares really is RAM where the workers run.

    Reported as three states, never two — an unobservable filesystem (no `/proc`, i.e. not
    Linux) is neither a pass nor a failure, and rendering it as either is how "we checked"
    comes to mean nothing.
    """
    observed = serving.filesystem_type(serving.WORKER_TMP_DIR)
    if observed is None:
        pytest.skip("filesystem type is not observable here — the third state, not a failure")
    assert observed in serving.RAM_BACKED_FILESYSTEMS, observed


@pytest.mark.spec("req-tap-serving-server-5")
def test_compose_mounts_a_bounded_tmpfs_at_the_authored_path() -> None:
    """The path is authored once in Python; this verifies the YAML copy against it.

    YAML cannot import a Python constant, so the mount target is necessarily written
    twice. A copy that is *verified* against its source is not a second derivation — but
    an unverified one drifts the day the constant moves, and gunicorn would then refuse to
    boot. The size bound is asserted for its own reason: a `tmpfs:` entry with no size
    defaults to half of host RAM, a silent enormous allocation for a file holding zero
    bytes.
    """
    entries = [
        line.strip().lstrip("-").strip()
        for line in (_REPO_ROOT / "docker-compose.yml").read_text().splitlines()
        if serving.WORKER_TMP_DIR in line and not line.lstrip().startswith("#")
    ]
    assert len(entries) == 1, entries
    target, _, options = entries[0].partition(":")
    assert target == serving.WORKER_TMP_DIR
    assert re.search(r"(^|,)size=\d+[kmg]?($|,)", options), options
