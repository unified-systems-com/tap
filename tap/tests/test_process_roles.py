"""One image, several start commands: the process roles in `tap/serving.py`.

The default role, `all`, must stay byte-for-byte the shape every existing stack runs.
The split roles must add up to that shape, so splitting a deployment moves work between
containers without adding or dropping a queue, a dispatcher, or the recurring tick.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.conf import settings

from tap import serving
from tap.db_aliases import ALL_ALIASES

_REPO_ROOT = Path(settings.BASE_DIR)
_SPLIT = (serving.ROLE_WEB, serving.ROLE_WORKER, serving.ROLE_SCHEDULER)


@pytest.mark.spec("req-tap-serving-process-roles-1")
def test_unset_role_is_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAP_PROCESS_ROLE", raising=False)
    assert serving.process_role() == serving.ROLE_ALL


@pytest.mark.spec("req-tap-serving-process-roles-1")
def test_unknown_role_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAP_PROCESS_ROLE", "cron")
    with pytest.raises(ValueError, match="TAP_PROCESS_ROLE"):
        serving.process_role()


@pytest.mark.spec("req-tap-serving-process-roles-1")
def test_all_is_the_full_queue_shape() -> None:
    assert serving.role_queue_threads(serving.ROLE_ALL) == serving.QUEUE_THREADS
    assert serving.role_dispatchers(serving.ROLE_ALL) == serving.QUEUE_DISPATCHERS
    assert serving.role_runs_recurring(serving.ROLE_ALL)


@pytest.mark.spec("req-tap-serving-process-roles-2")
def test_split_roles_add_up_to_all() -> None:
    threads: dict[str, int] = {}
    for role in _SPLIT:
        for queue, count in serving.role_queue_threads(role).items():
            assert queue not in threads, f"{queue} is worked by two roles"
            threads[queue] = count
    assert threads == serving.QUEUE_THREADS
    assert sum(serving.role_dispatchers(r) for r in _SPLIT) == serving.QUEUE_DISPATCHERS
    assert [r for r in _SPLIT if serving.role_runs_recurring(r)] == [serving.ROLE_SCHEDULER]


@pytest.mark.spec("req-tap-serving-process-roles-2")
def test_web_and_migrate_run_no_background_work() -> None:
    for role in (serving.ROLE_WEB, serving.ROLE_MIGRATE):
        assert serving.role_queue_threads(role) == {}
        assert serving.role_dispatchers(role) == 0
        assert not serving.role_runs_recurring(role)


@pytest.mark.spec("req-tap-serving-process-roles-1")
def test_all_role_budget_matches_the_existing_budget() -> None:
    """Without the admin allowance, the `all` role is exactly today's serving demand."""
    assert (
        serving.role_connection_budget(serving.ROLE_ALL) + serving.ADMIN_SESSION_HEADROOM == serving.connection_budget()
    )


@pytest.mark.spec("req-tap-serving-process-roles-2")
def test_split_budgets_sum_to_the_all_budget() -> None:
    """Splitting costs one extra supervisor per queue container, and nothing else."""
    split = sum(serving.role_connection_budget(r) for r in _SPLIT)
    aliases = len(ALL_ALIASES)
    extra_supervisors = 1
    assert (
        split
        == serving.role_connection_budget(serving.ROLE_ALL)
        + extra_supervisors * aliases * serving.RESTART_OVERLAP_FACTOR
    )


@pytest.mark.spec("req-tap-serving-process-roles-2")
def test_settings_follow_the_role_in_force() -> None:
    """The settings module built STEADY_QUEUE from the role this process runs."""
    queues = [w.queues for w in settings.STEADY_QUEUE.workers]
    assert queues == [[q] for q in serving.role_queue_threads()]
    assert len(settings.STEADY_QUEUE.dispatchers) == serving.role_dispatchers()
    assert settings.STEADY_QUEUE.skip_recurring is not serving.role_runs_recurring()


@pytest.mark.spec("req-tap-serving-process-roles-3")
@pytest.mark.spec("req-tap-serving-process-roles-4")
def test_entrypoint_knows_every_role() -> None:
    text = (_REPO_ROOT / "docker" / "entrypoint.sh").read_text()
    accepted = "all|web|worker|scheduler|migrate"
    assert accepted in text
    assert set(accepted.split("|")) == set(serving.PROCESS_ROLES)
