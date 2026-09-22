"""The container that serves requests does not run as root, and cannot drift back.

`Issue# 754 - tap`. The runtime stage carried no `USER` directive at all, so `web` served
as uid 0 — `scripts/dc exec -T web id` -> `uid=0(root)`. Nothing in the tree said so, asked
otherwise, or would have noticed if it changed back.

NO REQUIREMENT OWNS THIS YET. No spec mentions non-root, rootless, or the container user
(searched 2026-09-22), so these tests carry no `@pytest.mark.spec` — deliberately, rather
than by borrowing an ACID that is about something else. When the property is written into
canon, mark them.

What makes this a text test rather than a runtime one: the uid is decided in three files
that cannot import each other — a `USER` line in the Dockerfile, a `user:` key in compose,
and a set of directory preparations whose only job is to make the MOUNTS writable by a
non-root process. A runtime check on a warm stack proves none of it: volumes created while
the image was still root-owned stay writable, so the change passes locally and breaks on
the next cold boot. The honest split:

- PROVEN HERE (text): the declarations exist, are non-root, and agree with each other.
- NOT OBSERVED HERE: that a cold stack boots healthy, that `uv sync` can write a freshly
  created venv volume, that the bind mount is writable when the host uid differs from the
  container's. Those need `scripts/dc down -v && scripts/dc up` and a Linux host; see the
  tap#754 handover for which of them was actually observed and on which platform.

These now carry `req-tap-serving-unprivileged` markers. They deliberately did NOT when this
module was written, because no requirement owned the property and marking a test with an ACID
it does not verify inflates coverage while proving nothing. The requirement was written
afterwards (spec-tap-serving.md, ruled by George 2026-09-22) and the markers followed it, in
that order.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tap import preboot

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_ENTRYPOINT = _REPO_ROOT / "docker" / "entrypoint.sh"

#: The uid the published image runs as when nobody overrides it (Wolfi's `nonroot`).
_IMAGE_USER = "nonroot"
#: Mount targets the container writes at runtime. Each is a named volume, and a fresh
#: named volume inherits the ownership of the image directory at its mount path — so a
#: target the image does not prepare comes out root-owned and unwritable.
_PREPARED_MOUNT_TARGETS = ("/app/.venv", "/home/nonroot/.cache/uv", "/opt/tailwind")


def _stages() -> dict[str, list[str]]:
    """Dockerfile stage name -> its instruction lines (comments and blanks dropped)."""
    stages: dict[str, list[str]] = {}
    current: list[str] = []
    for raw in _DOCKERFILE.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^FROM\s+\S+(?:\s+AS\s+(\S+))?$", line, re.IGNORECASE)
        if match:
            current = []
            stages[match.group(1) or f"<anonymous-{len(stages)}>"] = current
        current.append(line)
    return stages


def _compose_web_service() -> list[str]:
    """The `web:` service block of docker-compose.yml, as stripped lines."""
    lines = _COMPOSE.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip() == "  web:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    ") and not line.startswith("#"):
            break
        block.append(line.strip())
    return block


@pytest.mark.spec("req-tap-serving-unprivileged-1")
def test_the_serving_stage_declares_a_non_root_user() -> None:
    """The `final` stage — the one that actually ships — drops root, and says so."""
    final = _stages()["final"]
    users = [line.split(maxsplit=1)[1].strip() for line in final if line.upper().startswith("USER ")]
    assert users, "the final stage declares no USER — the container serves as root (tap#754)"
    assert users[-1] == _IMAGE_USER, users
    assert users[-1] not in {"root", "0", "0:0"}, users


@pytest.mark.spec("req-tap-serving-unprivileged-3")
def test_the_root_only_image_setup_happens_before_the_drop_not_after() -> None:
    """`openssl fipsinstall` writes /etc/ssl; as nonroot it cannot.

    This is the ordering that made the drop land in `final` rather than in `app`. Asserted
    because the natural place to "tidy" a `USER` line is next to the other ENV/WORKDIR
    setup, and doing so would break the FIPS build rather than the serving posture — a
    failure one stage away from the edit that caused it.
    """
    stages = _stages()
    for name in ("app", "fips-0", "fips-1"):
        assert not [line for line in stages[name] if line.upper().startswith("USER ")], name


@pytest.mark.spec("req-tap-serving-unprivileged-3")
def test_the_build_stage_supply_chain_control_is_untouched() -> None:
    """`USER node` in js-vendor is a DIFFERENT control and must not be collateral.

    It exists so a hostile npm tarball extracts as `node` rather than root, on a different
    base image, in a stage that never ships. A sweep over "USER directives" that removed or
    moved it would weaken the build while the serving posture looked improved.
    """
    assert [line for line in _stages()["js-vendor"] if line.upper().startswith("USER ")] == ["USER node"]


@pytest.mark.spec("req-tap-serving-unprivileged-2")
def test_every_runtime_writable_mount_target_is_prepared_in_the_image() -> None:
    """A mount target the image does not create comes out root-owned and kills the boot.

    Docker initializes a fresh named volume from the image directory at its mount path,
    including ownership and mode — so preparation in the image IS the mechanism by which an
    unprivileged entrypoint gets a writable venv and uv cache. Nothing chowns them later:
    the entrypoint has already dropped root by the time it runs.
    """
    runs = re.findall(r"^RUN .+?(?=\n[A-Z#])", _DOCKERFILE.read_text(), re.MULTILINE | re.DOTALL)
    prep = [run for run in runs if "/app/.venv" in run]
    assert len(prep) == 1, "no single runtime-directory preparation RUN found in the Dockerfile"
    body = prep[0]
    for target in _PREPARED_MOUNT_TARGETS:
        assert target in body, f"{target} is mounted at runtime but never prepared: {body}"
    assert "chown" in body and ":0" in body, body
    assert "g+rwX" in body or "g+w" in body, body


@pytest.mark.spec("req-tap-serving-unprivileged-2")
def test_compose_mounts_the_named_volumes_at_the_paths_the_image_prepared() -> None:
    """The two halves of each mount are written in two files; this compares them.

    The uv cache moved off `/root/.cache/uv` — root's home, which a non-root container
    cannot use. If the compose target and the image's `UV_CACHE_DIR` drift apart, the
    volume mounts at a path nothing prepared and `uv sync` dies at container start.
    """
    text = _DOCKERFILE.read_text()
    cache_dir = re.search(r"^ENV UV_CACHE_DIR=(\S+)$", text, re.MULTILINE)
    assert cache_dir, "the image does not declare UV_CACHE_DIR"
    assert cache_dir.group(1) in _PREPARED_MOUNT_TARGETS, cache_dir.group(1)
    assert not cache_dir.group(1).startswith("/root/"), cache_dir.group(1)

    web = _compose_web_service()
    mounts = {entry.split(":", 1)[1] for entry in (line.lstrip("- ") for line in web) if ":/" in entry}
    assert f"{cache_dir.group(1)}" in mounts, mounts
    assert "/app/.venv" in mounts, mounts


@pytest.mark.spec("req-tap-serving-unprivileged-1")
def test_compose_never_hands_the_web_service_back_to_uid_zero() -> None:
    """Development overrides the UID — for bind-mount writability — but never to 0.

    The override exists because `.:/app` is host-owned: on Linux the container must run as
    the host uid or it cannot write the tree it serves from. `scripts/dc` supplies it. The
    failure mode this guards is the shortcut that "fixes" a permission error on someone's
    machine by pinning the uid back to root.
    """
    user = [line for line in _compose_web_service() if line.startswith("user:")]
    assert len(user) == 1, user
    value = user[0].split(":", 1)[1].strip().strip('"')
    uid = re.match(r"^\$\{TAP_UID:-(?P<default>[^}]*)\}", value)
    assert uid, f"the uid is not the host-supplied TAP_UID with a default: {value}"
    assert uid.group("default") not in {"0", "root", ""}, value


@pytest.mark.spec("req-tap-serving-unprivileged-4")
def test_dc_supplies_the_host_uid_so_a_linux_bind_mount_stays_writable() -> None:
    """The compose default (65532) is only correct where bind-mount ownership is mapped.

    On Docker Desktop for macOS any uid can write the mount, so a fixed 65532 looks fine;
    on Linux the write is refused unless the uid owns the tree. `scripts/dc` exports the
    invoking user's uid so the two platforms run the same way — and so the mac developer is
    exercising the path a Linux developer gets, rather than a luckier one.
    """
    assert re.search(r"^export TAP_UID=", (_REPO_ROOT / "scripts" / "dc").read_text(), re.MULTILINE)


@pytest.mark.spec("req-tap-serving-unprivileged-2")
def test_the_persisted_plugin_set_lands_where_an_unprivileged_process_can_write_it() -> None:
    """`/run` is root-owned; the entrypoint can no longer create a path in it.

    The file moved into a directory the image prepares. Its two ends live in bash and in
    Python, so they are compared rather than trusted: a mismatch would not fail the boot,
    it would silently drop every sibling exec back to the warned discovery fallback — the
    importlib mtime race that produced a registered type with no migrated table.
    """
    written = re.search(r"> (/run/\S+)", _ENTRYPOINT.read_text())
    assert written, "the entrypoint no longer persists TAP_PLUGINS"
    assert written.group(1) == preboot.TAP_PLUGINS_FILE_DEFAULT
    parent = str(Path(preboot.TAP_PLUGINS_FILE_DEFAULT).parent)
    assert parent != "/run", "a non-root entrypoint cannot create a file directly in /run"
    assert parent in _DOCKERFILE.read_text(), f"{parent} is written at boot but never prepared"
