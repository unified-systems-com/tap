"""The core file store (`specs/spec-tap-file-store.md`).

Whole files kept for the grid in an OCFL 1.1 storage root on their own mounted volume, written once,
verified before they are released. Optional per instance: enabled exactly when `TAP_FILES_ROOT` is
set. Imports no plugin.
"""
