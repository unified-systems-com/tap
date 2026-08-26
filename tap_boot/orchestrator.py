"""The bootloader orchestrator — fixed-phase standup (req-boot-phases).

TAP-IMPLEMENTS: req-boot-app@45a8b458c10d/39bdd0735a76 (derivation) — run_boot is the single
    canonical standup path the command and the spawn bridge both invoke.

TAP-IMPLEMENTS: req-boot-phases@5d4471b4925b/39bdd0735a76 (derivation) — the fixed,
    code-defined phase order lives here; profiles cannot reorder it.

`run_boot` is the single canonical standup path for both dev (`spawn-session.sh`,
req-boot-spawn-bridge) and customer deployments. It runs the v0 phase order
**auth → population**:

- **auth** — `tap_auth.sync_auth()` (capabilities → protected groups → built-in
  program actors, incl. `tap_bootloader`) then `ensure_initial_admin()`. The boot
  actor is resolved here, *after* `sync_auth` mints it (the v0 collapse of the
  fuller `bootstrap` pre-phase: nothing writes through the service layer before
  auth, so no earlier actor is needed — spec v0 Scope).
- **population** — bound `acting_as(tap_bootloader)`: pre-resolve every enabled
  step against in-memory registries (unknown plugin/collector/bundle aborts before
  ANY grid mutation, req-boot-population-4), *then* reconcile collector grid nodes,
  then apply the ordered `seed-plugin` / `fire-collector` steps.

Phases are plain functions so each becomes a registered section-handler body when
that framework lands (req-boot-sections) — an additive refactor, not a rewrite.
The deferred section/registry/two-layer-validate machinery is intentionally not
built here (spec v0 Scope).
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable
from types import FrameType
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from tap.flaws import HANDLING_OBSERVE_CONTINUE, flaw_class_for_path
from tap.preboot import resolve_var
from tap_auth.actors import BOOTLOADER, acting_as, get_builtin_actor
from tap_auth.sync import ensure_initial_admin, sync_auth
from tap_boot.profile import BootProfile, FireCollectorStep, PopulationStep, SeedPluginStep
from tap_boot.record import NullBootRecord

logger = logging.getLogger(__name__)

# Narrow, declared public surface. tap_boot is an un-gateable Family-B layer
# (spec-service-layer-boundary): it runs before the capability system exists, so
# its defense is surface-minimization, not gating. Only the three symbols the boot
# commands and profile-resolution guard import are exported; everything else —
# phase helpers, the collector-timeout default, the invocation self-check — is a
# module internal that no external caller should reach for.
__all__ = ["BootError", "check_profile", "run_boot"]

# A no-op writer keeps run_boot usable from tests/handlers that don't want stdout.
Echo = Callable[[str], None]
_SILENT: Echo = lambda _msg: None  # noqa: E731

# Default per-collector await timeout when a fire-collector step does not set its
# own `timeout_seconds`. Deliberately short — snappy collectors should finish well
# inside it; a slow collector (a full cloud pull) declares a higher value on its
# step. The better long-term home is a per-collector default the step overrides
# (see backlog req-boot-collector-timeout); v0 uses this single fallback.
DEFAULT_COLLECTOR_TIMEOUT_SECONDS = 90.0

# Await bound for one preflight self-test job (req-boot-obs-preflight). This bounds
# queue pickup + task overhead around the check, NOT the check itself — the check's
# own budget is the collector contract's self-test deadline (tap_cares readiness,
# req-tap-cares-collector-self-test-12), which is well inside this.
PREFLIGHT_AWAIT_TIMEOUT_SECONDS = 60.0


class BootError(Exception):
    """Raised when a phase cannot complete; the command maps it to a non-zero exit.

    `detail` is optional structured cause context — JSON-safe, secret-free — that
    rides the ABORT signal's `message_data["detail"]` and the boot record's abort
    block (req-boot-obs-abort-detail): the failing step label and, for collector
    failures, the failing self-test checks.
    """

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


# The only management commands expected to drive `run_boot`. Boot mints the
# capability system, so it runs *before* any gate exists and cannot itself be
# capability-gated (the un-gateable-layer variant of spec-service-layer-boundary:
# "can't gate before the gate exists"). Its runtime defense is a confirmed-positive
# context check — see `_check_boot_invocation_context`.
_ALLOWED_BOOT_COMMANDS = frozenset(
    {
        "tap_boot.management.commands.boot",
        "tap_boot.management.commands.cold_boot_gate",
    }
)


def _check_boot_invocation_context() -> None:
    """Detect — but do not block — an out-of-band `run_boot` invocation.

    A *confirmed-positive* check, deliberately not evidence-of-absence: it walks the
    call stack for a live `BaseCommand` instance from `_ALLOWED_BOOT_COMMANDS` —
    Django's `BaseCommand.execute() -> handle()` leaves the command object bound as
    `self` in a frame for the whole call, a stable public API rather than a fragile
    internal. A genuine boot-command frame cannot be forged from outside the boot
    path (the same instinct as spec-tap-callsite-identity: prove identity from
    structure, not from a self-asserted marker an illegitimate caller could also set).

    **Detection, not prevention (a tripwire, not a wall).** When the frame is absent
    this does NOT raise — it emits a `security`-tagged Flaw (handling
    `observe_continue`) and lets boot proceed. A hard fail here would be the worst kind
    of footgun: any drift in this heuristic (a Django internals change, a legitimate
    new invocation path) would brick every boot, while a real attacker who can already
    execute in-process gains almost nothing from the block — they can call the phase
    primitives directly. So the asymmetry runs the other way from most guards: the
    block's cost is catastrophic and its value marginal. What is genuinely valuable is
    the *signal* — an out-of-band boot invocation is a high-signal anomaly worth
    routing to incident response — so we record it loudly and continue (WARN_ON_ONCE,
    not BUG_ON). Residual risk named deliberately (spec-security-posture honest-risk):
    a malicious in-process caller CAN still complete an out-of-band boot; this surface
    alerts, it does not prevent.

    The test runner is the trusted exception: it drives `run_boot` directly and
    repeatedly, keyed on the deploy-controlled `TAP_TEST_MODE` settings flag (set only
    by the test settings, never reachable by request-time caller code) — so it neither
    trips the tripwire nor spams Flaws.
    """
    if getattr(settings, "TAP_TEST_MODE", False):
        return  # trusted: the test runner drives boot directly, outside any command
    frame: FrameType | None = sys._getframe(1)
    caller_filename = frame.f_code.co_filename if frame is not None else None
    while frame is not None:
        candidate = frame.f_locals.get("self")
        if isinstance(candidate, BaseCommand) and type(candidate).__module__ in _ALLOWED_BOOT_COMMANDS:
            return  # confirmed positive: an allowed boot command is driving this call
        frame = frame.f_back
    # No allowed boot-command frame: run_boot was reached out of band. Blame by where
    # the immediate caller lives (a plugin under plugins/ is an AppFlaw; first-party
    # code is a CodeFlaw), matching the service-layer-bypass security Flaws.
    flaw_cls = flaw_class_for_path(caller_filename)
    flaw_cls.report(
        invariant_id="boot_invoked_out_of_band",
        tags=["security"],
        handling=HANDLING_OBSERVE_CONTINUE,
        message=(
            "run_boot() was invoked outside an allowed boot management command "
            "(manage.py boot / cold_boot_gate). Boot runs before the capability system "
            "exists, so this path cannot be capability-gated; the invocation is recorded "
            "for incident-response review and allowed to proceed, not blocked. Confirm the "
            "caller is a legitimate standup path."
        ),
        logger=logger,
        detected_caller=caller_filename or "<unknown>",
    )


def run_boot(profile: BootProfile | None, *, echo: Echo | None = None, record: NullBootRecord | None = None) -> None:
    """Stand the instance up: auth phase, then (if the profile has steps) population.

    `profile` is None for an auth-only standup (an intentional `--allow-empty`
    run, req-boot-profile-4). Raises `BootError` on any phase failure, after
    logging the offending section/step (req-boot-report).

    `record` is the run's durable boot record (req-boot-obs-record) — pass a
    `BootRecord` to persist phases/steps/outcome; None runs record-free (the
    boot command passes one; tests and library callers may omit it). The record
    is finalized here on both the success and abort paths, so an aborting boot
    still leaves its evidence.
    """
    _check_boot_invocation_context()
    say = echo or _SILENT
    rec = record if record is not None else NullBootRecord()
    profile_label = profile.profile_id if profile else "(none — auth only)"
    logger.info("[c13a] boot starting: profile=%s", profile_label)
    say(f"Boot starting (profile: {profile_label}).")

    try:
        with rec.phase("auth"):
            _phase_auth(profile, say)

        with rec.phase("grid_infra"):
            _phase_grid_infra(say)

        if profile is None or not profile.has_population:
            logger.info("[f89d] boot: no population steps; auth-only standup complete")
            say("No population steps — auth-only standup complete.")
            rec.finish_ok()
            return

        # The boot actor is resolved after sync_auth mints it and bound for every
        # population write (req-boot-phases-3: no boot write is User=None).
        bootloader = get_builtin_actor(BOOTLOADER)
        with acting_as(bootloader), rec.phase("population"):
            _phase_population(profile, bootloader, say, rec)
    except BootError as exc:
        rec.finish_aborted("boot", str(exc), data=exc.detail)
        raise
    except Exception as exc:
        # Unexpected failure classes (AuthSyncError, infrastructure errors) still
        # finalize the record — the evidence must exist precisely when things broke.
        rec.finish_aborted("boot", str(exc))
        raise

    logger.info("[9e9b] boot complete: profile=%s", profile_label)
    say("Boot complete.")
    rec.finish_ok()


def check_profile(profile: BootProfile | None, *, echo: Echo | None = None) -> int:
    """Resolve-only preflight: validate every enabled step, mutate nothing.

    Runs the zero-grid-mutation pre-resolution `run_boot` does before the
    population phase (`_resolve_steps`) — every `seed-plugin` slug/bundle and
    every `fire-collector` key is checked against the in-memory registries — but
    stops there: no auth sync, no DB writes, no collector firing. This is the
    per-profile cold-boot smoke's engine: a shipped profile whose collector key
    has rotted (the module-path→slug drift class) or whose plugin/bundle is
    missing fails here, offline, without standing anything up.

    Returns the number of enabled population steps that resolved. Raises
    `BootError` on the first unresolvable step (same failure the real boot
    would hit at `_resolve_steps`, only sooner and side-effect-free).
    """
    say = echo or _SILENT
    profile_label = profile.profile_id if profile else "(none — auth only)"
    if profile is None or not profile.has_population:
        say(f"Profile '{profile_label}': no population steps to resolve (auth-only).")
        return 0
    plan = _resolve_steps(profile, say)
    say(f"Profile '{profile_label}': {len(plan)} population step(s) resolved cleanly.")
    return len(plan)


def _phase_auth(profile: BootProfile | None, say: Echo) -> None:
    """auth phase: hard-sync capabilities/groups/actors, ensure the admin, then
    (if the profile declares one) validate + apply the auth section."""
    logger.info("[0b5f] boot auth phase: sync_auth")
    say("Auth phase: syncing capabilities, protected groups, built-in actors ...")
    sync_auth()

    admin = ensure_initial_admin()
    if admin is not None:
        say(f"Auth phase: initial admin '{admin.get_username()}' ensured (joined tap_admin).")
    else:
        say("Auth phase: no DJANGO_SUPERUSER_USERNAME set; skipped initial-admin bootstrap.")

    if profile is not None and profile.has_auth:
        from django.conf import settings

        from tap_auth.boot import AuthBootError, apply_auth_boot_section

        logger.info("[b2d4] boot auth phase: applying auth section (providers, last-admin, deploy gate)")
        say("Auth phase: validating + applying auth section ...")
        try:
            apply_auth_boot_section(profile.auth or {}, deploy=not settings.DEBUG, echo=say)
        except AuthBootError as exc:
            raise BootError(f"auth section: {exc}") from exc


def _phase_grid_infra(say: Echo) -> None:
    """grid-infrastructure phase: provision the least-privilege read-only search role.

    Runs post-migrate (the entrypoint runs `migrate` before `manage.py boot`), so every
    plugin table exists and the type registry is populated when the grant set is computed.
    Idempotent — reconciles `tap_gryphon_ro`'s grants to the current registry set each boot
    and pins its resource GUCs (req-boot-search-role, req-grid-search-readonly-role.sec).
    Always runs, even for an auth-only standup, because search is a core surface.
    """
    from django.conf import settings
    from django.db import connections

    from tap_grid.search_role import provision_search_role, search_role_name

    conn = connections["default"]
    tables = provision_search_role(
        conn,
        password=settings.SEARCH_READONLY_PASSWORD,
        database=conn.settings_dict["NAME"],
        gucs=settings.SEARCH_ROLE_GUCS,
    )
    logger.info("[0075] boot grid-infra: search role %s granted SELECT on %d tables", search_role_name(), len(tables))
    say(f"Grid-infra phase: provisioned {search_role_name()} (SELECT on {len(tables)} tables).")


def _phase_population(profile: BootProfile, bootloader: object, say: Echo, rec: NullBootRecord) -> None:
    """population phase: pre-resolve (no mutation), reconcile, preflight, apply ordered steps."""
    from tap_cares.registry import reconcile_collector_nodes

    # Pre-resolution happens FIRST, against in-memory registries only — so an
    # unknown plugin slug / collector key / bundle name aborts before ANY grid
    # mutation, including the collector-node reconcile below (req-boot-population-4).
    plan = _resolve_steps(profile, say)

    logger.info("[f193] boot population phase: reconciling collector nodes")
    say("Population phase: reconciling collector grid nodes ...")
    reconcile_collector_nodes()

    # Readiness preflight (req-boot-obs-preflight): self-test every collector the
    # profile will fire, before the first seed-plugin step mutates the grid. Under
    # abort semantics this raises with a batch verdict; under continue semantics it
    # returns the keys whose fire steps must be skipped (firing a collector that
    # just proved unready is wasted minutes, req-boot-obs-preflight-5).
    unready_keys = _preflight_collectors(profile, plan, say, rec)

    failures: list[str] = []
    for step in plan:
        label = _step_label(step)
        if isinstance(step, FireCollectorStep) and step.key in unready_keys:
            logger.warning("[9982] boot skipping fire-collector %s: preflight failed", step.key)
            say(f"  [fire-collector] {step.key} SKIPPED — preflight failed.")
            rec.record_step(
                {"type": "fire-collector", "key": step.key, "status": "skipped", "note": "preflight failed"}
            )
            failures.append(label)
            continue
        t0 = time.monotonic()
        ok, detail = _apply_step(step, bootloader, say)
        detail["status"] = "ok" if ok else "failed"
        detail["duration_seconds"] = round(time.monotonic() - t0, 3)
        rec.record_step(detail)
        if ok:
            continue
        failures.append(label)
        if profile.on_failure == "abort":
            logger.error("[ac13] boot population aborting on failed step: %s", label)
            raise BootError(
                f"Population step failed: {label}; on_failure=abort — stopping.",
                detail={"failed_step": label, "failing_checks": detail.get("failing_checks", [])},
            )

    if failures:
        raise BootError(
            f"Population completed with {len(failures)} failed step(s): {', '.join(failures)}.",
            detail={"failed_steps": failures},
        )

    logger.info("[cc13] boot population phase complete: %d step(s)", len(plan))


def _preflight_collectors(profile: BootProfile, plan: list[PopulationStep], say: Echo, rec: NullBootRecord) -> set[str]:
    """Preflight every enabled fire-collector before any seed mutates: two lanes.

    **Offline lane first** (req-boot-obs-preflight-6): presence + kind of every
    declared required secret (req-boot-required-secrets-5) — no network, read from
    the loaded envelope registry. **Live lane second**: each unique collector key
    self-tested once via the cares contract's sanctioned path —
    `run_collection(run_mode="self_test_only")` awaited to terminal — so readiness
    persists on `CollectionJob.self_test` (req-boot-obs-preflight-3). A collector
    whose declared secret failed offline skips its live self-test and fails with
    the offline reason (provisioning gap vs liveness gap, named apart).

    Runs after the collector-node reconcile (the job path needs the Collector grid
    nodes) and before the first `seed-plugin` step (req-boot-obs-preflight-1).
    Both lanes run to completion before any verdict (the batch answer,
    req-boot-obs-preflight-2). With `on_failure=abort` a failure raises, naming
    every failing collector and missing secret; otherwise the failing keys are
    returned so their fire steps are skipped. The toggle resolves env > profile >
    default-true (req-boot-obs-preflight-4); a skip is loud and covers both lanes.
    """
    fire_keys: list[str] = []
    fire_steps: dict[str, list[FireCollectorStep]] = {}
    for step in plan:
        if isinstance(step, FireCollectorStep):
            if step.key not in fire_keys:
                fire_keys.append(step.key)
            fire_steps.setdefault(step.key, []).append(step)
    if not fire_keys:
        return set()

    profile_section = (
        {} if profile.collector_preflight is None else {"collector_preflight": profile.collector_preflight}
    )
    resolved = resolve_var(
        "population", "collector_preflight", profile_section=profile_section, default=True, is_bool=True
    )
    rec.record_variable("population", "collector_preflight", resolved.value, resolved.source)
    if not resolved.value:
        # A disabled safety net must announce itself (same posture as the disabled
        # pre-migrate snapshot, req-boot-snapshot-2).
        logger.warning(
            "[dcf8] collector preflight DISABLED (source: %s) — firing without readiness checks", resolved.source
        )
        say(f"Population preflight: DISABLED (source: {resolved.source}) — collectors fire without readiness checks.")
        rec.record_step({"type": "preflight", "status": "skipped", "note": f"disabled (source: {resolved.source})"})
        return set()

    # ---- Offline lane: declared secret presence + kind (req-boot-obs-preflight-6,
    # req-boot-required-secrets-5). Reads only the profile + the loaded envelope
    # registry — no network — and runs BEFORE any live self-test, so an absent
    # secret (a provisioning gap: mint it) is distinguished from a dead credential
    # (a liveness gap: rotate it). Coherence at load guarantees every ref resolves
    # to a declared entry.
    missing_secrets, blocked = _preflight_required_secrets(profile, fire_keys, fire_steps, say, rec)

    from tap_cares.models import Collector
    from tap_cares.services import fire_collector_and_await

    say(f"Population preflight: self-testing {len(fire_keys)} collector(s) ...")
    logger.info("[15f1] boot preflight: self-testing %d collector(s)", len(fire_keys))

    failures: list[tuple[str, list[dict[str, Any]], str]] = []
    for key in fire_keys:
        if key in blocked:
            # A collector whose declared secret is unavailable cannot pass its live
            # self-test — skip the network call and fail it with the offline reason.
            refs = ", ".join(blocked[key])
            rec.record_step(
                {
                    "type": "preflight",
                    "key": key,
                    "status": "failed",
                    "note": f"required secret(s) unavailable: {refs} — live self-test skipped",
                }
            )
            failures.append((key, [], f"required secret(s) unavailable: {refs}"))
            say(f"    FAILED — preflight {key}: required secret(s) unavailable ({refs}); live self-test skipped.")
            continue
        collector = Collector.objects.get(collector_registry=key)
        t0 = time.monotonic()
        ok, job = fire_collector_and_await(
            collector,
            run_mode="self_test_only",
            manual_run_source="boot-preflight",
            timeout_seconds=PREFLIGHT_AWAIT_TIMEOUT_SECONDS,
        )
        entry: dict[str, Any] = {
            "type": "preflight",
            "key": key,
            "status": "ok" if ok else "failed",
            "duration_seconds": round(time.monotonic() - t0, 3),
            "job_id": _job_entity_id(job),
            "summary": job.summary or None,
        }
        if ok:
            say(f"  [preflight] {key} OK ")
        else:
            checks = _failing_checks(job, key)
            entry["failing_checks"] = checks
            failures.append((key, checks, job.summary or ""))
            logger.error("[244a] boot preflight failed for %s: %s", key, job.summary or "see CollectionJob")
            say(f"    FAILED — preflight {key}: {job.summary or 'see CollectionJob'}")
            _say_checks(checks, say)
        rec.record_step(entry)

    if not failures:
        return set()

    failing_keys = [key for key, _checks, _summary in failures]
    if profile.on_failure == "abort":
        all_checks = [c for _key, checks, _summary in failures for c in checks]
        parts = [f"Collector preflight failed for {len(failures)} collector(s): {', '.join(failing_keys)}"]
        if missing_secrets:
            refs = ", ".join(m["ref"] for m in missing_secrets)
            parts.append(f"{len(missing_secrets)} required secret(s) missing/mismatched: {refs}")
        detail: dict[str, Any] = {"failed_step": "preflight", "failing_checks": all_checks}
        if missing_secrets:
            detail["missing_secrets"] = missing_secrets
        raise BootError(
            "; ".join(parts) + "; on_failure=abort — stopping before any seed step ran.",
            detail=detail,
        )
    return set(failing_keys)


def _preflight_required_secrets(
    profile: BootProfile,
    fire_keys: list[str],
    fire_steps: dict[str, list[FireCollectorStep]],
    say: Echo,
    rec: NullBootRecord,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Offline presence + kind check of the profile's declared secrets.

    Returns ``(missing_secrets, blocked)``: the failing declarations (ref/kind/
    note/problem — never values, req-boot-required-secrets-5) and the collector
    keys whose declared secrets failed, mapped to the failing refs, so the live
    lane skips them. Resolution goes through the loaded envelope registry
    (``tap_cares.secrets.resolve_secret``) — the exact store boot's collectors
    will resolve from, so the check cannot drift from runtime behavior.
    """
    entries_by_ref = {entry.ref: entry for entry in profile.required_secrets}
    ref_order: list[str] = []
    consumers: dict[str, list[str]] = {}
    for key in fire_keys:
        for step in fire_steps[key]:
            for ref in step.secrets:
                if ref not in ref_order:
                    ref_order.append(ref)
                if key not in consumers.setdefault(ref, []):
                    consumers[ref].append(key)
    if not ref_order:
        return [], {}

    from tap_cares.exceptions import SecretError, SecretNotFoundError
    from tap_cares.secrets import SecretRef, resolve_secret

    say(f"Population preflight: checking {len(ref_order)} required secret(s) (offline) ...")
    logger.info("[8e7b] boot preflight: offline check of %d required secret(s)", len(ref_order))

    missing_secrets: list[dict[str, Any]] = []
    blocked: dict[str, list[str]] = {}
    for ref in ref_order:
        declared = entries_by_ref[ref]
        scope, _, secret_key = ref.partition(":")
        problem: str | None = None
        try:
            secret = resolve_secret(SecretRef(scope=scope, key=secret_key))
        except SecretNotFoundError:
            problem = "missing"
        except SecretError as exc:
            problem = f"unresolvable ({exc})"
        else:
            if secret.kind != declared.kind:
                problem = f"kind mismatch (envelope kind '{secret.kind}', declared '{declared.kind}')"
        if problem is None:
            say(f"  [preflight] secret {ref} OK ({declared.kind})")
            rec.record_step(
                {
                    "type": "preflight",
                    "key": ref,
                    "status": "ok",
                    "note": f"required secret present, kind {declared.kind}",
                }
            )
            continue
        missing_secrets.append({"ref": ref, "kind": declared.kind, "note": declared.note, "problem": problem})
        for consumer_key in consumers[ref]:
            blocked.setdefault(consumer_key, []).append(ref)
        logger.error("[dcb9] boot preflight: required secret %s %s (kind %s)", ref, problem, declared.kind)
        say(f"    FAILED — required secret {ref} {problem}; kind {declared.kind}: {declared.note}")
        rec.record_step(
            {
                "type": "preflight",
                "key": ref,
                "status": "failed",
                "note": f"required secret {problem}; kind {declared.kind}: {declared.note}",
            }
        )
    return missing_secrets, blocked


def _resolve_steps(profile: BootProfile, say: Echo) -> list[PopulationStep]:
    """Validate every enabled step against in-memory registries; fail loud on any miss.

    Resolves with ZERO grid mutation (collector keys are checked against the
    in-memory collector registry, not by reading/creating grid nodes), so a
    malformed profile aborts before the population phase touches the grid.
    """
    from tap_cares.exceptions import CollectorNotFoundError
    from tap_cares.registry import get_collector
    from tap_plugins.seeding import PluginNotFound, resolve_tap_plugin

    for step in profile.enabled_steps:
        if isinstance(step, SeedPluginStep):
            try:
                config = resolve_tap_plugin(step.plugin)
            except PluginNotFound as exc:
                raise BootError(f"seed-plugin: {exc} Aborting before any population step runs.") from exc
            if step.bundle is not None:
                declared = {b.name for b in (config.manifest.grift if config.manifest else [])}
                if step.bundle not in declared:
                    raise BootError(
                        f"seed-plugin '{step.plugin}': unknown bundle '{step.bundle}'. "
                        f"Declared bundles: {sorted(declared) or '(none)'}. "
                        "Aborting before any population step runs."
                    )
        elif isinstance(step, FireCollectorStep):
            try:
                get_collector(step.key)
            except CollectorNotFoundError as exc:
                raise BootError(
                    f"fire-collector: unknown collector key '{step.key}' — not registered. "
                    "Aborting before any population step runs."
                ) from exc
        else:  # pragma: no cover - schema guards the type set
            raise BootError(f"Unknown population step type: {step!r}")

    skipped = len(profile.steps) - len(profile.enabled_steps)
    plan = list(profile.enabled_steps)
    logger.info("[8e0f] boot population plan: %d step(s) (%d disabled, skipped)", len(plan), skipped)
    say(f"Population plan: {len(plan)} step(s) to apply ({skipped} disabled).")
    return plan


def _apply_step(step: object, bootloader: object, say: Echo) -> tuple[bool, dict[str, Any]]:
    """Apply one population step; returns (ok, boot-record entry detail)."""
    if isinstance(step, SeedPluginStep):
        return _apply_seed_plugin(step, bootloader, say)
    if isinstance(step, FireCollectorStep):
        return _apply_fire_collector(step, say)
    return False, {}  # pragma: no cover


def _apply_seed_plugin(step: SeedPluginStep, bootloader: object, say: Echo) -> tuple[bool, dict[str, Any]]:
    from tap_plugins.seeding import resolve_tap_plugin, seed_plugin

    say(f"  [seed-plugin] {step.plugin} ...")
    config = resolve_tap_plugin(step.plugin)  # validated in _resolve_steps; cheap in-memory lookup
    outcomes = seed_plugin(config, actor=bootloader, bundle_name=step.bundle)
    entry: dict[str, Any] = {"type": "seed-plugin", "plugin": step.plugin}

    if not outcomes:
        # No bundles imported. A bad bundle name was already rejected in
        # pre-resolution, so this only happens for a plugin that declares no GRIFT
        # — report it honestly (it is a no-op, not "seeded data").
        logger.info("[5f47] seed-plugin %s: no GRIFT bundles to import", step.plugin)
        say(f"    OK — {step.plugin}: no GRIFT bundles to import (no-op).")
        return True, entry | {"bundles_seeded": 0}

    failed = [o for o in outcomes if not o.ok]
    for o in outcomes:
        if o.ok:
            logger.info("[e79e] seeded %s/%s", o.slug, o.bundle_name)
        else:
            detail = o.read_error if o.read_error is not None else "import failed (see grift result)"
            logger.error("[916b] seed failed %s/%s: %s", o.slug, o.bundle_name, detail)
    entry |= {"bundles_seeded": len(outcomes) - len(failed), "failed_bundles": len(failed)}
    if failed:
        say(f"    FAILED — {step.plugin}: {len(failed)} bundle(s) did not import.")
        return False, entry
    say(f"    OK — {step.plugin}: {len(outcomes)} bundle(s) seeded.")
    return True, entry


def _apply_fire_collector(step: FireCollectorStep, say: Echo) -> tuple[bool, dict[str, Any]]:
    from tap_cares.models import Collector
    from tap_cares.services import fire_collector_and_await

    # The Collector grid node exists now (reconcile ran after pre-resolution); the
    # key was validated against the registry in _resolve_steps.
    collector = Collector.objects.get(collector_registry=step.key)
    timeout = step.timeout_seconds if step.timeout_seconds is not None else DEFAULT_COLLECTOR_TIMEOUT_SECONDS

    say(f"  [fire-collector] {step.key} (run_mode={step.run_mode}, timeout={timeout:g}s) ...")
    ok, job = fire_collector_and_await(
        collector,
        run_mode=step.run_mode,
        manual_run_source="boot",
        timeout_seconds=timeout,
    )
    entry: dict[str, Any] = {
        "type": "fire-collector",
        "key": step.key,
        "job_id": _job_entity_id(job),
        "summary": job.summary or None,
    }
    if ok:
        logger.info("[75b3] fired collector %s: %s", step.key, job.summary or "successful")
        say(f"    OK — {step.key}: {job.summary or 'successful'}")
        return True, entry
    logger.error("[1324] collector failed %s: status=%s %s", step.key, job.status, job.summary or "")
    say(f"    FAILED — {step.key}: status={job.status} {job.summary or 'see CollectionJob'}")
    # Surface the persisted self-test checks — the evidence that names the actual
    # cause (a 401 vs a timeout vs a missing scope), req-boot-obs-abort-detail-1.
    checks = _failing_checks(job, step.key)
    entry["failing_checks"] = checks
    _say_checks(checks, say)
    return False, entry


def _failing_checks(job: object, key: str) -> list[dict[str, Any]]:
    """The failing self-test checks persisted on the job, tagged with their collector.

    Reads the structured `CollectionJob.self_test` payload the run task wrote
    (req-tap-cares-collector-self-test-2) — redaction-safe by the collector
    contract, so it may ride the abort path and the boot record verbatim.
    """
    self_test = getattr(job, "self_test", None) or {}
    checks = self_test.get("checks") or []
    return [{"collector": key} | dict(c) for c in checks if c.get("status") == "fail"]


def _say_checks(checks: list[dict[str, Any]], say: Echo) -> None:
    for check in checks:
        say(f"      check {check.get('code', '?')}: {check.get('message', '')}")


def _job_entity_id(job: object) -> str | None:
    entity_id = getattr(job, "entity_id", None)
    return str(entity_id) if entity_id is not None else None


def _step_label(step: object) -> str:
    if isinstance(step, SeedPluginStep):
        return f"seed-plugin:{step.plugin}"
    if isinstance(step, FireCollectorStep):
        return f"fire-collector:{step.key}"
    return repr(step)  # pragma: no cover
