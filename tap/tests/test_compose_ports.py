"""Published ports bind loopback unless told otherwise (tap#1158).

`docker-compose.yml` used to publish the web and Postgres ports as `"${WEB_PORT}:8000"`, with no host
address, so Docker listened on every interface: a dev stack with a database password that is a literal
in this public repo was reachable from the network. Every published port in a compose file in the repo
now names its host address, and unless `TAP_BIND` / `WEB_BIND` / `POSTGRES_BIND` say otherwise that
address is loopback.

The check reads the YAML and expands `${NAME:-default}` the way Compose does (nested defaults, an empty
value counts as unset), so it needs no Docker daemon.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Directories that hold other people's files or build output, not this repository's compose files.
_PRUNED = {".git", "node_modules", ".venv", "venv", "_dev-plugins", "build", "dist"}
_COMPOSE_NAME = re.compile(r"^(docker-)?compose[^/]*\.ya?ml$")


def compose_files(root: Path = _REPO_ROOT) -> list[Path]:
    """Every compose file under ``root``, at any depth: `docker-compose*.y[a]ml` and `compose*.y[a]ml`."""
    found = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if _PRUNED.intersection(rel.parts[:-1]) or not path.is_file():
            continue
        if _COMPOSE_NAME.match(path.name):
            found.append(path)
    return sorted(found)


_COMPOSE_FILES = compose_files()
_LOOPBACK = {"127.0.0.1", "::1"}
# `${NAME}` or `${NAME:-default}`, innermost first (the default may not itself contain `${`).
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^${}]*))?\}")


def expand(text: str, env: Mapping[str, str] | None = None) -> str:
    """Compose's interpolation for the forms used in port mappings: `${A}` and `${A:-default}`."""
    env = env or {}

    def one(match: re.Match[str]) -> str:
        value = env.get(match.group(1), "")
        return value if value else (match.group(2) or "")

    previous = None
    while previous != text:
        previous, text = text, _VAR.sub(one, text)
    return text


def published_ports(compose: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Every `ports:` entry of every service, as (service, entry)."""
    found: list[tuple[str, Any]] = []
    for name, service in (compose.get("services") or {}).items():
        for entry in (service or {}).get("ports") or []:
            found.append((name, entry))
    return found


def host_address(entry: Any, env: Mapping[str, str] | None = None) -> str | None:
    """The host address a port entry binds, or None when the entry names none (then Docker decides)."""
    if isinstance(entry, Mapping):  # long syntax
        raw = entry.get("host_ip")
        return expand(str(raw), env) or None if raw is not None else None
    text = expand(str(entry), env)
    text = text.split("/", 1)[0]  # drop /tcp, /udp
    if text.startswith("["):  # [::1]:8000:8000
        return text[1 : text.index("]")]
    parts = text.split(":")
    return parts[0] if len(parts) == 3 else None


def non_loopback_defaults(compose: Mapping[str, Any]) -> list[str]:
    """Published ports that, with nothing set, would not bind loopback."""
    bad = []
    for service, entry in published_ports(compose):
        if host_address(entry) not in _LOOPBACK:
            bad.append(f"{service}: {entry!r}")
    return bad


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.relative_to(_REPO_ROOT).as_posix())
def test_every_published_port_binds_loopback_by_default(path: Path) -> None:
    compose = yaml.safe_load(path.read_text())
    assert non_loopback_defaults(compose) == []


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
def test_compose_files_are_found_at_any_depth_and_under_either_name(tmp_path: Path) -> None:
    for rel in ("docker-compose.yml", "compose.yaml", "deploy/docker-compose.prod.yml", "a/b/compose.override.yml"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("services: {}\n")
    for rel in ("node_modules/x/docker-compose.yml", "_dev-plugins/p/compose.yml", "notes/compose-notes.txt"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("services: {}\n")
    found = {p.relative_to(tmp_path).as_posix() for p in compose_files(tmp_path)}
    assert found == {"docker-compose.yml", "compose.yaml", "deploy/docker-compose.prod.yml", "a/b/compose.override.yml"}


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
def test_the_repositorys_own_compose_files_are_all_found() -> None:
    names = {p.relative_to(_REPO_ROOT).as_posix() for p in _COMPOSE_FILES}
    assert {"docker-compose.yml", "docker-compose.ci.yml", "docker-compose.codespaces.yml", "docker-compose.build.yml"} <= names


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
def test_the_web_and_database_ports_are_actually_checked() -> None:
    """Guard against a vacuous pass: the base file publishes exactly these two."""
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose.yml").read_text())
    assert sorted(service for service, _ in published_ports(compose)) == ["db", "web"]


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
@pytest.mark.parametrize(
    "entry",
    [
        "8000:8000",
        "${WEB_PORT:-8000}:8000",
        "0.0.0.0:8000:8000",
        "${WEB_BIND:-0.0.0.0}:8000:8000",
        "${WEB_BIND:-${TAP_BIND:-0.0.0.0}}:8000:8000",
        "::8000:8000",
        {"target": 8000, "published": 8000},
        {"target": 8000, "published": 8000, "host_ip": "0.0.0.0"},
    ],
)
def test_the_check_rejects_a_port_that_would_listen_outward(entry: Any) -> None:
    assert non_loopback_defaults({"services": {"x": {"ports": [entry]}}}) != []


@pytest.mark.spec("req-dev-multisession-bind-loopback-1")
@pytest.mark.parametrize(
    "entry",
    ["127.0.0.1:8000:8000", "[::1]:8000:8000/tcp", {"target": 8000, "published": 8000, "host_ip": "127.0.0.1"}],
)
def test_the_check_accepts_a_loopback_port(entry: Any) -> None:
    assert non_loopback_defaults({"services": {"x": {"ports": [entry]}}}) == []


def _real_entries() -> dict[str, str]:
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose.yml").read_text())
    return {service: entry for service, entry in published_ports(compose)}


@pytest.mark.spec("req-dev-multisession-bind-loopback-2")
def test_tap_bind_opens_every_published_port() -> None:
    for entry in _real_entries().values():
        assert host_address(entry, {"TAP_BIND": "0.0.0.0"}) == "0.0.0.0"


@pytest.mark.spec("req-dev-multisession-bind-loopback-2")
def test_a_per_port_setting_opens_that_port_only_and_beats_tap_bind() -> None:
    entries = _real_entries()
    assert host_address(entries["web"], {"WEB_BIND": "0.0.0.0"}) == "0.0.0.0"
    assert host_address(entries["db"], {"WEB_BIND": "0.0.0.0"}) == "127.0.0.1"
    env = {"TAP_BIND": "0.0.0.0", "POSTGRES_BIND": "127.0.0.1"}
    assert host_address(entries["db"], env) == "127.0.0.1"
    assert host_address(entries["web"], env) == "0.0.0.0"


@pytest.mark.spec("req-dev-multisession-bind-loopback-2")
def test_an_empty_setting_falls_back_to_loopback() -> None:
    for entry in _real_entries().values():
        assert host_address(entry, {"TAP_BIND": "", "WEB_BIND": "", "POSTGRES_BIND": ""}) == "127.0.0.1"
