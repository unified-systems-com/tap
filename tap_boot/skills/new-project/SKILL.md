---
name: new-project
description: Start a brand-new TAP initiative — from "I have an idea" to a running, login-able instance built from exactly one new anchor plugin plus a starter set of EXISTING plugins. Use when someone says "let's build a new demo/product/instance", "I need to stand up something new to explore an idea", or asks how to start a project similar to how samsite or git-serious-double-tap started. NOT for adding one plugin to an already-running setup (that's /new-plugin) and NOT for getting a bare machine to a running TAP session at all (that's /get-started — this skill assumes that part is already done).
allowed-tools: Read Write Edit Bash(scripts/*) Bash(gh *) Bash(git *) Bash(docker *) Bash(docker compose *) Bash(ls *) Bash(cat *) Bash(mkdir *) Glob Grep Skill AskUserQuestion
argument-hint: [project-name]
---

# New Project: Idea → Running, Login-able Anchor

> **Skill source-of-truth.** Canonical location: `tap_boot/skills/new-project/SKILL.md`. `.claude/skills/…`
> is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Keep projects to data** (1): an instance plugin is bundles, Searches, Pages, panel configs, tags and layout hints.
- **Grow the owning plugin when a capability is missing** (2): add it once, by reviewed PR, where the concept lives, then use it from data.
- **Edit a live grid through the service layer, in named batches** (10): every change gets a batch, history and validation.
- **Write Python for collectors, when asked** (9): the collector is the home for source-specific code.


## Philosophy

This skill exists because TAP already has a working, load-bearing example of the shape it produces —
`git_serious_double_tap`: one thin **instance plugin** whose entire job is composing *existing* plugins
(`git_core`, `identity_core`, `administrivia`, `compliance_core`, `github_core`, `zizmor`) into one specific,
login-able, subject-specific stack, pinned in its own boot record. Nobody mapped out everything that instance
plugin could ever need before building it. What got built first was the smallest thing that could boot,
log in, and give a real system to iterate against — the visualization work, the products-row derivation,
the panel refinements all came *after*, against a running stack, not before.

This skill generalizes that shape into a repeatable path: **one new anchor plugin, a starter boot record
built from the existing plugin catalog, get to a logged-in login as fast as honestly possible, defer
everything else.** It is not a full architecture-planning tool. If you already know you're modeling a
brand-new domain nothing in the org has vocabulary for, this skill still gets you to a running anchor first
— `build-domain-vocabulary` and friends are what you reach for *after*, once you're looking at a real system
and can tell what it's actually missing.

Same rule [`get-started`](../get-started/SKILL.md) lives by: **re-implements nothing.** This skill is a
conversational front door onto `new-plugin`, `create-plugin-spec`, and `spawn-session.sh` — it makes the few
decisions that are genuinely new to this situation (what's the project, which existing plugins does it start
from) and hands everything else to the skill that already owns it. If a step here looks like it's
duplicating what `new-plugin` already does, that's a bug in this skill, not a reason to add a shortcut.

## Step 0 — Recognize which situation you're in

- **No TAP session running anywhere on this host** → stop here, run [`get-started`](../get-started/SKILL.md)
  first. This skill assumes a working TAP install exists; it is the layer above that, not a replacement
  for it.
- **A half-written spec or plugin checkout already exists for this idea** → don't restart from Step 1. Read
  what's there, confirm with the author what's still accurate, and resume from wherever it actually left off.
- **Genuinely starting cold** → proceed.

## Step 1 — The decisions only a human can make (ask in one batch)

1. **Project name.** Short, becomes three things at once: the anchor plugin's `slug`, its display name, and
   the `name` field of the Keystone node seeded in Step 5. Keep it consistent across all three — don't let
   the plugin slug and the project's "real" name drift apart.
2. **One-paragraph description of the idea.** What it's for, who it's for, what it observes or simulates.
   This becomes the Keystone's `description` (the prose anyone landing cold reads first) and the plugin
   spec's one-line purpose. Doesn't need to be final — it needs to be *honest about right now*, since the
   Keystone can be re-seeded later as the idea sharpens.
3. **Repo owner** (org or personal account) and **visibility** — same question `new-plugin`'s own Step 1
   asks, asked once here so it doesn't have to be re-asked when this skill hands off to it.

Do not ask about plugin architecture, domain models, or anything downstream of "can I log in yet" — that's
explicitly out of scope for this pass (see Philosophy).

## Step 2 — Search the existing plugin catalog

Don't guess what's available — enumerate it, the way this session actually did it:

```bash
gh repo list unified-systems-com --json name,description -L 100 | \
  jq -r '.[] | select(.name | startswith("tap-plugin-") or endswith("-tap")) | .name'
```

For each candidate plugin worth a look, pull its manifest rather than assume from the name:

```bash
gh api "repos/unified-systems-com/<repo>/contents/tap_plugin/<slug>/tap-plugin.toml" \
  --jq '.content' | base64 -d
```

Sort what you find into two buckets, out loud, so the author can correct you:

- **Substrate** — needed to get to a running login at all, independent of the project's subject matter
  (`identity_core` for auth, `administrivia` for the admin pages and grid landing, `git_core` if anything
  Git-shaped is involved).
- **Subject-matter** — what the project is actually *about* (for a FedRAMP VDR demo: `compliance_core`,
  `fedramp_20x_ksi`, maybe `github_core` if it's observing a real or simulated GitHub-hosted product).

Present the candidate starter set — substrate first, subject-matter second — and get an explicit yes/adjust
before scaffolding anything. A plugin genuinely missing from the catalog is a real, useful finding: name it,
don't silently work around it by picking something close enough.

## Step 3 — Scaffold the one anchor plugin

Invoke [`new-plugin`](../../../tap_plugins/skills/new-plugin/SKILL.md). It will refuse without a spec and
run [`create-plugin-spec`](../../../tap_plugins/skills/create-plugin-spec/SKILL.md) first — that's correct,
don't route around Gate 0.

**One deliberate fast-path for this specific case, named so it isn't confused with skipping rigor
generally:** an anchor/instance plugin in its first pass has no models or edges of its own — its whole job
is composing and seeding pages against *other* plugins' vocabulary (see `git_serious_double_tap`'s own
`grift/` — `home`, `tap-machinery`, `tap-repository`: composition and panel wiring, zero new entity types).
`create-plugin-spec`'s interview can move quickly for exactly that reason: skip the deep domain / prior-art
analysis its own process would run for a plugin introducing new vocabulary, and keep the spec to identity +
purpose + "this plugin carries data only: no models, no edges, no code."

**The anchor stays data for its whole life, not just its first pass** (AGENTS.md, *No bespoke code in a
project*). Its GRIFT bundles, Searches, Pages, panel configs, tags and layout hints are the project. When the
project needs a new node or edge type, that vocabulary goes into the vocabulary plugin that owns the concept
(a `*_core` substrate, a vendor plugin, or a new vocabulary plugin through the full `create-plugin-spec`
rigor), and the anchor uses it as data. When a page cannot be drawn or queried from data, the capability is
added to the plugin that owns it (tap_viz, tap_web, Gryphon) by a reviewed PR. The anchor's only code path is
a programmatic JavaScript layout written through the [`create-layout`](../../../tap_viz/skills/create-layout/SKILL.md) skill (AGENTS.md, *Best practices for TAP*,
item 8).

## Step 4 — Author the starter boot record

Model it directly on an existing instance plugin's own record — `git_serious_double_tap`'s
`boot/git_serious_double_tap.boot.json` is the worked reference: an `install.plugins` list naming the
Step 2 starter set, a `population.steps` list seeding whatever pages/panels the anchor wants plus
(Step 5) the Keystone bundle.

**Pin every plugin by commit SHA, not by tag alone.** A tag is movable: retagging changes the code an
UNCHANGED boot record installs, so "the record did not change" stops meaning "the same thing boots."
That is the hazard `tap#493` and `tap#200` exist to remove, and both are still open, which makes a new
record pinned by tag a new instance of the problem rather than an inherited one.

Resolve the SHA at the moment you write the record — and mind the difference between a tag object
and the commit it points at:

```
git ls-remote https://github.com/<owner>/<repo> 'refs/tags/<tag>*'
```

An **annotated** tag prints two lines. The plain `refs/tags/<tag>` line is the SHA of the tag OBJECT;
the `refs/tags/<tag>^{}` line is the commit. **Record the peeled `^{}` one.** A **lightweight** tag
prints a single line, which is already the commit.

This is not hypothetical here — every TAP plugin tag checked is annotated:

```
$ git ls-remote https://github.com/unified-systems-com/tap-plugin-github-core 'refs/tags/v0.9.0*'
76635dca571cc024bdaf9aa0ab0de68e75e80aa1  refs/tags/v0.9.0        <- tag object, NOT what installs
796a782adefc026a8da34bce10295ac8e21d3f2b  refs/tags/v0.9.0^{}     <- the commit, record this
```

Copy-paste form, which handles both kinds:

```
git ls-remote <url> 'refs/tags/<tag>*' | awk '{sha=$1; ref=$2} END{}; /\^\{\}$/{print $1; found=1} END{if(!found) print sha}'
```

Keep the tag beside the SHA for legibility — the tag says which release a human meant, the SHA says
what actually installs. Only the second one is a guarantee.

An earlier draft of this skill said the opposite, on the grounds that a demo in the make-it-work phase
could defer pin hygiene to a later fleet sweep. Two things were wrong with that. A skill sets the
DEFAULT for every project made through it, so "just this once" written into a procedure is not just
once. And it cited an in-session authorization as its justification, which a reader cannot check — the
reasoning has to stand on its own or it is not a reason.

## Step 5 — Seed the Keystone

A small GRIFT bundle in the new anchor plugin, one `keystone` node:

- `name` — the Step 1 project name.
- `description` — the Step 1 one-paragraph idea, verbatim or lightly cleaned up.
- `context_json` / `context_schema_json` — fine to start minimal (an empty object and a permissive schema);
  the keystone is meant to be re-seeded as the idea sharpens, not authored once and frozen
  (`tap_grid/specs/spec-grid-keystone.md`).

This is the node anyone — human or agent — reads first when landing on this instance cold. Don't skip it to
save time; it's cheaper to seed now than to reconstruct later from chat history.

A landing graph uses TAP's standard graph chrome, `node_style` `icon-badge` (the
[`add-panel`](../../../tap_web/skills/add-panel/SKILL.md) graph-panel rules), unless the author
formally asks for something else.

## Step 6 — Spawn and walk them in the door

```bash
scripts/spawn-session.sh <name> cli --boot-file <path-to-the-new-record>
```

(`--boot-file` for a still-local, not-yet-tagged record — matches `--dev-plugins`' own "everyday fork/dev
tier" language. Switch to `--from git+<repo>@<tag>#<id>` once the anchor plugin has its first release.)

Confirm login works, then confirm the Keystone is actually there and queryable — a quick Gryphon read
(`MATCH (k:keystone) RETURN k`) is enough. Then point forward, the same way `get-started` does:

- Something the running stack is missing that no existing plugin covers →
  [`build-domain-vocabulary`](../../../tap_grid/skills/build-domain-vocabulary/SKILL.md) decides what new
  vocabulary is actually needed before anything gets built.
- A genuinely new plugin beyond the anchor → `/new-plugin` again, this time through its full rigor (the
  Step 3 fast-path was specific to the anchor's first pass, not a standing exemption).
- Iterating on the anchor itself → `/add-page` and `/add-panel` as data; new vocabulary → `/add-model`, `/add-edge`
  in the vocabulary plugin that owns the concept, never in the anchor.
- Landing any of it → [`close-out-pr`](../../../tap/skills/close-out-pr/SKILL.md).

## If it fails

Same escalation as `get-started`: drive [`diagnose-failed-session-spawn`](../diagnose-failed-session-spawn/SKILL.md)
for anything that goes wrong once `spawn-session.sh` is running. This skill doesn't re-implement that
diagnosis either.
