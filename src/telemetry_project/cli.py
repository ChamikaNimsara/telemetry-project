"""Command-line interface for project utilities."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from telemetry_project import __version__
from telemetry_project.config import resolve_cache_dir
from telemetry_project.data.acquisition import (
    AcquisitionValidationError,
    acquire_events,
)
from telemetry_project.data.event_config import EventConfigError, load_event_config
from telemetry_project.data.manifest import write_manifest
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

    acquire_parser = commands.add_parser(
        "acquire",
        help="Acquire and validate configured FastF1 sessions.",
    )
    acquire_parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/events.yaml"),
    )
    acquire_parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/event-manifest.json"),
    )
    acquire_parser.add_argument("--cache-dir", type=Path)
    acquire_parser.add_argument(
        "--only-event",
        action="append",
        dest="only_events",
        help="Acquire one configured event; repeat to select multiple events.",
    )
    acquire_parser.add_argument(
        "--offline",
        action="store_true",
        help="Require all FastF1 responses to be present in the local cache.",
    )
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

    if args.command == "acquire":
        try:
            config = load_event_config(args.config)
            selected = (
                frozenset(args.only_events) if args.only_events is not None else None
            )
            manifest = acquire_events(
                config,
                cache_dir=resolve_cache_dir(args.cache_dir),
                offline=args.offline,
                only_events=selected,
            )
            write_manifest(manifest, args.manifest)
        except (AcquisitionValidationError, EventConfigError, OSError) as error:
            print(f"Acquisition configuration error: {error}", file=sys.stderr)
            return 2

        output = {
            "manifest": args.manifest.as_posix(),
            **asdict(manifest.summary),
        }
        print(json.dumps(output, indent=2))
        return 0 if manifest.summary.failed == 0 else 1

    raise AssertionError(f"Unhandled command: {args.command}")


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
