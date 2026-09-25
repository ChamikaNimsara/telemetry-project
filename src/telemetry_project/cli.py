"""Command-line interface for project utilities."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from telemetry_project import __version__
from telemetry_project.analysis.config import AnalysisConfigError, load_analysis_config
from telemetry_project.analysis.exploratory import (
    ExploratoryAnalysisError,
    run_exploratory_analysis,
)
from telemetry_project.analysis.performance import (
    PerformanceAnalysisError,
    run_race_performance_analysis,
)
from telemetry_project.analysis.performance_config import (
    PerformanceConfigError,
    load_performance_config,
)
from telemetry_project.config import resolve_cache_dir
from telemetry_project.data.acquisition import (
    AcquisitionValidationError,
    acquire_events,
)
from telemetry_project.data.dataset_config import (
    DatasetConfigError,
    load_dataset_config,
)
from telemetry_project.data.dataset_pipeline import DatasetBuildError, build_dataset
from telemetry_project.data.event_config import EventConfigError, load_event_config
from telemetry_project.data.manifest import write_manifest
from telemetry_project.modeling.baseline_config import (
    BaselineConfigError,
    load_baseline_config,
)
from telemetry_project.modeling.baselines import (
    BaselineEvaluationError,
    run_baseline_evaluation,
)
from telemetry_project.modeling.experiments import (
    ModelExperimentError,
    evaluate_final,
    select_model,
)
from telemetry_project.modeling.selection_config import (
    ModelConfigError,
    load_final_model_config,
    load_selection_config,
)
from telemetry_project.release_audit import ReleaseAuditError, run_release_audit
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

    dataset_parser = commands.add_parser(
        "build-dataset",
        help="Build and audit the leakage-safe analysis dataset.",
    )
    dataset_parser.add_argument(
        "--config", type=Path, default=Path("configs/dataset.yaml")
    )

    analysis_parser = commands.add_parser(
        "analyze-data",
        help="Generate development-only exploratory analysis and figures.",
    )
    analysis_parser.add_argument(
        "--config", type=Path, default=Path("configs/analysis.yaml")
    )
    performance_parser = commands.add_parser(
        "analyze-performance",
        help="Compare two configured laps using distance-aligned telemetry.",
    )
    performance_parser.add_argument(
        "--config", type=Path, default=Path("configs/race-performance.yaml")
    )
    performance_parser.add_argument("--cache-dir", type=Path)
    performance_parser.add_argument(
        "--offline",
        action="store_true",
        help="Require the configured session telemetry to exist in the cache.",
    )
    baseline_parser = commands.add_parser(
        "evaluate-baselines",
        help="Fit training-only baselines and evaluate validation events.",
    )
    baseline_parser.add_argument(
        "--config", type=Path, default=Path("configs/baseline.yaml")
    )
    selection_parser = commands.add_parser(
        "select-model",
        help="Compare frozen candidates using training and validation only.",
    )
    selection_parser.add_argument(
        "--config", type=Path, default=Path("configs/model-selection.yaml")
    )
    final_parser = commands.add_parser(
        "evaluate-final",
        help="Evaluate the frozen selected method on held-out test events.",
    )
    final_parser.add_argument(
        "--config", type=Path, default=Path("configs/final-model.yaml")
    )
    audit_parser = commands.add_parser(
        "release-audit",
        help="Check the public release candidate for packaging risks.",
    )
    audit_parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/release-audit.json"),
    )
    dataset_parser.add_argument("--cache-dir", type=Path)
    dataset_parser.add_argument(
        "--offline",
        action="store_true",
        help="Require lap and weather responses to exist in the FastF1 cache.",
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
            event_config = load_event_config(args.config)
            selected = (
                frozenset(args.only_events) if args.only_events is not None else None
            )
            manifest = acquire_events(
                event_config,
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

    if args.command == "build-dataset":
        try:
            dataset_config = load_dataset_config(args.config)
            dataset_summary = build_dataset(
                dataset_config,
                cache_dir=resolve_cache_dir(args.cache_dir),
                offline=args.offline,
            )
        except (
            DatasetBuildError,
            DatasetConfigError,
            EventConfigError,
            OSError,
        ) as error:
            print(f"Dataset build error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(dataset_summary), indent=2))
        return 0

    if args.command == "analyze-data":
        try:
            analysis_config = load_analysis_config(args.config)
            analysis_summary = run_exploratory_analysis(analysis_config)
        except (AnalysisConfigError, ExploratoryAnalysisError, OSError) as error:
            print(f"Exploratory analysis error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(analysis_summary), indent=2))
        return 0

    if args.command == "analyze-performance":
        try:
            performance_config = load_performance_config(args.config)
            performance_summary = run_race_performance_analysis(
                performance_config,
                cache_dir=resolve_cache_dir(args.cache_dir),
                offline=args.offline,
            )
        except (PerformanceConfigError, PerformanceAnalysisError, OSError) as error:
            print(f"Race-performance analysis error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(performance_summary), indent=2))
        return 0

    if args.command == "evaluate-baselines":
        try:
            baseline_config = load_baseline_config(args.config)
            baseline_summary = run_baseline_evaluation(baseline_config)
        except (BaselineConfigError, BaselineEvaluationError, OSError) as error:
            print(f"Baseline evaluation error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(baseline_summary), indent=2))
        return 0

    if args.command == "select-model":
        try:
            selection_config = load_selection_config(args.config)
            selection_summary = select_model(selection_config)
        except (ModelConfigError, ModelExperimentError, OSError) as error:
            print(f"Model selection error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(selection_summary), indent=2))
        return 0

    if args.command == "evaluate-final":
        try:
            final_config = load_final_model_config(args.config)
            final_summary = evaluate_final(final_config)
        except (ModelConfigError, ModelExperimentError, OSError) as error:
            print(f"Final evaluation error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(final_summary), indent=2))
        return 0

    if args.command == "release-audit":
        try:
            audit = run_release_audit(Path.cwd(), output=args.output)
        except (OSError, ReleaseAuditError) as error:
            print(f"Release audit error: {error}", file=sys.stderr)
            return 2
        print(json.dumps(asdict(audit), indent=2))
        return 0 if audit.passed else 1

    raise AssertionError(f"Unhandled command: {args.command}")


def entrypoint() -> None:
    """Console-script entry point."""
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()
