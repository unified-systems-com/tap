"""TAP Plugin Validator — standalone CLI.

Usage:
    python -m tap_plugins.validate_plugin /path/to/plugin
    python -m tap_plugins.validate_plugin /path/to/plugin --json
    python -m tap_plugins.validate_plugin /path/to/plugin --strict
    python -m tap_plugins.validate_plugin /path/to/plugin --level structure

Exit codes:
    0  Validation succeeded
    1  Validation failed
    2  Usage or configuration error
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

DESCRIPTION = """\
Validate a TAP plugin root directory.

Checks that the plugin's manifest, directory layout, edge definition files,
and GRIFT paths are structurally correct.  Does not require Django startup.
"""

EPILOG = """\
exit status:
  0   validation succeeded
  1   validation failed
  2   usage or configuration error

examples:
  %(prog)s plugins/grid_fixtures
  %(prog)s plugins/grid_fixtures --json
  %(prog)s plugins/grid_fixtures --strict
  %(prog)s plugins/grid_fixtures --level structure --json
"""


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser whose help output is the CLI's man page.

    TAP-IMPLEMENTS: req-tap-plugin-validate-help@7d96f6c62e4c/1e9180728659 (surface) — the
        man-page-style -h/--help screen: description, flags, exit statuses, examples.
    """
    parser = argparse.ArgumentParser(
        prog="python -m tap_plugins.validate_plugin",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "plugin_root",
        type=Path,
        help="path to the plugin root directory",
    )
    parser.add_argument(
        "--level",
        default="structure",
        help="validation level (default: structure; loads and runs are reserved)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="emit machine-readable JSON output",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="promote warnings to failures",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the standalone validator CLI and return its exit code.

    TAP-IMPLEMENTS: req-tap-plugin-validate-cli@0d7faa29bf56/3dcdb570053a (surface) — the
        `python -m tap_plugins.validate_plugin` entry point: one path argument, --json,
        --strict, structure-only with redirects to the management command.
    TAP-IMPLEMENTS: req-tap-plugin-validate-exit@cfd4920d0241/3dcdb570053a (derivation) — the
        stable exit-code contract: 0 success, 1 validation failure, 2 usage/configuration
        error (including unknown and Django-required levels).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    from tap_plugins.validate.service import (
        DJANGO_REQUIRED_LEVELS,
        KNOWN_LEVELS,
        UnsupportedLevelError,
        validate_plugin,
    )

    if args.level not in KNOWN_LEVELS:
        print(
            f"Error: unknown validation level {args.level!r}. " f"Known levels: {', '.join(sorted(KNOWN_LEVELS))}",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    if args.level in DJANGO_REQUIRED_LEVELS:
        print(
            f"Error: validation level {args.level!r} requires Django.\n"
            f"Use the management command instead:\n"
            f"  python manage.py validate_plugin <plugin_root> --level {args.level}",
            file=sys.stderr,
        )
        return EXIT_USAGE_ERROR

    plugin_root = args.plugin_root.resolve()

    try:
        result = validate_plugin(
            plugin_root,
            level=args.level,
            strict=args.strict,
        )
    except UnsupportedLevelError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_USAGE_ERROR

    if args.json_output:
        print(result.to_json())
    else:
        print(result.to_human())

    return EXIT_SUCCESS if result.ok else EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
