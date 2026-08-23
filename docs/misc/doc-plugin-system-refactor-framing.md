---
title: Plugin System Refactor Framing
date: 2026-06-26
status: planning-note
audience:
  - llm
  - developer
related_specs:
  - tap_plugins/specs/spec-tap-plugin-architecture.md
  - tap_plugins/specs/spec-tap-plugin-load-lifecycle-v0.md
  - tap_plugins/specs/spec-tap-plugin-manifest-v0.md
  - specs/spec-tap-boot-v0.md
related_roadmap:
  - plan/road-rampart.md#step-rampart-launch-ready
---

# Plugin System Refactor Framing

Captured 2026-06-26 from George's plugin-system framing note. This is a
thinking document, not a spec and not an implementation plan. It records the
big-picture intent for the plugin refactor so future plugin-install,
boot-profile, packaging, and marketplace work can trace back to the motivating
rant instead of rediscovering the shape from memory.

## Original Framing

okay, time to think through finalizing the plugin system.

Big picture - we want plugins to work similarly to wordpress, where admins can
add them quickly to a running instance, they can be updated in place, and
(eventually) they can support dependent plugins leading to an ecosystem.  The
eventual goal is that plugins will be available through multiple app stores,
which could include internet-accessible, openly available stores run by us (or
anyone else) as well as internal app stores that a company could set up and
operate themselves (side note that our app stores will be built on TAP, but
that's a project for another day).

This means that our plugins will need all the capabilities that you'd expect:

* versioning
* ability to download and install gracefully on a running system
* nice-to-haves for graceful failure and recovery / rollback
* enable / disable mechanics (although we can decide how sophisticated we need
  these to be)
* dependency collection (another nice-to-have, but probably going to come sooner
  rather than later)
* security features like code signing, grants / permissions needed that can be
  scoped and validated during load

This is going to add up to a lot of stuff, and we need to track them all so we
know that the goals are on the board, but down-scoping to the "make it work"
version is going to be the first important move here.

So things that I know we need to make it work:

* packaging - standardizing on uv for distribution and installation.  they've
  done a ton of work to make this efficient and we're in the python ecosystem so
  let's leverage it.  that said i'm not sure what exactly we should be including
  as part of the uv capability set, so we'll need to discuss this in detail.
* installation - how plugins are installed efficiently and elegantly, and when /
  how that happens.  up until now we've been hardcoding all the plugins into the
  builds, which is not great, it's getting very, very close to the point where we
  pull those out of main and refactor into their own repositories, then install
  them up when we boot an instance.  the installation process should support
  local in-plugin includes so that we don't pollute settings.py with every damn
  third party package, ideally there's a single caller in settings.py for
  tap_plugins which will wire in the rest of the plugin-based dependencies that
  we need.  if absolutely necessary we'll allow modification to settings.py but
  we should standardize it in some way so that the plugins are clearly called out
  rather than just dropping them ad hoc into the INSTALLED_APPS array.
* configuration - the step after installation, where the plugins come up with
  initial setup / config instructions to integrate themselves effectively into
  the system and bring themselves online.  we've got enough variety of plugins
  now that we should be able to figure out the shapes we need here.
* reboot - a container that's already got the plugins installed should boot up
  without pulling new plugins down or configuring them, it should "just work"
* refactor plugins - the existing plugins need to be refactored out to their own
  repos, we can start with a single package target, then expand to the full set
  of samsite plugins, which as of now is our richest, interconnected set of
  packages
* refactor skill - the plugin creation skill should be updated with all the
  standards that we've defined here to make it possible to generate fully
  compliant plugins from the skill itself.

The end goal is that we should be able to refactor samsite to the point where it
gets a boot profile which contains plugins to install and we can go boot samsite
up, its plugins get pulled from somewhere and installed, and the system comes
fully online.

Things that we'll leave off until later:

* dependencies - although we may hit this as part of samsite, at the very least
  we'll see where it's needed based on some of the dependencies between plugins
  we already have, so if there's a quick / efficient path available using uv we
  should think this through and consider working it in.
* updates - this is going to be A Whole Thing, and we'll need to think through
  how to do that, perhaps TUF comes into play here?  we should consider things
  like simple approaches of starting new containers and building out the plugins
  first before going straight to live updates of running systems.
* enable / disable / remove - another complex subject that will require turning
  capabilities on / off, highly variable depending on the plugin, we'll need more
  plugins before we know how to do this.
* bake-in - an ability to pre-bake images with the plugins installed that we know
  the system needs.
* auth tie-in - the ability for plugins to define new capabilities and roles,
  this will be needed, but we can leave all that security stuff off to the last
  minute as is tradition (but it should be on the board).

This is my initial thoughts on what this is and where we want to get to.

Take a hard, aggressive look at the above and stress test it for accuracy and
roadmap compliance.  also run a deep search across other similar projects to
gather prior art and compare their implementations with the proposal above -
what lines up, what features do the have that we don't what have they learned
along the way that we can benefit from?

this is turning out to (not surprisingly) be a major implementation, which makes
sense:  if it was easy then everybody would do it :). that said, this is one of
the core capabilities that takes this from - george's product he runs, to
something that runs everywhere and everyone uses, so let's do the work to dial it
in.

## Immediate Interpretation

The core demand signal is not "build a full app store now." It is "make
installable plugin code real enough that a fresh Rampart instance can stand up
from a profile, with samsite as the proving composition."

Future work should preserve the distinction between:

* the launch-ready minimum: exact plugin code installation, Django app visibility,
  uv sync, migrations, boot population, and reboot stability
* the ecosystem board: dependency solving, updates, rollback, enable/disable,
  removal, signing, grants, stores, and baked images

