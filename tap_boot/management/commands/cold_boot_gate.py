"""`manage.py cold_boot_gate` — the Phase-1 development-validation gate.

TAP-IMPLEMENTS: req-dev-validation-smoke-gate@6e9c7b0cc199/aa1ea3920556 (derivation) — the
    single gate artifact every invoker (dev, scripts/gate, promote, CI) runs identically.
TAP-IMPLEMENTS: req-dev-validation-real-backend@02c4a054f62f/aa1ea3920556 (enforcement) — the
    gate cycle runs against the real DB-backed task backend, never a stub.
TAP-IMPLEMENTS: req-dev-validation-known-broken@261bd2411c82/aa1ea3920556 (derivation) — the
    known-broken manifest's semantics (expected-fail vs must-pass) are applied here.

The ordered, halt-on-failure check that a freshly-built environment can boot from
zero and complete one real end-to-end cycle — the thing hands-on dog-fooding
structurally cannot catch (a cold boot, the spawn-off-`main` path, a cold flow),
and the mechanical protection of the multi-session workflow: a rotted `main`
silently poisons every session spawned from it.

Spec: `specs/spec-dev-validation.md` (`req-dev-validation-smoke-gate`,
`req-dev-validation-real-backend`, `req-dev-validation-known-broken`). This is the
single artifact the local dev, `scripts/gate`, `scripts/promote-to-main.sh`, and a
future server CI all invoke identically — never a reimplemented environment. It
MUST run inside the compose image (the container Python build is non-stock); it is
driven against a **fresh scratch database** by `scripts/gate` (which sets
`DATABASE_URL` and provisions/drops the scratch DB around this command).

The ordered cycle (each step halts the gate on failure unless listed in the
known-broken manifest):

  1. schema:migrate            createcachetable (before migrate — the tap_health
                               E001 cache-table chicken-and-egg) then migrate from
                               zero on the empty scratch DB.
  2. schema:makemigrations     `makemigrations --check` — no model drift with no
                               migration (the #1 Django gap both NetBox/Nautobot
                               close and TAP lacked).
  3. profiles:resolve          every shipped boot profile resolves against the
                               registries (the per-profile cold-boot smoke; catches
                               the module-path→slug fire-collector rot class).
  4. seed:boot-test_all        run the real `test_all` boot (auth → strict seed →
                               collector-node reconcile) — the union superset, so
                               the seed path is exercised across every plugin. A
                               failed bundle fails.
  5. collector:cycle           one real collector reaches a terminal CollectionJob
                               state through the REAL DB-backed backend + in-process
                               drain (never ImmediateBackend), the scheduler queue is
                               evaluated in the same drain, and grid mutation is
                               positively asserted via PRODUCED_BATCH edges (an
                               idempotent no-op is a valid SUCCESSFUL outcome).
  6. health                    `run_health` — the assembled instance's real backends
                               (db / cache round-trip / queue / secrets) actually work.

Wall-clock budget: correctness and real-backend fidelity over speed. The human is
offline during a promote by design; the gate is not latency-optimized.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from tap.ratchet import RatchetError, ratchet_ceiling

logger = logging.getLogger(__name__)

# The deterministic offline canary (grid_fixtures) — no network, no credentials, so
# the gate's real-backend cycle never flakes on an upstream being down. Override with
# --collector to drive a real domain collector (e.g. fedramp_20x_ksi:ksi-catalog).
DEFAULT_COLLECTOR = "grid_fixtures:canary"
DEFAULT_COLLECTOR_TIMEOUT = 120
# House ratcheting-baseline convention (req-dev-validation-known-broken): in-repo,
# per-entry justified, ratchets to zero. Empty `entries` == strict mode.
# parents[2] is the tap_boot/ app dir (this file is tap_boot/management/commands/).
KNOWN_BROKEN_PATH = Path(__file__).resolve().parents[2] / "tap_boot.cold_boot_gate_known_broken.json"


class GateStepFailed(Exception):
    """A single ordered step failed; the runner decides halt vs. tolerate."""


@dataclass(frozen=True)
class GateStep:
    step_id: str
    title: str
    run: Callable[[Command], str]


class Command(BaseCommand):
    help = "Cold-boot development-validation gate (ordered, halt-on-failure). See specs/spec-dev-validation.md."

    # The gate runs against a FRESH scratch DB where the cache table does not yet
    # exist, so Django's startup system checks (tap_health E001) would abort before
    # handle() ever runs step 1 (createcachetable). Defer checks; step 1 provisions
    # the table, and every call_command below runs its own checks against a
    # by-then-valid schema.
    requires_system_checks: tuple[str, ...] = ()

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--collector",
            default=DEFAULT_COLLECTOR,
            help=f"Registry key of the collector fired for the real-backend cycle (default {DEFAULT_COLLECTOR}, "
            "the deterministic offline canary). Override to drive a real domain collector.",
        )
        parser.add_argument(
            "--collector-timeout",
            type=int,
            default=DEFAULT_COLLECTOR_TIMEOUT,
            help="Seconds to await the collector's job to a terminal state via the in-process drain.",
        )
        parser.add_argument(
            "--known-broken",
            default=str(KNOWN_BROKEN_PATH),
            help="Path to the known-broken manifest (in-repo, ratchets to zero; empty == strict).",
        )
        parser.add_argument(
            "--skip-if-not-installable",
            action="store_true",
            help="Skip the gate (exit 0, loud) when this stack cannot install the `test_all` union — "
            "i.e. a focused session. The full cold boot is inherently a full-install check; the "
            "all-plugins CI lane owns it (req-dev-validation-all-plugins-lane). The promote passes this.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Focused-stack early-out FIRST — before any precondition (real backend, DB):
        # a stack that cannot install `test_all` cannot run this full-install gate at
        # all, so it skips and the all-plugins CI lane owns the truth. No backend needed
        # to say "not my job."
        if options["skip_if_not_installable"] and not self._test_all_installable():
            self.stdout.write(
                self.style.WARNING(
                    "cold_boot_gate SKIPPED — focused stack: the `test_all` union is not installable "
                    "here, so the full cold boot cannot run locally. The all-plugins CI lane boots "
                    "`test_all` on a full-install runner and owns full cold-boot truth "
                    "(req-dev-validation-all-plugins-lane, req-dev-multisession-ci-gate)."
                )
            )
            return
        self._guard_real_backend()
        self._collector_key = options["collector"]
        self._collector_timeout = options["collector_timeout"]
        known_broken = self._load_known_broken(Path(options["known_broken"]))

        steps = [
            GateStep("schema:migrate", "Fresh DB → createcachetable → migrate from zero", self._step_migrate),
            GateStep("schema:makemigrations", "makemigrations --check (no model drift)", self._step_makemigrations),
            GateStep("profiles:resolve", "Every shipped boot profile resolves", self._step_profiles_resolve),
            GateStep(
                "seed:boot-test_all",
                "Real `test_all` (union) boot (auth → strict seed → reconcile)",
                self._step_boot_test_all,
            ),
            GateStep("collector:cycle", "One real collector cycle via the real backend", self._step_collector_cycle),
            GateStep("health", "Assembled-instance health (db / cache / queue / secrets)", self._step_health),
        ]

        self.stdout.write(f"cold_boot_gate: {len(steps)} step(s); backend={settings.TASKS['default']['BACKEND']}")
        started = time.monotonic()
        tolerated: list[str] = []
        failed_broken: set[str] = set()

        for i, step in enumerate(steps, start=1):
            self.stdout.write(f"\n[{i}/{len(steps)}] {step.step_id} — {step.title}")
            try:
                detail = step.run(self)
            except Exception as exc:  # noqa: BLE001 — the gate's whole job is to catch and classify
                if step.step_id in known_broken:
                    failed_broken.add(step.step_id)
                    tolerated.append(step.step_id)
                    logger.warning("[6a5b] cold_boot_gate step %s failed but is known-broken: %s", step.step_id, exc)
                    self.stdout.write(
                        self.style.WARNING(
                            f"    KNOWN-BROKEN (tolerated): {exc}\n" f"      reason: {known_broken[step.step_id]}"
                        )
                    )
                    continue
                logger.error("[513f] cold_boot_gate GATE RED at step %s: %s", step.step_id, exc)
                raise CommandError(
                    f"GATE RED at step [{i}/{len(steps)}] {step.step_id}: {exc}\n"
                    f"The first failing step halts the gate (halt-and-report). "
                    f"origin/main must not advance past this tree."
                ) from exc
            self.stdout.write(self.style.SUCCESS(f"    ok — {detail}"))

        self._ratchet_known_broken(known_broken, failed_broken)

        elapsed = time.monotonic() - started
        summary = f"GATE GREEN: {len(steps)} step(s) in {elapsed:.1f}s"
        if tolerated:
            summary += f" ({len(tolerated)} known-broken tolerated: {', '.join(sorted(set(tolerated)))})"
        logger.info("[00bc] cold_boot_gate green in %.1fs (%d tolerated)", elapsed, len(tolerated))
        self.stdout.write("\n" + self.style.SUCCESS(summary))

    # -- guards / manifest ---------------------------------------------------

    def _guard_real_backend(self) -> None:
        """req-dev-validation-real-backend-1: never the ImmediateBackend substitute."""
        backend = settings.TASKS["default"]["BACKEND"]
        if "ImmediateBackend" in backend:
            raise CommandError(
                f"Refusing to run the gate under {backend}. The load-bearing requirement "
                f"(req-dev-validation-real-backend) is the real DB-backed backend; ImmediateBackend "
                f"runs tasks inline and would stay green through the exact delivery bug class the gate "
                f"exists to catch. Run via manage.py (tap.settings), not the pytest/test_settings path."
            )

    def _load_known_broken(self, path: Path) -> dict[str, str]:
        """Return {step_id: reason}. Missing file == strict (empty)."""
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"known-broken manifest unreadable ({path}): {exc}") from exc
        entries = data.get("entries", [])
        broken: dict[str, str] = {}
        for entry in entries:
            step_id = entry.get("step")
            reason = entry.get("reason", "")
            if not step_id or not reason:
                raise CommandError(
                    f"known-broken manifest entry missing 'step' or 'reason' (req-dev-validation-known-broken-3): {entry}"
                )
            broken[step_id] = reason
        return broken

    def _ratchet_known_broken(self, known_broken: dict[str, str], failed_broken: set[str]) -> None:
        """req-dev-validation-known-broken-2: a listed entry that no longer fails is stale → red.

        Delegates the compare-and-report to the shared ceiling-ratchet core
        (`tap.ratchet`) so this manifest obeys the one house ratchet convention.
        The stale half is what fires here — a newly-failing *un*listed step has
        already halted the run before this point — but routing `current`/`baseline`
        through the same core keeps the "green stays honest" teeth in one place.
        RatchetError is re-raised as CommandError to preserve the clean gate-red UX.
        """
        try:
            ratchet_ceiling(
                current=failed_broken,
                baseline=set(known_broken),
                surface="cold-boot known-broken manifest",
                baseline_path=KNOWN_BROKEN_PATH,
                new_hint=(
                    "A newly-failing step is not tolerated — fix it, or (last resort) add a justified "
                    '{"step": ..., "reason": ...} entry (req-dev-validation-known-broken-3).'
                ),
            )
        except RatchetError as exc:
            raise CommandError(f"GATE RED: {exc} (req-dev-validation-known-broken-2)") from exc

    # -- steps ---------------------------------------------------------------

    def _step_migrate(self, _cmd: Command) -> str:
        # createcachetable BEFORE migrate: the tap_health E001 system check hard-fails
        # migrate if tap_cache is missing (chicken-and-egg), so provision it first —
        # the same ordering the container entrypoint uses.
        call_command("createcachetable", verbosity=0)
        call_command("migrate", "--noinput", verbosity=0)
        return "schema built from zero"

    def _step_makemigrations(self, _cmd: Command) -> str:
        try:
            call_command("makemigrations", "--check", "--dry-run", verbosity=0)
        except SystemExit as exc:  # --check exits non-zero when a migration is missing
            raise GateStepFailed(
                "model changes have no migration (makemigrations --check failed). "
                "Run `manage.py makemigrations` and commit the result."
            ) from exc
        return "no missing migrations"

    @staticmethod
    def _test_all_installable() -> bool:
        """True when this stack can install the ``test_all`` union — i.e. a full stack.

        The single full-stack predicate, via the shared install-awareness filter:
        ``test_all``'s install set IS the full plugin union, so the stack is "full"
        exactly when ``test_all`` is installable here.
        """
        from tap.plugin_testing import installed_plugin_slugs
        from tap_boot.profile import installable_profile_ids

        return "test_all" in installable_profile_ids(installed_plugin_slugs())

    def _step_profiles_resolve(self, _cmd: Command) -> str:
        from tap.plugin_testing import installed_plugin_slugs
        from tap_boot.orchestrator import BootError, check_profile
        from tap_boot.profile import installable_profile_ids, load_profile, profile_ids

        if not profile_ids():
            raise GateStepFailed("no shipped boot profiles discovered")
        # Install-aware via the shared filter (tap_boot.profile.installable_profile_ids):
        # resolve only profiles whose plugins are installed in this stack. On a full
        # stack (the only place this gate runs to completion — a focused promote skips
        # it, see handle()) that is every profile; the filter keeps the surfaces from
        # drifting and makes a manual focused run resolve its subset rather than red on
        # an absent-plugin profile.
        ids = installable_profile_ids(installed_plugin_slugs())
        for profile_id in ids:
            try:
                check_profile(load_profile(profile_id))
            except BootError as exc:
                raise GateStepFailed(f"profile '{profile_id}' does not resolve against the registries: {exc}") from exc
        return f"{len(ids)} profile(s) resolved: {', '.join(ids)}"

    def _step_boot_test_all(self, _cmd: Command) -> str:
        from tap_boot.orchestrator import BootError, run_boot
        from tap_boot.profile import load_profile

        try:
            run_boot(load_profile("test_all"), echo=lambda _m: None)
        except BootError as exc:
            raise GateStepFailed(f"test_all boot failed: {exc}") from exc
        return "test_all (union) profile booted (auth + strict seed + collector reconcile)"

    def _step_collector_cycle(self, _cmd: Command) -> str:
        from tap_auth.actors import BOOTLOADER, acting_as, get_builtin_actor
        from tap_cares.dev_validation import DrainTimeout, drain_ready_executions
        from tap_cares.models import CollectionJobStatus, Collector
        from tap_cares.services import run_collection
        from tap_grid.batch import produced_batches

        key = self._collector_key
        try:
            collector = Collector.objects.get(collector_registry=key)
        except Collector.DoesNotExist as exc:
            raise GateStepFailed(
                f"no on-grid Collector for key '{key}' (was it seeded/reconciled by the base boot?)"
            ) from exc

        # Trigger gate wants a named actor; fire as tap_bootloader (holds the cap).
        # The collection still executes as the least-privilege tap_cares.collector.
        with acting_as(get_builtin_actor(BOOTLOADER)):
            job = run_collection(collector, manual_run=True, manual_run_source="cold_boot_gate")
        job_id = job.entity_id

        # Real backend: enqueue → commit → in-process drain (dispatch/claim/perform).
        # The drain also dispatches the scheduler queue, so the scheduler fire is
        # evaluated in the same run (req-dev-validation-smoke-gate-3).
        try:
            performed = drain_ready_executions(deadline=time.monotonic() + self._collector_timeout)
        except DrainTimeout as exc:
            raise GateStepFailed(str(exc)) from exc

        job.refresh_from_db()
        if job.status not in {CollectionJobStatus.SUCCESSFUL.value, CollectionJobStatus.FAILED.value}:
            raise GateStepFailed(
                f"collector '{key}' did not reach a terminal state within {self._collector_timeout}s "
                f"(status={job.status}) after {performed} drained execution(s) — delivery hang."
            )
        if job.status == CollectionJobStatus.FAILED.value:
            raise GateStepFailed(
                f"collector '{key}' ran through the real backend but FAILED: "
                f"summary={job.summary!r} errors={(job.results or {}).get('error')}"
            )

        imported = produced_batches(job_id)["imported"]
        if imported:
            return (
                f"collector '{key}' → terminal SUCCESSFUL via real backend "
                f"({performed} drained), {len(imported)} GRIFT batch(es) imported "
                f"(PRODUCED_BATCH, disposition=imported); scheduler evaluated"
            )
        # SUCCESSFUL with no import is a legitimate idempotent no-op — the linchpin
        # (real backend → terminal) is proven; not a failure (req-dev-validation-smoke-gate-4 note).
        return (
            f"collector '{key}' → terminal SUCCESSFUL via real backend ({performed} drained), "
            f"idempotent no-op (no PRODUCED_BATCH this run); scheduler evaluated"
        )

    def _step_health(self, _cmd: Command) -> str:
        from tap_health.selection import READINESS
        from tap_health.service import run_health

        # Readiness: the gate is asking "did this cold boot produce an instance fit
        # to serve and act on the grid?", not "should something restart this
        # process?" (req-tap-health-selection).
        report = run_health(selection=READINESS)
        if not report.ok:
            unhealthy = [o.name for o in report.outcomes if o.critical and o.result.status.value == "unhealthy"]
            raise GateStepFailed(f"health report not ok; critical unhealthy: {unhealthy}")
        return f"health {report.status.value} ({len(report.outcomes)} probe(s), selection={report.selection})"
