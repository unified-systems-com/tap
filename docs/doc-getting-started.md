---
title: Getting Started with TAP
audience:
  - adopter
  - developer
  - llm
status: draft
---

# Getting started with TAP: tips, traps, and what it is actually for

[`doc-tap-intro.md`](doc-tap-intro.md) is what TAP *is*, in two pages. The
[README](../README.md) is how to get it running. This is the third thing: enough framing
that a smart technical person can tell what to try first, what to skip, and where the
edges are — without reading the specs to find out.

It assumes you have not run it yet.

---

## The one-sentence version

You describe a system you are responsible for; TAP turns it into a live graph you can
query, look at, and keep honest as it changes. Core speaks no domain language at all —
every vocabulary (AWS, Git, Okta, your on-prem estate) arrives as a plugin.

That last point is the one that decides whether TAP is useful to you. **TAP does not come
with a model of your world. It comes with the machinery to build one, and a catalog of
models other people already built.**

---

## Three doors, and picking the wrong one costs you an afternoon

There are three entry points and they are genuinely different. All three are *skills* —
procedures written for an AI coding assistant, which is the intended way to drive this.

| You are… | Use | What it does |
| --- | --- | --- |
| On a bare machine, nothing running | `/get-started` | Host prep, the choices, the run, first login. Ends with you looking at a TAP instance. |
| Holding an idea, want it modelled | `/new-project` | Turns a description into **one thin anchor plugin** composing plugins that already exist, boots it, hands you a login. |
| Already running, want one more thing | `/new-plugin` | Adds a single plugin to a setup that exists. |

**The common mistake is reaching for `/new-plugin` when you want `/new-project`.** If you
are starting something new, you almost certainly want one *anchor* plugin that composes
several existing ones — not to hand-build each piece. `/new-project` asks you a batch of
questions first and creates nothing until you answer them.

> Invoke skills deliberately. Reading a file does not start one.

---

## What already exists, and how to read the catalog

Before building vocabulary, find out whether it is already built. Your assistant can
enumerate the catalog directly — `/new-project` does this as its second step — but it
helps to know what you are looking at, because the names follow a pattern.

**Substrate plugins (`*_core`) are vendor-neutral vocabulary.** They model a *kind of
thing*, not a product:

| Plugin | Gives you |
| --- | --- |
| `computing_core` | `file`, `program`, `user`, `port`, `ip_address`, `network_interface`, `tcp_connection`, `private_key`, `public_key`, `web_host`, `web_document` |
| `git_core` | Repositories, refs and commits, with identities any source can mint |
| `identity_core` | `human`, `organization`, `oidc_issuer` |
| `compliance_core` | `compliance_boundary`, `compliance_context`, `compliance_finding`, `compliance_evidence`, `compliance_artifact`, `compliance_exception` |
| `project_management_core` | **Nothing yet — deliberately.** The package exists, declares its slug, and ships no vocabulary; milestones and tasks get added when a real project needs them. Worth knowing as the honest face of the pattern below: a plugin can be a placeholder. |

If you are mapping an on-prem estate, `computing_core` is very likely your starting
substrate — those eleven primitives cover a great deal of "what is actually running on
this box and what is it talking to".

**Vendor plugins name a product**, and most are deliberately thin at v0: they carry *one
outer node* — the Okta org, the Duo account, the Teleport cluster, the GitLab instance —
and nothing beneath it yet.

That is not incompleteness. It is a design affordance worth understanding early:

> **You can place a thing in the grid before you can collect from it.** The outer node
> exists so a design can reference the system now, and the collection that fills it in
> arrives later. You can model an estate you have no credentials for.

**Products** (`git-serious`, `samsite`) are whole compositions — a worked example of many
plugins assembled into something with pages and a point of view. Read one if you want to
see where this ends up.

---

## Can, can't, should, shouldn't

Honest edges, so you do not spend a day finding them yourself.

**It can:**

- Model a domain nobody has modelled, without touching core. That is the normal case, not
  an extension point bolted on.
- Hold things you cannot observe yet, and fill them in when you can.
- Keep field-level provenance and history — you can ask *when did this change, and what
  told us*, not just *what is it now*.
- Run entirely offline against a fixture corpus, with no credentials at all.

**It can't:**

- Guess your domain. If no plugin models your thing, you are writing vocabulary — the
  skills make that tractable, but it is still design work you have to do.
- Be pointed at a system and auto-discover it. Collection is written per source,
  deliberately: a collector declares what it observes and what that means.
- Serve as a general-purpose database. The grid is a model of systems you are responsible
  for, and its shape reflects that.

**You should:**

- Start from a running instance rather than a whiteboard. The fast path exists because
  arguing about a model you cannot see is the slowest way to get one right.
- Let the assistant drive. Skills under `*/skills/` are the real interface; this repo
  treats AI assistants as first-class operators rather than a convenience.
- Model the smallest thing that answers a real question, then grow it. A vocabulary that
  answers nothing is the most common way to waste a week here.
- Spawn sessions freely. They are worktrees, they are cheap, and they are disposable.

**You shouldn't:**

- Fork core to add your domain. If you find yourself editing `tap_grid/` to model
  something, that is the signal you want a plugin.
- Hand-build what `/new-project` composes. It exists because assembling the substrate by
  hand is tedious and easy to get subtly wrong.
- Expect a fast answer to an issue. TAP is maintained by one person — the README says this
  plainly and it is worth believing.

---

## Practical tips

**Lite first.** `scripts/lite-spawn.sh <name>` gives you a real worktree, environment and
secrets wiring in seconds, and starts no containers. You can read the code, try an edit,
or talk to an assistant about it without paying for a stack you may not keep.
`scripts/promote-lite-session.sh <name>` boots that same worktree when you decide you want
it. Ports are chosen at promote time, so lite sessions reserve nothing.

**Sessions are disposable, and that is the intended posture.** `despawn-session.sh <name>`
removes one. Do not nurse a session you have broken — spawn another.

**The boot profile is the manifest.** `boot/*.boot.json` is the honest answer to "what is
in this instance": which plugins install, which seed, which collectors fire, and which
credentials are required. Read the profile before reading the code if you want to know
what an instance actually is.

**Credentials are declared, not discovered.** A profile that needs a credential says so in
`required_secrets`, and the boot preflight checks the declarations in seconds — naming
what is missing before anything expensive runs. The default `core_dev` profile needs none
at all, which is why you can be looking at a running grid before deciding whether to give
it anything.

**A plugin can be installed editable or pinned.** Editable installs load from a local
checkout — useful while you are building. Pinned installs take a released version. If you
are wondering why a change you merged is not showing up, check which one you are on; that
is the single most common cause.

---

## When you get stuck

- `/get-started` can diagnose a failed first run, and `/diagnose-failed-session-spawn`
  exists for exactly the case its name describes.
- `logs/boot/latest.boot-record.json` is the verdict of the last boot, persisted.
- The specs under `specs/` and `<app>/specs/` are the contract. When a skill and a spec
  disagree, the spec wins and the skill is the bug.
- [Open an issue](../../issues). Read [CONTRIBUTING.md](../CONTRIBUTING.md) first, because
  contribution here starts with one.

---

## Where to go next

| Where | What |
| --- | --- |
| [`doc-tap-intro.md`](doc-tap-intro.md) | TAP in two pages |
| [`../architecture.md`](../architecture.md) | The architectural contract |
| [`doc-gryphon-commandments.md`](doc-gryphon-commandments.md) | Writing queries against the grid |
| `boot/` | What an instance installs and seeds |
| `*/skills/` | Every procedure, written to be run |
