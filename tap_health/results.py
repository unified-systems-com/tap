"""Structured health result + report types and their projections.

req-tap-health-service-3, req-tap-health-exposure (spec-tap-health-v0.md).

A probe returns a `ProbeResult` carrying explicit machine fields (`status`,
`critical`, `group`, a stable `code` for non-healthy results) alongside
optional human prose (`detail`, `reasoning`) and a structured `context` dict.
A programmatic actor branches on `status`/`code`, never on prose (Law 4,
docs/misc/agent-affordance-laws.md).

`HealthReport` aggregates per-probe results into an overall verdict and offers
two projections:

- `full()` — everything, for trusted surfaces (the internal service, the CLI).
- `scorecard()` — per-probe `status` + overall verdict only, **never** detail,
  reasoning, context, or code. The scorecard is a security boundary
  (req-tap-health-exposure-3); a load-bearing test proves it strips the rich
  fields. No endpoint exposes it in this version (the unauthenticated `/healthz`
  is parked, req-tap-health-exposure-4) — it exists for a future,
  deliberately-stood-up external surface.

The four-state model: overall is `unhealthy` if any *critical* probe is
`unhealthy`; else `degraded` if any probe is `degraded` **or a non-critical
probe is `unhealthy`** (non-blocking but never hidden as healthy); else
`healthy`. `unknown` never flips the verdict but is never dropped — it is
always visible per-probe (Law 1, Preserve Truth).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProbeStatus(StrEnum):
    """The four health states. `StrEnum` so values serialize as plain strings."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


def exception_detail(exc: BaseException) -> str:
    """Return the bounded, authored `detail` for a probe that caught `exc`.

    A probe's `detail` is "a short human string" (`req-tap-health-service-3`) and
    a raw `str(exc)` is neither short nor authored. It is an *unbounded* string
    the probe never wrote, and every projection carries it: the CLI's `full()`,
    the spawn gate's CI log, and — since `req-tap-health-exposure-6` — the image
    `HEALTHCHECK`'s stdout, which Docker concatenates into the container's
    `State.Health.Log` every 120s for the life of the container, where any reader
    of `docker inspect` and any monitoring agent that scrapes container state
    collects it. A psycopg `OperationalError` routinely carries host, port and
    role; nothing proves a DSN or credential material cannot reach that message
    on some path, and Docker's per-entry truncation is not redaction.

    So the exception's TYPE name is what escapes, never its message. This is the
    shape `_probe_serving` already uses for the HTTP probes, promoted to the one
    function every probe calls: DERIVE the fact once (remedy 1) so a probe that
    routes its caught exception through here *cannot* leak a message, and no
    projection downstream has to strip one. It is deliberately not a redactor —
    a regex that strips things that look like passwords would be drift-detection
    wearing prevention's clothes, and would still ship the lie first.

    The status `code` is what a consumer branches on (Law 4) and the probe name
    says which probe failed, so a bounded detail costs an operator nothing they
    were supposed to be reading anyway.

    Args:
        exc: The exception a probe caught.

    Returns:
        The exception's class name, e.g. `"OperationalError"`.
    """
    return type(exc).__name__


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of one probe execution.

    Construct via the `ProbeResult.*` classmethods so the machine fields stay
    consistent. `code` is required for any non-healthy result and omitted for a
    healthy one; it is a stable, probe-namespaced token a consumer branches on.
    """

    status: ProbeStatus
    code: str | None = None
    detail: str | None = None
    reasoning: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A stable `code` is the machine contract for any non-healthy result
        # (Law 4); enforce it so a programmatic consumer never meets a coded
        # gap. Healthy results carry no code. Constructing an invalid result is
        # a probe bug — it surfaces (via service isolation) as `probe.raised`.
        if self.status is not ProbeStatus.HEALTHY and not self.code:
            raise ValueError(f"A {self.status.value!r} ProbeResult requires a stable `code`.")

    @classmethod
    def healthy(cls, *, detail: str | None = None, context: dict[str, Any] | None = None) -> ProbeResult:
        return cls(status=ProbeStatus.HEALTHY, detail=detail, context=context or {})

    @classmethod
    def degraded(
        cls,
        code: str,
        *,
        detail: str | None = None,
        reasoning: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProbeResult:
        return cls(ProbeStatus.DEGRADED, code=code, detail=detail, reasoning=reasoning, context=context or {})

    @classmethod
    def unhealthy(
        cls,
        code: str,
        *,
        detail: str | None = None,
        reasoning: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProbeResult:
        return cls(ProbeStatus.UNHEALTHY, code=code, detail=detail, reasoning=reasoning, context=context or {})

    @classmethod
    def unknown(cls, code: str, *, detail: str | None = None, context: dict[str, Any] | None = None) -> ProbeResult:
        return cls(ProbeStatus.UNKNOWN, code=code, detail=detail, context=context or {})


@dataclass(frozen=True)
class ProbeOutcome:
    """A probe's identity (name/group/critical) joined to its `ProbeResult`.

    The report holds a list of these; the registry supplies name/group/critical
    and the probe call supplies the result.
    """

    name: str
    group: str
    critical: bool
    result: ProbeResult


# Overall-verdict precedence: a critical unhealthy is worst, then degraded.
_DEGRADED = ProbeStatus.DEGRADED
_UNHEALTHY = ProbeStatus.UNHEALTHY


@dataclass(frozen=True)
class HealthReport:
    """Aggregate of per-probe outcomes with an overall verdict and projections.

    `selection` names the set that was run (req-tap-health-selection). It is
    carried on the report because a verdict is only meaningful alongside the
    question it answers — "healthy" for `liveness` and "healthy" for `readiness`
    are different claims.
    """

    outcomes: tuple[ProbeOutcome, ...]
    selection: str

    @property
    def status(self) -> ProbeStatus:
        """Overall four-state verdict (see module docstring).

        A *critical* unhealthy is `unhealthy`. A *non-critical* unhealthy, or any
        `degraded`, is `degraded` — never hidden as `healthy` (Law 1, Preserve
        Truth): the overall verdict stays non-blocking but stays honest.

        An **empty** selection is `unknown`, never `healthy`: a green verdict
        earned by running no probes would be a claim nothing supports. `ok` stays
        True, so an orchestrator does not act (e.g. restart) on the strength of a
        question no probe answered.
        """
        if not self.outcomes:
            return ProbeStatus.UNKNOWN
        if any(o.critical and o.result.status is _UNHEALTHY for o in self.outcomes):
            return ProbeStatus.UNHEALTHY
        if any(o.result.status in (_UNHEALTHY, _DEGRADED) for o in self.outcomes):
            return ProbeStatus.DEGRADED
        return ProbeStatus.HEALTHY

    @property
    def ok(self) -> bool:
        """True unless a critical probe is unhealthy — the CLI exit-code basis.

        A non-critical failure surfaces as `degraded` (truthful) but keeps `ok`
        True, so the gate stays non-blocking on non-critical probes.
        """
        return self.status is not ProbeStatus.UNHEALTHY

    def full(self) -> dict[str, Any]:
        """Trusted projection: every field of every probe (Law 4 machine view).

        For internal callers and the CLI. Carries the rich `detail`/`reasoning`/
        `context` and the stable `code`.
        """
        checks: dict[str, dict[str, Any]] = {}
        for o in self.outcomes:
            entry: dict[str, Any] = {
                "status": o.result.status.value,
                "critical": o.critical,
                "group": o.group,
            }
            if o.result.code is not None:
                entry["code"] = o.result.code
            if o.result.detail is not None:
                entry["detail"] = o.result.detail
            if o.result.reasoning is not None:
                entry["reasoning"] = o.result.reasoning
            if o.result.context:
                entry["context"] = o.result.context
            checks[o.name] = entry
        # `selection` rides the trusted projection only: it tells a consumer which
        # question this verdict answers. The coarse scorecard is left untouched —
        # its shape is a tested security boundary (req-tap-health-exposure-3) and
        # no external surface consumes it today.
        return {"status": self.status.value, "selection": self.selection, "checks": checks}

    def scorecard(self) -> dict[str, Any]:
        """Coarse projection: per-probe `status` + overall verdict ONLY.

        A security boundary (req-tap-health-exposure-3): it must never carry
        `detail`, `reasoning`, `context`, or `code`. The leak-test asserts this.
        """
        return {
            "status": self.status.value,
            "checks": {o.name: {"status": o.result.status.value} for o in self.outcomes},
        }


__all__ = ["ProbeStatus", "ProbeResult", "ProbeOutcome", "HealthReport", "exception_detail"]
