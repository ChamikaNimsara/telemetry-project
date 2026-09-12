"""Command-line interface for project utilities."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from telemetry_project import __version__
from telemetry_project.config import resolve_cache_dir
from telemetry_project.smoke import run_fastf1_smoke


def build_parser() -> argparse.ArgumentParser:
    """Build the project command-line parser."""
    parser = argparse.ArgumentParser(
        prog="telemetry-project",
        description="Reproducible motorsport telemetry project utilities.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    smoke_parser = commands.add_parser(
        "smoke-fastf1",
        help="Load lap timing for one FastF1 session.",
    )
    smoke_parser.add_argument("--year", type=int, default=2024)
    smoke_parser.add_argument("--event", default="Bahrain")
    smoke_parser.add_argument("--session", default="R", dest="session_code")
    smoke_parser.add_argument("--cache-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process status."""
    args = build_parser().parse_args(argv)
    if args.command == "smoke-fastf1":
        result = run_fastf1_smoke(
            year=args.year,
            event=args.event,
            session_code=args.session_code,
            cache_dir=resolve_cache_dir(args.cache_dir),
        )
        print(json.dumps(asdict(result), indent=2))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
