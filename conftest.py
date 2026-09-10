"""Root-level pytest configuration — collection scoping ONLY.

The test-harness fixtures (the `tap_test` caller context, the auth-bootstrap
seeding, the service-write hatch) do NOT live here. They are a real pytest
plugin — `tap/pytest_harness.py`, loaded via `-p tap.pytest_harness` in the
configfile's `addopts` — because conftest loading depends on how pytest was
invoked: pytest 9.1 stopped
loading the rootdir conftest chain for `--pyargs`-resolved packages (2026-08-09),
which silently stripped the harness from every `pytest --pyargs tap_plugin.<slug>`
run (plugin-ci lane 2) and failed every plugin DB test at the service boundary.
An entry-point plugin loads in every invocation mode; a conftest does not. Do not
move load-bearing fixtures back here. (req-tap-test-fixtures / spec-tap-testing.md)

What legitimately remains here is rootdir-scoped COLLECTION configuration —
`collect_ignore` is a conftest-only pytest hook variable, and it only matters when
collection walks this repo tree, which is exactly the case where this conftest is
guaranteed to load.
"""

from pathlib import Path

from tap.plugin_testing import installed_plugin_slugs

# The monorepo `plugins/` walk that lived here (a `collect_ignore` over uninstalled plugins
# on disk) was retired 2026-09-10 (tap#369): plugin tests ride inside the installed package
# and are collected by their OWNER through the one seam, `tap.plugin_testing` /
# `tap.lane_run` — never by a root walk that happens to find them.
collect_ignore: list[str] = []
