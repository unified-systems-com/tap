"""The image declares a health check, and that declaration cannot be a lie.

`req-tap-health-exposure-6` (specs/spec-tap-health-v0.md). The `web` container shipped
with no `HEALTHCHECK` at all, so a wedged instance and a serving one were
indistinguishable to Docker — the shape of the 2026-09-15 outage, where both containers
read `up` for nineteen hours while the site was dead (tap#521).

What this module protects is the part a runtime observation would NOT catch cheaply: the
instruction is a string in a Dockerfile, and a typo in it fails in a way that *looks like
a health failure*. Docker's health contract is `0` healthy, `1` unhealthy, and **`2`
reserved, documented "do not use"** — while `manage.py health` exits `2` on a usage error
(`EXIT_USAGE`: no `--set`, or an unknown selection name) and argparse exits `2` on an
unknown flag. So the test does not merely assert that a `HEALTHCHECK` line is PRESENT; it
takes the instruction's own argv and feeds it to the health command's own parser, and
checks the `--set` value against `tap_health.selection.SELECTION_NAMES`. The claim is
verified against its source rather than re-typed here (remedy 2 of the
presence-is-not-correctness ladder); a `2 -> 1` wrapper script was rejected because it
would mask a configuration error as an outage instead of preventing it.

HONEST LIMITS — three states, never two. These tests read the Dockerfile as text. They
prove the declaration is well-formed and internally coherent. They do NOT and cannot
observe:

- that a freshly built image's `docker inspect` carries the instruction,
- that a container reaches `healthy` after a normal boot without flapping to `unhealthy`,
- that stopping the database drives it `unhealthy` within `interval x retries`.

Those need a built image and a running stack, which this suite does not have. They are
**NOT OBSERVED**, not "passing" — see the PR for the handover.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from tap_health.management.commands.health import Command as HealthCommand
from tap_health.registry import health_probe_registry
from tap_health.selection import SELECTION_NAMES, selects

_REPO_ROOT = Path(settings.BASE_DIR)
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_ENTRYPOINT = _REPO_ROOT / "docker" / "entrypoint.sh"

#: Pre-boot, migrate and plugin seeding take roughly this long on a normal start. The
#: `--start-period` must cover it, because a container that flaps to `unhealthy` during a
#: NORMAL startup teaches operators to ignore the signal.
_MEASURED_BOOT_SECONDS = 180


# ---------------------------------------------------------------------------
# Dockerfile reading — one parse, shared by every assertion below
# ---------------------------------------------------------------------------


def _logical_instructions(dockerfile: str) -> list[str]:
    """The Dockerfile's instructions with comments dropped and continuations joined."""
    instructions: list[str] = []
    buffer = ""
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            buffer += line[:-1].strip() + " "
            continue
        instructions.append((buffer + line).strip())
        buffer = ""
    if buffer:
        instructions.append(buffer.strip())
    return instructions


def _stage_of_healthcheck() -> tuple[str, str]:
    """The `(stage_name, instruction)` of the single `HEALTHCHECK`, else fail loudly."""
    stage = "<implicit>"
    found: list[tuple[str, str]] = []
    for instruction in _logical_instructions(_DOCKERFILE.read_text()):
        head = instruction.split(maxsplit=1)[0].upper()
        if head == "FROM":
            parts = instruction.split()
            upper = [p.upper() for p in parts]
            stage = parts[upper.index("AS") + 1] if "AS" in upper else "<unnamed>"
        elif head == "HEALTHCHECK":
            found.append((stage, instruction))
    assert len(found) == 1, f"expected exactly one HEALTHCHECK instruction, found {len(found)}: {found}"
    return found[0]


def _split_healthcheck(instruction: str) -> tuple[dict[str, str], list[str]]:
    """Split a `HEALTHCHECK` into its `--flag=value` options and the CMD's exec-form argv.

    Fails on shell form deliberately: shell form runs the probe through `/bin/sh -c`,
    which would let the shell's own exit conventions (127 for "not found", 126 for "not
    executable") stand in for the health verdict, and would lose the direct-exec property
    the venv interpreter path depends on.
    """
    tokens = shlex.split(instruction)
    assert tokens[0].upper() == "HEALTHCHECK"
    assert "CMD" in [t.upper() for t in tokens], f"HEALTHCHECK has no CMD: {instruction}"
    cmd_index = [t.upper() for t in tokens].index("CMD")

    options: dict[str, str] = {}
    for token in tokens[1:cmd_index]:
        assert token.startswith("--") and "=" in token, f"unparsable HEALTHCHECK option {token!r}"
        flag, _, value = token.partition("=")
        options[flag] = value

    payload = instruction[instruction.upper().index("CMD") + len("CMD") :].strip()
    assert payload.startswith("["), f"HEALTHCHECK must use exec form (a JSON array), got: {payload!r}"
    argv: list[str] = json.loads(payload)
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    return options, argv


def _seconds(value: str) -> int:
    """A Docker duration string (`120s`, `4m`, `1m30s`) as whole seconds."""
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", value)
    assert match and any(match.groups()), f"unparsable duration {value!r}"
    hours, minutes, secs = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + secs


@pytest.fixture(scope="module")
def healthcheck() -> tuple[str, dict[str, str], list[str]]:
    stage, instruction = _stage_of_healthcheck()
    options, argv = _split_healthcheck(instruction)
    return stage, options, argv


# ---------------------------------------------------------------------------
# req-tap-health-exposure-6 — the declaration exists, in the artifact
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_health_check_is_declared_in_the_image_not_only_in_compose(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """A compose-only health check is absent from the published artifact.

    That is the tap#502 failure shape: a property asserted in one place and untrue in the
    thing that ships. Declared in the `app` stage, both FIPS variants inherit it, so
    `docker run` and any orchestrator get it too. Compose may still override; it may not
    be the only home.
    """
    stage, _options, _argv = healthcheck
    assert stage == "app", f"HEALTHCHECK is declared in stage {stage!r}; both FIPS variants branch from `app`"


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_health_check_runs_the_network_free_cli_in_the_session_venv(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """It reuses the tier-1 CLI projection — no endpoint, no route, no listening socket.

    The interpreter is named absolutely because a health check inherits none of the
    environment `docker/entrypoint.sh` exports for the server; the venv it names is
    derived from that entrypoint rather than re-typed, so the two cannot drift apart.
    """
    _stage, _options, argv = healthcheck

    venv = re.search(r"^export VIRTUAL_ENV=(\S+)$", _ENTRYPOINT.read_text(), re.MULTILINE)
    assert venv, "docker/entrypoint.sh no longer exports VIRTUAL_ENV; re-derive the interpreter path"
    assert argv[0] == f"{venv.group(1)}/bin/python", argv

    assert argv[1].endswith("manage.py"), argv
    assert argv[2] == "health", argv


# ---------------------------------------------------------------------------
# req-tap-health-exposure-6 — the reserved exit code cannot be reached
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_instruction_argv_is_accepted_by_the_health_commands_own_parser(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """Docker reserves exit code 2; `manage.py health` spends it on usage errors.

    Both of the command's exit-2 paths are argument-shaped — argparse rejecting an
    unknown flag, and the command's own `_usage_error` on a missing or unknown `--set`.
    So the argv baked into the image is parsed HERE by the same parser that would refuse
    it there. A typo fails this test instead of presenting a configuration error to
    Docker as a health failure with undefined behaviour.
    """
    from django.core.management.base import CommandError

    _stage, _options, argv = healthcheck
    parser = HealthCommand().create_parser("manage.py", "health")

    try:
        parsed: dict[str, Any] = vars(parser.parse_args(argv[3:]))
    except (CommandError, SystemExit) as exc:  # pragma: no cover - the failure we exist to catch
        pytest.fail(f"the HEALTHCHECK argv {argv[3:]} is a usage error for `manage.py health`: {exc}")

    selection = parsed.get("selection")
    assert selection, "the HEALTHCHECK must name a selection; a missing --set exits 2, which Docker reserves"
    assert selection in SELECTION_NAMES, (
        f"the HEALTHCHECK names selection {selection!r}, which `manage.py health` would refuse with the "
        f"reserved exit code 2. Valid selections: {', '.join(SELECTION_NAMES)}."
    )


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_selected_set_actually_contains_probes(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """A selection that resolves to zero probes reports `unknown`, never `healthy`.

    `liveness` is the trap: it is deliberately empty (dependency failures are not
    restart-fixable), so a container health check pointed at it would be a green light
    earned by checking nothing — and would never go green at all. This asserts the
    declared set has members, rather than asserting the literal string `readiness`, so it
    keeps holding if the set vocabulary changes underneath it.
    """
    _stage, _options, argv = healthcheck
    selection = argv[argv.index("--set") + 1]

    members = [
        name for name in health_probe_registry.keys() if selects(health_probe_registry.get(name).sets, selection)
    ]
    assert members, f"selection {selection!r} resolves to no probes; it can only ever report `unknown`"


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_selected_set_still_exercises_the_serving_process(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """A health check that only reached dependencies could not see the outage it exists for.

    Most readiness probes run in the calling process and stay green while the web worker is
    dead. `http.web` and `http.api` are the exceptions: they GET the loopback
    `TAP_HEALTH_SELF_URL` and read the *authentication* responses (302 into the login wall,
    401 on the API) as proof that the WSGI stack, middleware chain and auth layer executed.
    Drop them from `readiness` and the container check silently becomes blind to a wedged
    gunicorn while still reporting `healthy` — the precise failure it was added to end.

    HONEST NOTE: the two probe NAMES are the one fact this module authors rather than
    derives. There is no machine-readable "exercises the server" flag to key off; if one is
    ever added, this assertion should key off that instead.
    """
    _stage, _options, argv = healthcheck
    selection = argv[argv.index("--set") + 1]

    members = {
        name for name in health_probe_registry.keys() if selects(health_probe_registry.get(name).sets, selection)
    }
    assert {"http.web", "http.api"} <= members, (
        f"selection {selection!r} no longer includes the probes that exercise the serving process "
        f"(http.web / http.api); the container health check would report `healthy` through a wedged server. "
        f"Members: {sorted(members)}"
    )


# ---------------------------------------------------------------------------
# req-tap-health-exposure-6 — the numbers are coherent with the rest of the stack
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_timeout_sits_inside_the_stacks_other_time_bounds(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """`--timeout` is the ONLY bound on a hung probe, and it must not be the longest one.

    `run_health()` has no runner-level time budget in v0 — the http probes carry their own
    2s socket timeout, the `db` probe carries none — so Docker's timeout is what stops a
    wedged check. Two ceilings bound it: it must not exceed the statement bound every
    other database wait in this stack uses (derived from settings, never re-typed), and it
    must be shorter than the interval, or checks would overlap themselves.
    """
    _stage, options, _argv = healthcheck
    timeout = _seconds(options["--timeout"])
    interval = _seconds(options["--interval"])

    statement_bound = _seconds(settings.SEARCH_STATEMENT_TIMEOUT)
    assert timeout <= statement_bound, (
        f"--timeout={timeout}s exceeds the {statement_bound}s statement bound "
        "(settings.SEARCH_STATEMENT_TIMEOUT); the health check would outlive the database wait it reports on"
    )
    assert timeout < interval, f"--timeout={timeout}s must be shorter than --interval={interval}s"


@pytest.mark.spec("req-tap-health-exposure-6")
def test_the_start_period_covers_a_normal_boot(
    healthcheck: tuple[str, dict[str, str], list[str]],
) -> None:
    """A container must never flap to `unhealthy` while it is legitimately still booting.

    Failures inside `--start-period` do not count toward `--retries` and the container
    reads `starting`. Pre-boot, migrate and plugin seeding take ~180s, so anything at or
    below that would report a normal startup as a fault — and a signal that cries wolf on
    every boot is a signal operators learn to ignore.
    """
    _stage, options, _argv = healthcheck
    start_period = _seconds(options["--start-period"])
    assert start_period > _MEASURED_BOOT_SECONDS, (
        f"--start-period={start_period}s does not clear the measured ~{_MEASURED_BOOT_SECONDS}s boot"
    )
    assert int(options["--retries"]) >= 2, "one failed probe must not flip a container; transient blips exist"
