---
name: tailwind-rebuild
description: Rebuild tap_web/static/tap_web/css/tailwind.css from templates after editing Tailwind utility classes. Invoke whenever a template edit changes which utility class strings are present in any `class="..."` attribute under tap_web/templates, tap_viz/templates, or any plugin's templates (in-tree plugins/, a _dev-plugins/ checkout, or a wheel-installed tap_plugin package in the venv). Idempotent and fast.
allowed-tools: Read Bash(scripts/dc *) Bash(grep *)
argument-hint: (none)
---

# Rebuild Tailwind CSS

You are regenerating the compiled Tailwind stylesheet after a template edit that changed which utility classes are present. The compiled CSS at `tap_web/static/tap_web/css/tailwind.css` is committed to git — it is the production artifact and the source of truth for what utility-class rules exist at runtime. If you edit a template to add a new utility class and don't run this skill, the compiled CSS stays stale and the class will silently no-op in the browser (the "class attribute is set, computed style ignores it" symptom).

## When to invoke this skill

Run this skill any time your template diff introduces or removes a Tailwind utility class string. Examples that trigger it:

- Adding `flex`, `gap-4`, `text-sm`, `bg-slate-800`, `text-amber-300`, etc., where the class isn't already present in the compiled output
- Adding a responsive-prefix variant like `sm:grid-cols-3` or `md:flex-row`
- Adding an arbitrary value like `max-w-[90rem]` or `bg-[#abc123]`
- Removing the last instance of a utility class from all scanned templates (the rule disappears from the compiled output)
- Adding a new template directory if you also added it to `tailwind.config.js` content paths

Examples that do NOT trigger it:

- Editing element text, `id` attributes, or non-class attributes
- Reordering existing class names without adding/removing any
- Editing tokens inside HTML comments — Tailwind's scanner ignores comments by design

When in doubt, run the skill. It's idempotent and the cached-binary path is fast (~50ms to verify the cached SHA-256 + ~500ms to rebuild).

## How it works

The tailwindcss CLI binary is NOT carried in the web image — deliberately, so the image stays slim and we don't go through hoops to install a build-time tool that's only needed during template iteration. The skill orchestrates two scripts inside the running web container:

1. **`docker/install-tailwindcss.sh`** — installs the pinned tailwindcss v3.4.17 standalone binary into `/opt/tailwind/tailwindcss`, backed by the Docker named volume `tailwind_bin`. The first invocation downloads from GitHub Releases and verifies its SHA-256 against `tap_web/third_party_manifest.toml` (implements `req-grid-thirdparty-manifest.sec-9/-10`). Subsequent invocations short-circuit when the cached binary's checksum still matches the manifest. The binary lives in Docker's internal volume storage; nothing executes on the host filesystem.
2. **`docker/tailwind-build`** — runs the binary against `tailwind.config.js` to regenerate `tap_web/static/tap_web/css/tailwind.css` (minified).

`dc down -v` wipes the volume; the next skill invocation re-downloads + re-verifies fresh.

## Procedure

Step 1 — run the orchestrated install + build:

```bash
scripts/dc exec web /app/docker/install-tailwindcss.sh && scripts/dc exec web /app/docker/tailwind-build
```

If the web container isn't currently up, run `scripts/dc up -d web` first.

Step 2 — verify the class you added (or one of them) is in the compiled output. Pick a representative class from your template diff and grep the compiled CSS:

```bash
grep 'max-w-\[90rem\]' tap_web/static/tap_web/css/tailwind.css
```

Class names containing colons, brackets, or other shell-metacharacters need escaping in the grep pattern:

- `sm:grid-cols-3` → `grep 'sm\\:grid-cols-3'`
- `max-w-[90rem]` → `grep 'max-w-\[90rem\]'`
- `bg-[#abc]` → `grep 'bg-\[#abc\]'`

If grep finds the rule, the class is in the compiled CSS and the skill is done. If grep finds nothing, the class probably isn't in any scanned `class="..."` attribute — common causes are (a) the class is inside an HTML comment (the scanner ignores comments by design), (b) typo in the class name, or (c) the template lives outside the content paths in `tailwind.config.js`, or (d) the template belongs to a plugin that is not installed in THIS session.

The content paths are currently `tap_web/templates`, `tap_viz/templates`, and one glob per road a plugin's templates arrive by — `plugins/**` (in-tree), `_dev-plugins/**` (dev checkout), and `.venv/lib/python*/site-packages/tap_plugin/**` (wheel-installed). Cause (d) is the one that surprises people: the rebuild only sees the plugins this stack has installed, so a session without the plugin cannot compile that plugin's classes (tap#622).

Step 3 — stage and commit `tap_web/static/tap_web/css/tailwind.css` in the same commit as the template change. Reviewers expect the artifact and the template to be consistent at every revision; production deployments serve the committed artifact unchanged.

## If the skill fails

- **`scripts/dc exec web` reports "service web is not running"** — start it with `scripts/dc up -d web` and retry.
- **`install-tailwindcss: no checksum_sha256_linux_<arch> found for tailwindcss`** — `tap_web/third_party_manifest.toml` is missing the per-arch checksum for your container's architecture, or the manifest entry has drifted. Check the entry; if you're on a new arch, the spec requires adding it (see [`tap_grid/specs/spec-grid-security.md`](../../../tap_grid/specs/spec-grid-security.md) `req-grid-thirdparty-manifest.sec-9`).
- **`install-tailwindcss: SHA-256 mismatch`** — either the manifest checksum drifted from the upstream release, or someone tampered with the download path. Don't bypass; investigate upstream first.
- **Compiled CSS has the class but the browser still shows no style** — that's not this skill's failure mode. It usually means the browser cached the old stylesheet (hard-refresh with Cmd-Shift-R) or you're looking at the wrong element.
- **You need a manual rebuild outside the container** — recovery procedure in [`docs/misc/doc-dev-tailwind-rebuild.md`](../../../docs/misc/doc-dev-tailwind-rebuild.md).

## Spec references

- [`tap_web/specs/spec-web-tailwind-pipeline.md`](../../specs/spec-web-tailwind-pipeline.md) — the rebuild architecture (skill-driven) and its tradeoffs against an always-on container watcher
- [`tap_grid/specs/spec-grid-security.md`](../../../tap_grid/specs/spec-grid-security.md) — `req-grid-thirdparty-manifest.sec-9/-10` for the manifest + checksum contract that `install-tailwindcss.sh` enforces
- [`tap_web/third_party_manifest.toml`](../../third_party_manifest.toml) — single source of truth for the tailwindcss version and per-arch checksums
