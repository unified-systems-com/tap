---
spec: ../../tap_web/specs/spec-web-tailwind-pipeline.md
audience: [llm, developer]
covers:
  - ../../tap_web/specs/spec-web-tailwind-pipeline.md
  - req-web-tailwind-pipeline-manual-fallback
update-triggers:
  - the install or build script names / paths in `docker/` change
  - the scanned content paths in `tailwind.config.js` change
  - the compiled stylesheet path (`tap_web/static/tap_web/css/tailwind.css`) moves
  - the `/tailwind-rebuild` skill's procedure changes substantively
assumes:
  - macOS or Linux dev environment running TAP via `scripts/dc`
  - the reader is debugging a missing CSS rule, the `/tailwind-rebuild` skill is unavailable or has failed, or they're rebuilding outside the container
provides: |
  Reader knows that the `/tailwind-rebuild` skill normally handles
  rebuilds, when a manual rebuild is still warranted, the in-container
  and host-side recipes for running it, how to verify the output, and
  how to recognize the symptom that signals "the class never made it
  into the CSS."
---

# Rebuilding the Tailwind CSS Stylesheet

## Status

The compiled stylesheet at `tap_web/static/tap_web/css/tailwind.css` is **committed in git**. It is regenerated on demand by the `/tailwind-rebuild` skill (`tap_web/skills/tailwind-rebuild/SKILL.md`) whenever a template edit changes which Tailwind utility class strings are present. An auto-memory at `feedback_tailwind_class_edit_invoke_rebuild_skill.md` triggers the AI workflow to invoke the skill at the right moment. See `tap_web/specs/spec-web-tailwind-pipeline.md` for the full architecture rationale.

For the normal AI-driven dev loop you let the skill handle it. This doc exists for the cases where something has broken, you're editing without an AI in the loop, or you need to rebuild outside the container entirely.

## When manual rebuild is warranted

- **You're editing without an AI in the loop.** The skill+memory pattern guarantees rebuilds on the AI path; a human editor has no automatic trigger and must invoke either the skill (preferred) or this manual recipe themselves after touching utility classes.
- **The skill itself failed.** Network error during the binary download, checksum mismatch, container not running. The skill's `## If the skill fails` section covers most of these; for the rest, drop to the in-container recipe below.
- **You're outside the container.** A CI environment, a code reviewer's machine without Docker, evaluating a PR on a laptop with the dev stack off.
- **You want to verify a class lands before committing.** Grep is the canonical check; see "Verify" below.

If your concern is "I added a class and don't see the rule in the compiled CSS," first sanity-check the class is inside a real `class="…"` attribute (Tailwind's scanner ignores tokens that are only inside HTML comments) before reaching for the manual recipe.

## The symptom of a missing rule

The HTML attribute is set correctly on the element — browser dev tools show `class="sm:grid sm:grid-cols-3 sm:gap-4 ..."` — but the computed style doesn't reflect the class. No `display: grid`. No grid template columns. The element renders as if the class weren't there.

This is *not* a CSS specificity problem, a media-query problem, or a Tailwind config problem. The rule simply doesn't exist in `tailwind.css`. Confirm by grepping the compiled file:

```
scripts/dc exec web grep "sm\\\\:grid-cols-3" tap_web/static/tap_web/css/tailwind.css
```

(Run inside the container so you're grepping the live output. Grepping the host copy is equivalent because of the bind mount, but the container path is unambiguous.) If grep finds nothing, the rule is missing.

## Rebuild procedure

### Preferred: in-container, via the project's pinned binary

```
scripts/dc exec web /app/docker/install-tailwindcss.sh
scripts/dc exec web /app/docker/tailwind-build
```

These are the same two scripts the `/tailwind-rebuild` skill orchestrates, so the output matches exactly what the skill produces. The first invocation downloads + verifies the binary against `tap_web/third_party_manifest.toml` (cached in the `tailwind_bin` named volume thereafter); the second runs the build against `tailwind.config.js`.

**The rebuild only sees the plugins THIS session has installed.** The content globs cover plugin templates on all three roads a plugin arrives by — in-tree `plugins/`, a `_dev-plugins/<slug>/` checkout, and wheel-installed `tap_plugin/` packages in the container venv — so a rebuild run in a stack without a given plugin cannot compile that plugin's utility classes, and re-running it there would *drop* classes a plugin-bearing session had compiled in. Rebuild from a session that has the relevant plugins installed, and check the diff for unexpected deletions before committing. Whether the committed artifact should depend on the builder's plugin set at all is the open question in tap#622.

### Fallback: host side without Docker

If you genuinely cannot use the container (e.g., evaluating PR diffs on a laptop with Docker off), the host-side invocation is:

```
npx -y @tailwindcss/cli@3.4.17 \
    -c tailwind.config.js \
    -i tap_web/static/tap_web/css/tailwind-input.css \
    -o tap_web/static/tap_web/css/tailwind.css \
    --minify
```

Notes:

- The `@3.4.17` pin matches the version recorded in `tap_web/third_party_manifest.toml` (which is also what the container install uses). Drift between the host CLI version and the manifest will produce noisy diffs against teammates' builds — keep them in sync.
- The `--minify` flag matches the in-container build's shape. Drop it for human-readable output while iterating, but the committed `tailwind.css` should always be minified.
- Run from the repo root, not from `tap_web/`.

If you don't have `npx`, download the matching standalone binary from the Tailwind releases page (URL pattern: `https://github.com/tailwindlabs/tailwindcss/releases/download/v3.4.17/tailwindcss-<os>-<arch>`) and verify its SHA-256 against the per-arch checksum in `tap_web/third_party_manifest.toml` before running it.

## Verifying the rebuild

After rebuilding:

1. Grep for the new utility:
   ```
   grep "sm\\\\:grid-cols-3" tap_web/static/tap_web/css/tailwind.css
   ```
   It should find at least one match. If not, either the template path isn't scanned (check `tailwind.config.js` content paths against the file you edited), the class spelling doesn't exactly match what's in the template, or the class is only inside an HTML comment.

2. Reload the page in the browser with a hard refresh (Cmd-Shift-R) — the cached old stylesheet otherwise sticks.

3. Open dev tools, inspect the element, and confirm the computed style now reflects the class.

## Commit the rebuilt artifact

`tap_web/static/tap_web/css/tailwind.css` is **tracked in git**. Stage and commit it in the same commit as the template change that motivated the rebuild — reviewers expect the artifact and the template to be consistent at every revision, and production deployments serve the committed file unchanged. This is the inverse of the v0 pipeline's gitignore approach; the current architecture treats the committed artifact as the source of truth and relies on the skill + memory (or this manual recipe) to keep it honest. See `tap_web/specs/spec-web-tailwind-pipeline.md` for the rationale.
