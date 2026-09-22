# The Maintainer Dev Box — Programmatic Access Into A Running Codespace

## Philosophy

A Codespace is a whole running TAP instance on a machine nobody has to own. That makes it two
different things to two different people, and the mistake this spec exists to prevent is serving
both from one container.

To a **visitor**, a Codespace is the product: a one-click trial that must be the artifact we ship,
byte for byte, with no affordance a stranger did not ask for. To a **maintainer**, the same Codespace
is a remote machine — somewhere to debug an instance that only misbehaves on a generated hostname,
and somewhere to run a test lane that the laptop cannot finish.

The governing rule is:

> Maintainer access is a **separate devcontainer configuration attached to a separate service**. The
> visitor's container is the shipped image and gains nothing — no listening service, no socket, no
> tooling. Choosing the maintainer configuration is a deliberate act at Codespace creation, and it is
> visible in the Codespace's own record.

Three observations drive it:

- **The trial container is a product surface.** `gs#99` exists because a stranger can make a Codespace
  public with one click. Adding an SSH daemon to the container we hand that stranger widens the
  attack surface of the artifact itself, to buy a convenience only we use. Separating the two costs
  one compose service and keeps the shipped image honest.
- **Reading the code is the wrong half.** The failures that need a maintainer are failures of the
  *running system*: a derivation that did not fire, an environment variable that never reached PID 1,
  a boot profile that resolved to nothing. A shell that can see `/app` but not `web`'s process
  environment answers none of those questions. This is the requirement that decides the design, and
  it is the one an "attach a dev container and be done" answer quietly fails.
- **The laptop is the constrained resource.** The development host OOM-kills test runs (`rc=137`,
  observed repeatedly across three lane attempts on 2026-09-21). Work has been verified narrowly and
  reported with caveats because of it. A Codespace on a 4-core/16GB machine is not a convenience here;
  it is the difference between "tests I could run" and "the lane".

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | The Visitor's Container Is Untouched | The trial runs the shipped image with no maintainer affordance. |
| 2. | Access Reaches The Running System | Not just the source tree — the processes, their environment, their logs. |
| 3. | Choosing It Is Deliberate | A separate configuration, picked at creation, recorded in the Codespace. |
| 4. | No New Inbound Surface | The existing authenticated tunnel is the only path in. |

## Prior Art

**The Dev Containers specification** already answers the "two configurations" half: a repository may
carry several, under `.devcontainer/<name>/devcontainer.json`, and GitHub's *New with options…*
dialog lets the creator pick one. This is the sanctioned mechanism for exactly this split, not a
workaround. **Verified by reading the spec and GitHub's Codespaces documentation** (see Implementation
for what remains unverified).

**`gh codespace ssh`** is the transport, and it is better than it sounds. It does not dial an address:
it tunnels through GitHub's own infrastructure under the operator's authenticated CLI session, so the
Codespace needs no public address and nothing inbound is opened. Its `--config` mode emits per-
codespace OpenSSH configuration, and `gh`'s own help states that once installed you may *"ssh to
codespaces as if they were ordinary remote hosts"* — which brings `scp`, `rsync`, `sshfs` and git
remotes with it. `gh codespace cp` covers file movement without any of that.

**The `sshd` dev container feature** (`ghcr.io/devcontainers/features/sshd`) is the standard way to
put an SSH server in a dev container — and it is written for Debian/Ubuntu. `gh`'s own error text says
so: *"for codespaces that use **Debian-based images**, you can add the following to your
devcontainer.json"*. TAP's image is Wolfi (**RAN** `cat /etc/os-release` in the running container:
`ID=wolfi`), so the feature does not apply to `web`. This is the single fact that shapes the whole
design, and it was discovered by running rather than by reading.

**Docker-outside-of-docker** (`ghcr.io/devcontainers/features/docker-outside-of-docker`) is the
settled pattern for a dev container that needs to drive sibling containers: it mounts the host's
Docker socket rather than nesting a daemon. It is the same construct that makes `docker compose`
usable from inside a dev container, and it is what makes goal 2 reachable.

**Gitpod, Coder and DevPod** all converged on the same separation — a workspace image distinct from
the application image — for the same reason: the thing you develop *in* and the thing you ship are
different artifacts with different threat models. TAP is adopting a consensus, not inventing one.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-devbox-visitor-untouched | [The Visitor's Container Gains Nothing](#the-visitors-container-gains-nothing) | Proposed | No sshd, no socket, no tooling in the shipped image |
| req-dev-devbox-separate-config | [Maintainer Access Is A Separate Configuration](#maintainer-access-is-a-separate-configuration) | Proposed | Chosen at creation; never the default |
| req-dev-devbox-reaches-running-system | [Access Reaches The Running System](#access-reaches-the-running-system) | Proposed | Processes and their environment, not only the tree |
| req-dev-devbox-no-inbound | [No New Inbound Surface](#no-new-inbound-surface) | Proposed | The authenticated tunnel is the only path; ports stay private |
| req-dev-devbox-identity-is-the-operators | [The Session Acts As The Operator](#the-session-acts-as-the-operator) | Proposed | Stated plainly because it is easy to forget |
| req-dev-devbox-lane-capable | [The Box Can Run The Lane](#the-box-can-run-the-lane) | Proposed | The motivating benefit, and the done-test |

---

### The Visitor's Container Gains Nothing
----

RID: `req-dev-devbox-visitor-untouched`

Status: `Proposed`

The `web` service a visitor's Codespace attaches to runs the published image with no modification: no
SSH daemon, no Docker socket, no development tooling, no additional listening port. Every maintainer
affordance lives in a different service, reached by a different configuration.

**Why this is the first requirement rather than an implementation detail.** The trial container is not
a development environment that happens to be public; it is the product, in front of a stranger who may
make it publicly reachable with one click. An SSH daemon there is a listening service on the artifact
we are asking people to trust, added for the convenience of the two people who never needed it to be
there. The whole serving epic (`Issue# 459 - tap`) was about making the shipped thing safe to expose;
quietly re-widening it through the dev-tooling door would undo that at exactly the surface it was
closed at.

**The rejected shortcut, stated because it is tempting and it works.** TAP's image is Wolfi and
carries `apk`, running as root (**RAN**: `command -v apk` → `/usr/bin/apk`; `id` → `uid=0(root)`). So
`apk add openssh-server` in a lifecycle command genuinely would work, and would be perhaps four lines.
It is refused because it mutates the shipped artifact at runtime: the container a visitor is looking
at would no longer be the container we published, and "which image is this?" would stop having one
answer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-visitor-untouched-1 | The Default Config Adds Nothing | Proposed | `.devcontainer/devcontainer.json` declares no features, installs no packages, and opens no port beyond the application's own. | Diffable in one file |
| req-dev-devbox-visitor-untouched-2 | No Socket In `web` | Proposed | The `web` service never mounts the Docker socket, under any configuration. | The maintainer service mounts it; `web` does not |

---

### Maintainer Access Is A Separate Configuration
----

RID: `req-dev-devbox-separate-config`

Status: `Proposed`

Maintainer access is `.devcontainer/maintainer/devcontainer.json`, attached to a `devbox` service that
exists only in a Codespaces compose overlay. It is selected at Codespace creation through *New with
options…*; there is no flag, environment variable or runtime switch that turns a visitor's Codespace
into a maintainer one.

**The separation is legible, which is the point.** Which configuration a Codespace was created from is
part of its record, so "is this box one of ours?" is answered by looking rather than by remembering. A
single configuration with a conditional inside it would make the same two containers with none of that
legibility, and the conditional would be one edit away from defaulting the wrong way.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-separate-config-1 | Two Configurations Exist | Proposed | The repository carries exactly two devcontainer configurations, and the visitor's is the one a bare *Create codespace* selects. | GitHub picks `.devcontainer/devcontainer.json` by default |
| req-dev-devbox-separate-config-2 | No Runtime Promotion | Proposed | No environment variable or command converts a running visitor Codespace into a maintainer one. | The boundary is creation-time or it is not a boundary |

---

### Access Reaches The Running System
----

RID: `req-dev-devbox-reaches-running-system`

Status: `Proposed`

A maintainer session can inspect the **running stack**, not merely the source tree: the processes in
`web` and `db`, their environment, their filesystems including tmpfs, and their logs.

**This requirement is the reason the design is shaped the way it is**, and it is the one a casual
answer fails. A dev container beside the stack sees `/app`, because `/app` is a bind mount of the same
workspace. It does not see `web`'s process environment, and it does not see `web`'s tmpfs. The
concrete case that produced this spec: on 2026-09-21 a Codespace came up serving, but with its auth
configuration unloaded, and the two facts that would have settled it in seconds were `web`'s
environment and `/run/tap-codespace.env` — a file on `web`'s tmpfs. A `devbox` without reach into
`web` could have read neither, and the diagnosis cost a human round-trip instead.

The mechanism is docker-outside-of-docker: the `devbox` service mounts the host's Docker socket and
uses `docker exec` to reach its siblings.

**The cost, stated plainly and not buried.** A mounted Docker socket is root on the Codespace VM.
Anything with that socket can start a privileged container and own the host. On an ephemeral,
single-purpose, per-maintainer box this is a smaller grant than it sounds — the VM's whole job is to
run this stack, and it is discarded after — but it is a real grant and it is why this requirement
carries an explicit decision rather than a default.

**Alternatives considered:**

| Option | Disposition |
| --- | --- |
| Socket into `devbox`, `docker exec` into `web` | **Chosen (pending ruling).** The only option that satisfies this requirement. Root-on-VM is the price. |
| `devbox` with no socket | Rejected. Sees the tree and the network, not the processes — fails the requirement that motivated the spec. |
| sshd inside `web` via `apk` | Rejected by `req-dev-devbox-visitor-untouched`. Would satisfy this requirement directly, which is why it keeps coming back. |
| The `sshd` dev container feature on `web` | Not available. Debian-only; TAP's image is Wolfi (**RAN**, see Prior Art). |
| Docker-in-docker | Already ruled against for the devcontainer generally (`gs#102`, 2026-09-21): compose-native won on 39,808 vs 18,304 observed `devcontainer.json` files, and DinD clusters around image-building projects rather than applications with a database. |
| Browser VS Code terminal only | The status quo. Works, and offers no programmatic access — every check costs a human round-trip, which is the problem being solved. |

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-reaches-running-system-1 | A Command Returns From The Session | Proposed | `gh codespace ssh -c <name> -- '<command>'` runs non-interactively and its stdout returns to the calling session. | The primitive everything else is built on |
| req-dev-devbox-reaches-running-system-2 | `web`'s Environment Is Readable | Proposed | From `devbox`, the environment of `web`'s PID 1 and the contents of its tmpfs can be read. | The 2026-09-21 case, as the done-test |
| req-dev-devbox-reaches-running-system-3 | Files Move Both Ways | Proposed | `gh codespace cp` (or `scp` via `--config`) copies files to and from the Codespace. | Patches in, artifacts out |

---

### No New Inbound Surface
----

RID: `req-dev-devbox-no-inbound`

Status: `Proposed`

Nothing in this spec opens a network path that did not already exist. Access arrives through GitHub's
authenticated tunnel, reached with the operator's `gh` credentials; no port is published to the
internet, and forwarded port visibility stays `private` unless a human deliberately changes it.

**Why this is worth a requirement rather than an assumption.** "Add SSH" reads like "open port 22",
and it is not: the tunnel already exists and already carries the browser editor. The SSH daemon listens
only inside the container, on the Codespace's private network, and the tunnel authenticates before
anything reaches it. The security question is therefore not exposure — it is authorization, which is
`req-dev-devbox-identity-is-the-operators`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-no-inbound-1 | Ports Stay Private | Proposed | No configuration in this spec sets a forwarded port's visibility to `public` or `org`. | `gh codespace ports` shows `private` |
| req-dev-devbox-no-inbound-2 | No Third-Party Tunnel | Proposed | No additional tunnelling dependency or credential is introduced. | GitHub's own transport, or nothing |

---

### The Session Acts As The Operator
----

RID: `req-dev-devbox-identity-is-the-operators`

Status: `Proposed`

A maintainer session authenticates as the operator's GitHub identity, on a machine that also holds a
Codespace-injected `GITHUB_TOKEN`. Everything done there is done as that person.

This is recorded as a requirement because it is the kind of fact that is obvious once and forgotten
afterwards. An automated session with a shell on that box is operating with the operator's
credentials on a machine holding a live token — a materially different posture from a laptop session,
and one the operator should choose knowingly rather than inherit. It also means the ordinary rules
about credentials still apply there: a token in that environment is a credential, not an environment
variable.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-identity-is-the-operators-1 | The Posture Is Documented Where It Is Used | Proposed | The maintainer configuration states, in the file, whose identity a session acts as and what the box holds. | A reader of the config learns it without reading this spec |

---

### The Box Can Run The Lane
----

RID: `req-dev-devbox-lane-capable`

Status: `Proposed`

A maintainer Codespace can run `scripts/test` — the full lane, the promote gate — to completion.

**This is the motivating benefit and it deserves to be a requirement rather than a hoped-for side
effect.** The development host OOM-kills test runs: `rc=137`, three lane attempts and several suites
killed on 2026-09-21 alone. The consequence is not merely slow; it is epistemic. Work has been shipped
with "I ran these suites and could not run the lane" attached, and a reviewer has had to take the gap
on trust. A machine that finishes the lane converts that into evidence.

It also sets the machine-size question. `basicLinux32gb` (2 cores, 8GB) is what a visitor gets and is
what `gs#103` must measure the trial against. Whether it is what a maintainer box should use is a
different question with a different answer, and conflating them would let a green run on a large
machine masquerade as a statement about the trial.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-devbox-lane-capable-1 | The Full Lane Completes | Proposed | `scripts/test` runs to a verdict in a maintainer Codespace, with no `rc=137`. | The done-test for the whole spec |
| req-dev-devbox-lane-capable-2 | The Machine Size Is Recorded | Proposed | The maintainer configuration names the machine type it expects, distinctly from the visitor's. | So a lane result is never read as a trial measurement |

---

## Implementation

Four steps, in this order, because each one can invalidate the next.

1. **`docker-compose.codespaces.yml`** — an overlay adding a `devbox` service on a Debian-based dev
   container image, joined to the stack's network, bind-mounting the workspace, with the Docker socket
   mounted (pending the ruling below). The base compose file is unchanged, so `scripts/dc` and every
   other environment are untouched.
2. **`.devcontainer/maintainer/devcontainer.json`** — `dockerComposeFile` listing the base and the
   overlay, `service: devbox`, the `sshd` and `docker-outside-of-docker` features.
3. **`.devcontainer/devcontainer.json`** — unchanged. Stated as a step so that "did we touch the
   visitor's config?" has an answer in the diff.
4. **Prove it, in this order**: `gh codespace ssh -c <name> -- 'echo ok'` returns; `--config` written
   and plain `ssh` works; `docker exec` from `devbox` reads `web`'s environment and
   `/run/tap-codespace.env`; then `scripts/test` to a verdict.

**What is NOT verified, and would be found at step 1.** Dev container features are applied by building
a derived image, and TAP's compose is deliberately **pull-only** — it hard-fails on a missing pinned
tag rather than silently building (`docker-compose.yml`, and `docker-compose.build.yml` is the explicit
opt-in). Whether features compose cleanly with that policy for a service defined in an overlay is
**NOT OBSERVED**. It should be the first thing tried, because a failure there changes the design rather
than the details — and because discovering it after three more steps would be expensive.

**A CODEOWNERS rule accompanies the new surface.** `.devcontainer/` is a local-execution surface in the
sense `spec-dev-local-execution.md` means it: it decides what runs on a machine a contributor connects
to. The catch-all `*` already owns it, so an explicit rule closes no gap today — it is written for the
same reason the `/*/skills/` rule is, to keep the ownership true if the catch-all is ever narrowed.

## Open Decisions

| Decision | Options | Recommendation |
| --- | --- | --- |
| **The Docker socket** | Mount it into `devbox` (satisfies `req-dev-devbox-reaches-running-system`, and is root on the Codespace VM) — or omit it (no host-root grant, and the spec's motivating requirement fails). | Mount it. The VM is ephemeral, single-purpose and per-maintainer, and without it the feature answers the wrong half of the problem. But it is the operator's call, not a default, and it is why this table exists. |
| **Maintainer machine size** | Inherit the visitor's default, or pin a larger type. | Pin a larger one, and record it, per `req-dev-devbox-lane-capable-2`. |

## Future

- **A user-facing capability sandbox.** The same construct — a shell beside a running instance, separate
  from the product container — is the natural shape for letting users try extensions and configuration
  changes before an MCP service exists. Named here so the design is not accidentally foreclosed; not
  built here, because a maintainer tool and a user-facing sandbox have different threat models and
  conflating them now would produce something that serves neither.
- **Prebuilds**, which `gs#103` will want regardless, and which a maintainer box benefits from most
  because it is created most often.
