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
import os
from pathlib import Path
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
    assert "exec /app/.venv/bin/gunicorn" in entrypoint
    assert "tap.wsgi:application" in entrypoint
    assert settings.WSGI_APPLICATION == "tap.wsgi.application"


@pytest.mark.spec("req-tap-serving-process-failure-2")
def test_the_server_is_execed_directly_and_not_wrapped_by_uv_run() -> None:
    """The arbiter must BE PID 1, not be a child of a PID 1 that cannot reap.

    `exec uv run gunicorn ...` shipped and looked right: it has the `exec`, and the
    comment above it asserted gunicorn was PID 1. `exec` replaced the shell with **uv**,
    which forked gunicorn as a child — so PID 1 was `uv run`, which does not reap the
    orphans a PID namespace's PID 1 inherits. Measured on a 24h container: 266 zombies
    of 278 processes, all PPid 1 (tap#502).

    HONEST LIMIT: this reads source text. It cannot observe the property it protects —
    that `/proc/1/cmdline` inside a running container names gunicorn — because that
    needs a container, which this suite does not have. It is a presence test, kept
    because what it forbids is something a later change would ADD back (the `uv run`
    wrapper is the natural thing to reach for), not something absent today. The
    correctness observation belongs on a running instance, not here.
    """
    served = [
        line.strip()
        for line in _ENTRYPOINT.read_text().splitlines()
        if line.lstrip().startswith("exec ") and "gunicorn" in line
    ]
    assert served == ["exec /app/.venv/bin/gunicorn --config /app/docker/gunicorn.conf.py tap.wsgi:application"], served


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
