"""`max_connections` is derived from the process model, not authored beside it.

`req-tap-serving-connection-budget`. PostgreSQL's default of 100 is what the demo-dev
stack hit head-on after 16 hours on 2026-09-15: 100 established connections, all from its
own web container, every request and steady_queue's own heartbeat failing with "sorry, too
many clients already" (tap#460, tap#471). A ceiling nobody computed is not a budget; it is
the absence of one wearing a budget's clothes.

WHAT IS OBSERVED HERE: the arithmetic, that it reads the configuration actually in force,
and that the two compose files declare what it computes. WHAT IS NOT: whether a running
instance stays under the ceiling (`req-tap-serving-connection-budget-2`) or survives a
rolling restart (`-4`). Both need a loaded instance, neither is exercised by anything in
this suite, and both are recorded as NOT OBSERVED in `specs/spec-tap-serving.md`. A
passing config test must never be read as a load test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.conf import settings

from tap import db_aliases, serving

_REPO_ROOT = Path(settings.BASE_DIR)
_COMPOSE_FILES = (_REPO_ROOT / "docker-compose.yml", _REPO_ROOT / "docker-compose.ci.yml")


def _declared_max_connections(path: Path) -> list[int]:
    return [int(m) for m in re.findall(r"max_connections=(\d+)", path.read_text())]


@pytest.mark.spec("req-tap-serving-connection-budget-1")
def test_every_compose_file_declares_the_derived_ceiling() -> None:
    """YAML cannot import Python, so the number is declared and VERIFIED — the same
    declare-and-check shape the heartbeat mount and the stop allowance already use.

    Both files, deliberately: the CI overlay REPLACES the base `command:`, so a ceiling
    set only in the base file would leave every CI lane on PostgreSQL's default while the
    dev stack ran on the budget — the two environments differing in the one property the
    2026-09-15 incident turned on.
    """
    expected = serving.development_connection_budget()
    for path in _COMPOSE_FILES:
        assert _declared_max_connections(path) == [expected], f"{path.name} declares the wrong ceiling"


@pytest.mark.spec("req-tap-serving-connection-budget-1")
def test_the_alias_count_is_the_configured_alias_set() -> None:
    """The multiplier is TRUE, not merely declared.

    `ALL_ALIASES` is what the budget multiplies by. If a third alias were configured and
    this tuple were not updated, the ceiling would keep its old answer and read as
    derived — a presence test wearing a correctness test's clothes.
    """
    assert set(db_aliases.ALL_ALIASES) == set(settings.DATABASES)


@pytest.mark.spec("req-tap-serving-connection-budget-3")
def test_the_queue_thread_counts_move_the_ceiling() -> None:
    """The per-process undercount this guards: "one connection per worker" is true of
    gunicorn sync workers and false of steady_queue, whose threads each hold their own."""
    base = serving.connection_budget(web_workers=3, aliases=2)
    more_threads = dict(serving.QUEUE_THREADS)
    more_threads["default"] += 1
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(serving, "QUEUE_THREADS", more_threads)
        assert serving.connection_budget(web_workers=3, aliases=2) > base


@pytest.mark.spec("req-tap-serving-connection-budget-1")
def test_the_web_worker_count_moves_the_ceiling() -> None:
    assert serving.connection_budget(web_workers=6, aliases=2) > serving.connection_budget(web_workers=3, aliases=2)


@pytest.mark.spec("req-tap-serving-connection-budget-3")
def test_steady_queue_is_configured_from_the_same_constants_the_budget_reads() -> None:
    """One fact, two readers. Raising a queue's threads in `tap/serving.py` raises both
    the running worker configuration and the ceiling derived from it; a second copy in
    settings would have let them disagree silently, which is how capacity looks configured
    right up to the moment it is not."""
    configured = {worker.queues[0]: worker.threads for worker in settings.STEADY_QUEUE.workers}
    assert configured == serving.QUEUE_THREADS
    assert len(settings.STEADY_QUEUE.dispatchers) == serving.QUEUE_DISPATCHERS


@pytest.mark.spec("req-tap-serving-connection-budget-1")
def test_the_serving_budget_excludes_the_test_lane() -> None:
    """The xdist allowance is a property of the development cluster, not of the product.

    Named as its own function so a deployment's ceiling is not quietly inflated by the
    test harness — and so the difference between the two numbers stays legible.
    """
    assert serving.connection_budget() < serving.development_connection_budget()
