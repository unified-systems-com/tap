"""The data-directory facts the plugin report carries (`req-tap-plugin-datadir-report`).

Per plugin, the declaration, where the directory is and whether it is as provisioned, its measured
size with the time it was taken, its executable files and a bounded top-level listing. Once for the
instance, whether the volume is enabled and, when it is, its verdict, filesystem, free space and the
orphans and strays under it. The command line and the plugin status page show the same thing
because both read this, and neither walks the filesystem itself.
"""

from __future__ import annotations

from typing import Any

from tap_plugins.datadir import _facts, _placement


def plugin_section(slug: str, declaration: Any, *, budget_s: float = _facts.WALK_BUDGET_S) -> dict[str, Any]:
    """The report's ``data_directory`` object for one plugin."""
    if declaration is None:
        return {"declared": False}
    section: dict[str, Any] = {
        "declared": True,
        "purpose": declaration.purpose,
        "durability": declaration.durability,
        "max_bytes": declaration.max_bytes,
        "executes": declaration.executes,
    }
    placement = _placement.place(slug, declaration.durability)
    if placement.root is None:
        section.update({"path": None, "location": None, "placement_refusal": placement.refusal})
        section.update({"exists": False, "as_provisioned": False, "detail": placement.refusal})
        section["measurement"] = {"available": False, "reason": placement.refusal, "measured_at": _facts._now()}
        section["executables"] = []
        section["executables_cut"] = False
        section["listing"] = {"entries": [], "cut": False}
        return section
    path = placement.path
    assert path is not None  # nosec B101
    section.update({"path": str(path), "location": "ephemeral" if placement.ephemeral else "volume"})
    section["placement_refusal"] = ""
    section.update(_facts.ownership(path))
    # Measured whenever it is a real directory, even one with the wrong owner or mode: the
    # operator still needs to see what is in it.
    if section["exists"] and not path.is_symlink() and path.is_dir():
        measured = _facts.measure(path, budget_s=budget_s)
        listing = _facts.listing(path)
    else:
        measured = {"available": False, "reason": section["detail"] or "missing", "measured_at": _facts._now()}
        listing = {"entries": [], "cut": False}
    section["executables"] = measured.pop("executables", [])
    section["executables_cut"] = measured.pop("executables_cut", False)
    section["measurement"] = measured
    section["listing"] = listing
    return section


def instance_section(declared: set[str]) -> dict[str, Any]:
    """The report's top-level ``plugin_data`` object."""
    root = _placement.volume_root()
    verdict = _placement.volume_verdict()
    if root is None or verdict is None:
        ephemeral = _placement.EPHEMERAL_ROOT
        classified = _facts.classify_root(ephemeral, declared) if ephemeral.is_dir() else {"orphans": [], "strays": []}
        return {
            "volume_enabled": False,
            "volume_root": None,
            "verdict": None,
            "ephemeral_root": str(ephemeral),
            "filesystem": None,
            **classified,
        }
    usable = verdict.usable
    return {
        "volume_enabled": True,
        "volume_root": str(root),
        "verdict": {"usable": usable, "check": verdict.check, "reason": verdict.reason},
        "ephemeral_root": str(_placement.EPHEMERAL_ROOT),
        "filesystem": _facts.filesystem(root) if usable else None,
        **(_facts.classify_root(root, declared) if usable else {"orphans": [], "strays": []}),
    }


__all__ = ["instance_section", "plugin_section"]
