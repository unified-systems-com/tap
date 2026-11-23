"""The chain of versions: the links a type's author keeps between one version and the next.

``req-grid-entity-model-version`` rules 9 to 17, and rule 5 of ``req-grid-entity-spine-version``.
For every version after the first a type has one link from the version before it. A link is a
:class:`Step`, which takes what one record asserts at version N and returns it at N+1, or a
:class:`Break`, which says no step exists.

Where links are declared
------------------------
In a module named ``model_links`` at the root of the package that owns the types, holding one
name, ``LINKS``: a mapping from a type slug to its :class:`TypeLinks`. A plugin's is
``tap_plugin/<slug>/model_links.py``; a core app's is ``<app>/model_links.py``; the spine's entry
is keyed :data:`SPINE` in ``tap_grid``'s. One form for a node type, an edge type and the spine,
because an edge type has no class to hang a declaration on and the spine has no type.

The module is deliberately apart from the models. A step must keep working as the class moves on
(rule 10), so it takes and returns plain mappings and never imports the model class; a module of
its own makes that the natural thing to write. It is found by name, with Django's own
``autodiscover_modules``, the first time links are asked for, so an app that declares none pays
nothing and a manifest needs no new key.

A link is keyed by the version it arrives at: ``{2: Step(...)}`` is the link from 1 to 2.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: The key the spine's chain is declared under.
SPINE = "spine"
#: The module an app declares its links in, and the name inside it.
LINKS_MODULE = "model_links"
LINKS_NAME = "LINKS"
FIRST_VERSION = 1


class RecordRefused(Exception):
    """Raised by a step that cannot upgrade one record, with the reason (rule 11, rule 13)."""


@dataclass(frozen=True)
class Step:
    """One record at version N to the same record at N+1.

    ``upgrade`` is given what the record asserts, which may be partial (rule 11), and returns it
    at the next version. It reads that mapping and nothing else. It raises
    :class:`RecordRefused` for a record it cannot carry.

    What it costs is declared, not inferred (rule 13):

    - ``drops``: fields of version N that version N+1 has no place for;
    - ``renames``: new field name -> the one old field it is;
    - ``derived``: new field name -> the old field it is built from. A tuple of several old
      fields is refused by the guard: a FLIP entry names one source for a field (rule 31);
    - ``may_refuse``: why some records may be refused, where they may;
    - ``key``: the natural key at version N to the key at N+1, where the version changes it
      (rule 12); ``key_refused`` is the reason no such function exists.
    """

    upgrade: Callable[[dict[str, Any]], dict[str, Any]]
    drops: tuple[str, ...] = ()
    renames: Mapping[str, str] = field(default_factory=dict)
    derived: Mapping[str, Any] = field(default_factory=dict)
    may_refuse: str = ""
    key: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    key_refused: str = ""


@dataclass(frozen=True)
class Break:
    """No step exists from version N to N+1 (rule 14)."""

    reason: str
    successor: str = ""


Link = Step | Break


@dataclass(frozen=True)
class TypeLinks:
    """A type's chain: one link per version after the first, and the oldest version still imported."""

    links: Mapping[int, Link] = field(default_factory=dict)
    oldest: int = FIRST_VERSION


_NO_LINKS = TypeLinks()
_declared: dict[str, TypeLinks] = {}
_discovered = False


def declare(type_slug: str, links: Mapping[int, Link] | TypeLinks, *, oldest: int = FIRST_VERSION) -> None:
    """Record a type's chain. What ``LINKS`` in a ``model_links`` module is read into."""
    chain = links if isinstance(links, TypeLinks) else TypeLinks(links=dict(links), oldest=oldest)
    _declared[type_slug] = chain


def forget(type_slug: str) -> None:
    """Remove a declared chain. For tests."""
    _declared.pop(type_slug, None)


def _discover() -> None:
    """Read ``LINKS`` from every installed app's ``model_links`` module, once per process."""
    global _discovered
    if _discovered:
        return
    from django.apps import apps
    from django.utils.module_loading import autodiscover_modules

    if not apps.ready:
        return
    _discovered = True
    autodiscover_modules(LINKS_MODULE)
    for config in apps.get_app_configs():
        module = sys.modules.get(f"{config.name}.{LINKS_MODULE}")
        declared = getattr(module, LINKS_NAME, None) if module is not None else None
        if not isinstance(declared, Mapping):
            continue
        for type_slug, chain in declared.items():
            # A chain a test or an earlier app declared is not overwritten silently.
            if type_slug in _declared:
                logger.warning("[9b41] %s declares links for %s, which already has a chain", config.name, type_slug)
                continue
            declare(type_slug, chain)


def links_for(type_slug: str) -> TypeLinks:
    """The chain declared for a type; an empty one where its owner declared none."""
    _discover()
    return _declared.get(type_slug, _NO_LINKS)


def any_declared() -> bool:
    _discover()
    return bool(_declared)


def describe(arrives_at: int) -> str:
    """How a link is named in a refusal: by the two versions it joins."""
    return f"version {arrives_at - 1} to {arrives_at}"


def declaration_problems(label: str, type_slug: str, declared_version: int) -> list[str]:
    """What is wrong with a type's chain on its own (rules 9, 13, 16, 17 and 31).

    A type above version 1 needs one link for every version after the first. A link keyed
    outside that range, a step that is not callable, an ``oldest`` beyond the declared version,
    and a field built from more than one old field are each a problem.
    """
    chain = links_for(type_slug)
    problems: list[str] = []
    for version in range(FIRST_VERSION + 1, declared_version + 1):
        link = chain.links.get(version)
        if link is None:
            problems.append(
                f"{label}: version {declared_version} is declared and no link is declared from "
                f"{describe(version)}. Every version after the first needs a step or a declared break "
                f"({LINKS_MODULE}.py, {LINKS_NAME}[{type_slug!r}])"
            )
            continue
        if isinstance(link, Break):
            if not link.reason:
                problems.append(f"{label}: the break from {describe(version)} gives no reason")
            continue
        if not isinstance(link, Step) or not callable(link.upgrade):
            problems.append(f"{label}: the link from {describe(version)} is neither a step nor a declared break")
            continue
        for new_field, source in sorted(link.derived.items()):
            if not isinstance(source, str):
                problems.append(
                    f"{label}: the step from {describe(version)} builds {new_field!r} from more than one old "
                    f"field ({', '.join(map(str, source))}). A field's source attribution names one source, so "
                    "a field built from several cannot carry one: keep the old fields beside the new one, or "
                    "declare a break"
                )
    for version in sorted(chain.links):
        if version <= FIRST_VERSION or version > declared_version:
            problems.append(
                f"{label}: a link is declared arriving at version {version}, and the type is declared at "
                f"version {declared_version}"
            )
    if chain.oldest < FIRST_VERSION or chain.oldest > declared_version:
        problems.append(
            f"{label}: the oldest version still imported is declared as {chain.oldest}, outside versions "
            f"{FIRST_VERSION} to {declared_version}"
        )
    return problems
