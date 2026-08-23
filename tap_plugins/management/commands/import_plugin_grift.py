"""Import bundled GRIFT data for one or more TAP plugins.

Usage:
    docker compose exec web uv run python manage.py import_plugin_grift administrivia
    docker compose exec web uv run python manage.py import_plugin_grift administrivia --bundle grid-landing
    docker compose exec web uv run python manage.py import_plugin_grift --all

Reads each plugin's tap-plugin.toml manifest, finds declared [[grift]] bundles,
and calls grift_import on each one using strict upsert semantics.
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from tap_plugins.base import TapPluginConfig


class Command(BaseCommand):
    help = "Import declared GRIFT bundles for one or more TAP plugins."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "plugin_slugs",
            nargs="*",
            metavar="PLUGIN_SLUG",
            help="One or more plugin slugs to import (e.g. administrivia).",
        )
        group.add_argument(
            "--all",
            dest="all_plugins",
            action="store_true",
            default=False,
            help="Import GRIFT data for all registered TAP plugins.",
        )
        parser.add_argument(
            "--bundle",
            dest="bundle_name",
            default=None,
            help="Import only this named bundle (applies to all specified plugins).",
        )
        parser.add_argument(
            "--dry-run",
            dest="dry_run",
            action="store_true",
            default=False,
            help="Parse and validate GRIFT files without writing to the database.",
        )
        parser.add_argument(
            "--force-batches",
            dest="force_batches",
            default="",
            help=(
                "Comma-separated list of batch_entity_id UUIDs to force re-import. "
                "Bypasses the skip-if-exists guard for the named batches only. "
                "Permitted if and only if DEBUG=True. See req-grid-import-grift-force-reimport."
            ),
        )
        parser.add_argument(
            "--sweep-strict",
            dest="sweep_strict",
            action="store_true",
            default=False,
            help=(
                "With --force-batches, abort the run before any writes if any "
                "sweep candidate fails a guardrail. See req-grid-import-grift-batch-scoped-sweep."
            ),
        )
        parser.add_argument(
            "--purge",
            dest="purge",
            action="store_true",
            default=False,
            help=(
                "With --force-batches, hard-delete swept entities and their "
                "batch-scoped history instead of tombstoning. Permitted if and "
                "only if DEBUG=True. See req-grid-import-grift-sweep-purge."
            ),
        )
        parser.add_argument(
            "--lint",
            dest="lint",
            action="store_true",
            default=False,
            help=(
                "Scan every selected plugin's grift bundles in declared order "
                "and report any entity_id that appears in more than one place. "
                "No DB reads or writes. Exits non-zero if duplicates are found. "
                "See req-grid-import-grift-ordering."
            ),
        )

    def handle(self, *args, **options):
        from django.conf import settings

        all_plugins = options["all_plugins"]
        plugin_slugs = options["plugin_slugs"]
        bundle_name = options["bundle_name"]
        dry_run = options["dry_run"]
        force_batches_raw = options["force_batches"]
        sweep_strict = options["sweep_strict"]
        purge = options["purge"]
        lint = options["lint"]

        force_batches: list[str] = (
            [b.strip() for b in force_batches_raw.split(",") if b.strip()] if force_batches_raw else []
        )

        # Fail fast with operator-friendly errors before touching any files.
        if (force_batches or purge) and not settings.DEBUG:
            raise CommandError(
                "--force-batches and --purge are permitted if and only if DEBUG=True. "
                "This invariant is enforced by req-grid-import-grift-force-reimport and "
                "req-grid-import-grift-sweep-purge — refusing the invocation."
            )
        if purge and not force_batches:
            raise CommandError("--purge requires --force-batches; name the batches to purge explicitly.")
        if sweep_strict and not force_batches:
            raise CommandError("--sweep-strict requires --force-batches; it only affects sweeps on force re-import.")

        plugin_configs = self._resolve_plugins(all_plugins, plugin_slugs)

        if not plugin_configs:
            raise CommandError("No matching TAP plugins found.")

        if lint:
            # No DB reads/writes; just scan files.
            ok = self._run_lint(plugin_configs, bundle_name)
            if not ok:
                raise CommandError("Lint found duplicate entity_id declarations across grift bundles.")
            return

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode: no database writes."))
        if force_batches:
            self.stdout.write(
                self.style.WARNING(
                    f"Force re-import mode: {len(force_batches)} batch(es) named. "
                    + ("Purge enabled. " if purge else "")
                    + ("Strict sweep enabled. " if sweep_strict else "")
                )
            )

        total_imported = 0
        total_errors = 0

        for config in plugin_configs:
            imported, errors = self._import_plugin(
                config,
                bundle_name,
                dry_run,
                force_batches=force_batches,
                sweep_strict=sweep_strict,
                purge=purge,
            )
            total_imported += imported
            total_errors += errors

        if total_errors:
            # Raise CommandError so the process exits non-zero. Callers like
            # scripts/spawn-session.sh rely on this to abort the spawn (and
            # fire its failure trap) instead of silently leaving the session
            # in a partially-seeded state.
            raise CommandError(
                f"Completed with {total_errors} error(s); " f"{total_imported} bundle(s) imported successfully."
            )
        self.stdout.write(self.style.SUCCESS(f"Done. {total_imported} bundle(s) imported."))

    # ---------------------------------------------------------------------------

    def _resolve_plugins(
        self,
        all_plugins: bool,
        plugin_slugs: list[str],
    ) -> list[TapPluginConfig]:
        from tap_plugins.seeding import PluginNotFound, all_tap_plugins, resolve_tap_plugin

        if all_plugins:
            return all_tap_plugins()

        result = []
        for slug in plugin_slugs:
            try:
                result.append(resolve_tap_plugin(slug))
            except PluginNotFound as exc:
                raise CommandError(str(exc)) from exc
        return result

    def _import_plugin(
        self,
        config: TapPluginConfig,
        bundle_name: str | None,
        dry_run: bool,
        *,
        force_batches: list[str] | None = None,
        sweep_strict: bool = False,
        purge: bool = False,
    ) -> tuple[int, int]:
        manifest = config.manifest
        if manifest is None:
            self.stderr.write(self.style.ERROR(f"  [{config.name}] No manifest loaded; skipping."))
            return 0, 1

        bundles = manifest.grift
        if bundle_name:
            bundles = [b for b in bundles if b.name == bundle_name]
            if not bundles:
                self.stderr.write(
                    self.style.ERROR(f"  [{manifest.slug}] Bundle '{bundle_name}' not declared in manifest; skipping.")
                )
                return 0, 1

        if not bundles:
            self.stdout.write(f"  [{manifest.slug}] No GRIFT bundles declared; nothing to import.")
            return 0, 0

        # Dry-run validates files only; it never routes through the writing seed
        # op, so it reads each bundle here.
        if dry_run:
            imported = 0
            errors = 0
            for bundle in bundles:
                self.stdout.write(f"  [{manifest.slug}] Validating bundle '{bundle.name}' from {bundle.path} ...")
                grift_path = manifest.plugin_root / bundle.path
                try:
                    with open(grift_path) as fh:
                        document = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    self.stderr.write(self.style.ERROR(f"    Failed to read '{bundle.path}': {exc}"))
                    errors += 1
                    continue
                if self._dry_run_bundle(manifest.slug, bundle.name, document):
                    imported += 1
                else:
                    errors += 1
            return imported, errors

        # Real import — the shared seed_plugin op (also used by tap_boot's
        # population phase) runs as the named tap_bootloader program actor
        # (req-tap-auth-actor-model: no User=None at the service boundary; the
        # bootloader's least-privilege bundle includes grid.import_grift +
        # grid.write).
        from tap_auth.actors import BOOTLOADER, get_builtin_actor
        from tap_plugins.seeding import seed_plugin

        imported = 0
        errors = 0
        outcomes = seed_plugin(
            config,
            actor=get_builtin_actor(BOOTLOADER),
            bundle_name=bundle_name,
            force_batches=tuple(force_batches or ()),
            sweep_strict=sweep_strict,
            purge=purge,
        )
        for outcome in outcomes:
            self.stdout.write(f"  [{outcome.slug}] Imported bundle '{outcome.bundle_name}' from {outcome.bundle_path}.")
            if outcome.read_error is not None:
                self.stderr.write(self.style.ERROR(f"    Failed to read '{outcome.bundle_path}': {outcome.read_error}"))
                errors += 1
                continue
            self._report_result(outcome.slug, outcome.bundle_name, outcome.result)
            if outcome.result.success:
                imported += 1
            else:
                errors += 1

        return imported, errors

    def _dry_run_bundle(self, plugin_slug: str, bundle_name: str, document: dict) -> bool:
        """Validate a GRIFT document against the GRIFT schema without writing.

        Uses the importer's own document-schema validation (single source of
        truth) — structural only; per-record model validation runs against the
        DB on a real import. Returns True iff the document is valid.
        """
        from tap_grid.grift import validate_grift_document

        issues = validate_grift_document(document)
        if issues:
            for issue in issues:
                self.stderr.write(self.style.ERROR(f"    [{plugin_slug}/{bundle_name}] {issue.path}: {issue.message}"))
            return False

        batch_count = len(document.get("batches", []))
        node_count = sum(len(b.get("nodes", [])) for b in document.get("batches", []))
        edge_count = sum(len(b.get("edges", [])) for b in document.get("batches", []))
        self.stdout.write(
            self.style.SUCCESS(
                f"    [{plugin_slug}/{bundle_name}] Valid — "
                f"{batch_count} batch(es), {node_count} node(s), {edge_count} edge(s)."
            )
        )
        return True

    def _report_result(self, plugin_slug: str, bundle_name: str, result) -> None:
        counts = result.counts
        label = f"[{plugin_slug}/{bundle_name}]"

        if result.success:
            self.stdout.write(
                self.style.SUCCESS(
                    f"    {label} OK — "
                    f"{counts.batches_imported} batch(es), "
                    f"{counts.nodes_imported} node(s), "
                    f"{counts.edges_imported} edge(s) imported"
                    + (
                        f", {counts.batches_force_reimported} force-reimported"
                        if counts.batches_force_reimported
                        else ""
                    )
                    + (f", {counts.entities_swept} swept" if counts.entities_swept else "")
                    + (f" ({counts.entities_purged} purged)" if counts.entities_purged else "")
                    + (f", {counts.sweep_skipped} sweep skip(s)" if counts.sweep_skipped else "")
                    + (f", {counts.edges_skipped} edge(s) skipped" if counts.edges_skipped else "")
                    + (f", {counts.entities_upserted} upserted" if counts.entities_upserted else "")
                    + (f", {counts.warnings} warning(s)" if counts.warnings else "")
                    + "."
                )
            )
            # Per-entity upsert visibility (req-grid-import-grift-ordering): list
            # every node/edge whose entity_id already existed in the grid and was
            # replaced in-place. Helps developers see when a batch is overwriting
            # content seeded by an earlier batch (within or across plugins).
            for batch_summary in result.imported_batches:
                for u in batch_summary.upserted_entities:
                    name_part = f" '{u.name}'" if u.name else ""
                    self.stdout.write(f"      [upsert] {u.kind} {u.entity_type} {u.entity_id}{name_part}")
            # Skipped-batch visibility: when a batch is skipped because its
            # batch_entity_id already exists, surface it explicitly so the
            # developer can decide whether --force-batches is warranted.
            for sb in result.skipped_batches:
                self.stdout.write(
                    f"      [skip] batch {sb.batch_entity_id} already imported "
                    f"(use --force-batches={sb.batch_entity_id} to re-run)"
                )
        else:
            self.stderr.write(self.style.ERROR(f"    {label} FAILED:"))
            for issue in result.errors:
                self.stderr.write(f"      [{issue.phase}] {issue.code} at {issue.path}: {issue.message}")

    def _run_lint(
        self,
        plugin_configs: list[TapPluginConfig],
        bundle_name: str | None,
    ) -> bool:
        """Scan every plugin's declared grift bundles in order and report any
        entity_id that appears in more than one (plugin, bundle, batch) location.

        GRIFT execution is last-write-wins per entity within the deterministic
        ordering of plugin → manifest bundle → in-file batch (see
        req-grid-import-grift-ordering). Duplicates are not always a bug —
        sometimes a later seed legitimately overrides an earlier one — but
        they should be intentional. Lint surfaces them so the developer can
        confirm.

        Returns True when no duplicates are found, False otherwise.
        """
        # entity_id -> ordered list of {plugin, bundle, path, name}
        seen: dict[str, list[dict]] = {}

        for config in plugin_configs:
            manifest = config.manifest
            if manifest is None:
                continue
            bundles = manifest.grift
            if bundle_name:
                bundles = [b for b in bundles if b.name == bundle_name]

            for bundle in bundles:
                grift_path = manifest.plugin_root / bundle.path
                try:
                    with open(grift_path) as fh:
                        document = json.load(fh)
                except (OSError, json.JSONDecodeError) as exc:
                    self.stderr.write(self.style.ERROR(f"  [{manifest.slug}/{bundle.name}] Failed to read: {exc}"))
                    continue

                for batch_idx, batch in enumerate(document.get("batches", [])):
                    bep = batch.get("batch_entity", {})
                    self._lint_record(
                        seen,
                        bep.get("entity_id"),
                        bep.get("entity_type", "batch"),
                        bep.get("name"),
                        manifest.slug,
                        bundle.name,
                        f"$.batches[{batch_idx}].batch_entity",
                    )
                    for n_idx, node_obj in enumerate(batch.get("nodes", [])):
                        env = node_obj.get("entity", {})
                        self._lint_record(
                            seen,
                            env.get("entity_id"),
                            env.get("entity_type"),
                            env.get("name"),
                            manifest.slug,
                            bundle.name,
                            f"$.batches[{batch_idx}].nodes[{n_idx}]",
                        )
                    for e_idx, edge_obj in enumerate(batch.get("edges", [])):
                        env = edge_obj.get("entity", {})
                        self._lint_record(
                            seen,
                            env.get("entity_id"),
                            env.get("entity_type", "edge"),
                            env.get("name"),
                            manifest.slug,
                            bundle.name,
                            f"$.batches[{batch_idx}].edges[{e_idx}]",
                        )

        # Report duplicates.
        duplicates = {eid: sites for eid, sites in seen.items() if len(sites) > 1}
        if not duplicates:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Lint OK — scanned {sum(1 for _ in seen)} unique entity_id(s) across selected bundles; no duplicates."
                )
            )
            return True

        self.stderr.write(
            self.style.WARNING(
                f"Lint found {len(duplicates)} entity_id(s) declared in more than one place. "
                f"Last-declared wins per req-grid-import-grift-ordering; confirm this is intentional."
            )
        )
        for eid, sites in duplicates.items():
            etype = sites[0].get("entity_type") or "?"
            self.stderr.write(f"\n  {etype} {eid}")
            for site in sites:
                name_part = f" ('{site['name']}')" if site.get("name") else ""
                self.stderr.write(f"    - {site['plugin']}/{site['bundle']} at {site['path']}{name_part}")
        return False

    @staticmethod
    def _lint_record(
        seen: dict[str, list[dict]],
        entity_id: str | None,
        entity_type: str | None,
        name: str | None,
        plugin: str,
        bundle: str,
        path: str,
    ) -> None:
        if not entity_id:
            return
        seen.setdefault(entity_id, []).append(
            {
                "entity_type": entity_type,
                "name": name,
                "plugin": plugin,
                "bundle": bundle,
                "path": path,
            }
        )
