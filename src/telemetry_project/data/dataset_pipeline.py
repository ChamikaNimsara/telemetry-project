"""End-to-end audited construction of the versioned analysis dataset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd

from telemetry_project.data.cleaning import (
    EXCLUSION_ORDER,
    EventAudit,
    clean_event_laps,
    summarize_event,
)
from telemetry_project.data.dataset_config import DatasetConfig
from telemetry_project.data.event_config import load_event_config
from telemetry_project.data.features import build_analysis_rows
from telemetry_project.data.schema import (
    ANALYSIS_COLUMNS,
    DATASET_SCHEMA_VERSION,
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    read_analysis_csv,
    validate_analysis_dataset,
)
from telemetry_project.data.splits import event_ids_by_split


class DatasetBuildError(ValueError):
    """Raised when inputs or loaded sessions cannot produce a valid dataset."""


@dataclass(frozen=True, slots=True)
class DatasetBuildSummary:
    """Compact CLI result for a completed build."""

    events: int
    raw_laps: int
    samples: int
    train_samples: int
    validation_samples: int
    test_samples: int
    dataset_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _write_csv(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    frame.to_csv(
        temporary,
        index=False,
        lineterminator="\n",
        float_format="%.6f",
    )
    temporary.replace(path)
    return _sha256(path)


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetBuildError(
            f"Unable to read acquisition manifest '{path}': {error}"
        ) from error
    if not isinstance(payload, dict):
        raise DatasetBuildError("Acquisition manifest root must be a JSON object.")
    if payload.get("manifest_schema_version") != 1:
        raise DatasetBuildError("Acquisition manifest schema version must be 1.")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        raise DatasetBuildError("Acquisition manifest must contain event records.")
    failed = [event for event in events if event.get("status") != "success"]
    if failed:
        raise DatasetBuildError(
            f"Acquisition manifest contains {len(failed)} unsuccessful event(s)."
        )
    return payload


def _event_id(record: dict[str, Any]) -> str:
    year = int(record["year"])
    round_number = int(record["round_number"])
    session = str(record["session_code"])
    return f"{year}-{round_number:02d}-{session}"


def _load_event(
    record: dict[str, Any], config: DatasetConfig
) -> tuple[pd.DataFrame, EventAudit]:
    session = fastf1.get_session(
        int(record["year"]),
        str(record["requested_event"]),
        str(record["session_code"]),
    )
    session.load(laps=True, telemetry=False, weather=True, messages=False)
    weather = session.laps.get_weather_data()
    event_id = _event_id(record)
    cleaned = clean_event_laps(
        session.laps,
        weather,
        event_id=event_id,
        event_name=str(record["resolved_event"]),
        split=str(record["split"]),
        source_id=str(record["source_id"]),
        season=int(record["year"]),
        round_number=int(record["round_number"]),
        session_code=str(record["session_code"]),
        policy=config.eligibility,
    )
    rows, pairs = build_analysis_rows(
        cleaned,
        minimum_consecutive_laps=config.eligibility.minimum_consecutive_eligible_laps,
    )
    audit = summarize_event(
        cleaned,
        target_pairs_before_minimum=pairs,
        final_samples=len(rows),
    )
    return rows, audit


def _render_quality_report(
    audits: list[EventAudit], config: DatasetConfig, source_manifest_sha256: str
) -> str:
    raw_laps = sum(audit.raw_laps for audit in audits)
    samples = sum(audit.final_samples for audit in audits)
    base_eligible = sum(audit.base_eligible_laps for audit in audits)
    weather_missing = sum(audit.weather_missing_rows for audit in audits)
    wet = sum(audit.wet_weather_rows for audit in audits)
    primary_counts = {
        reason: sum(audit.exclusion_counts.get(reason, 0) for audit in audits)
        for reason in EXCLUSION_ORDER
    }
    lines = [
        "# Data Quality Report",
        "",
        "**Scope:** US-04 validated analysis dataset",
        f"**Dataset version:** {config.dataset_version}",
        f"**Dataset schema:** {DATASET_SCHEMA_VERSION}",
        f"**Source manifest SHA-256:** `{source_manifest_sha256}`",
        "",
        "## Outcome",
        "",
        f"The audit examined {raw_laps:,} race laps across {len(audits)} events. "
        f"After lap-level eligibility and strict consecutive-target checks, "
        f"{samples:,} modelling samples remain from {base_eligible:,} "
        "base-eligible laps.",
        "",
        f"Weather is aligned to each lap. {weather_missing:,} rows lack required "
        f"weather values and {wet:,} rows report rainfall; both are excluded under "
        "the version 1 dry-running policy.",
        "",
        "## Event Coverage",
        "",
        "| Split | Event | Raw laps | Missing required | Base eligible | Target "
        "pairs | Final samples | Weather missing | Wet | Pit laps | Disrupted |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for audit in audits:
        lines.append(
            f"| {audit.split} | {audit.event_name} | {audit.raw_laps} | "
            f"{audit.missing_required_rows} | {audit.base_eligible_laps} | "
            f"{audit.target_pairs_before_minimum} | "
            f"{audit.final_samples} | {audit.weather_missing_rows} | "
            f"{audit.wet_weather_rows} | {audit.pit_laps} | "
            f"{audit.disrupted_track_status_rows} |"
        )
    lines.extend(
        [
            "",
            "## Exclusion Policy",
            "",
            "Each raw lap receives at most one primary exclusion reason in the "
            "documented precedence order. Counts therefore do not double-count a lap. "
            "A modelling sample is retained only when both the current and immediately "
            "following chronological lap are eligible, belong to the same driver and "
            "stint, and belong to a run of at least "
            f"{config.eligibility.minimum_consecutive_eligible_laps} consecutive "
            "eligible laps.",
            "",
            "| Primary reason | Excluded laps |",
            "|---|---:|",
        ]
    )
    lines.extend(
        f"| {reason.replace('_', ' ')} | {count} |"
        for reason, count in primary_counts.items()
    )
    lines.extend(
        [
            "",
            "Independent diagnostics can overlap: "
            f"{sum(audit.missing_required_rows for audit in audits)} rows have a "
            "missing required value, "
            f"{sum(audit.pit_laps for audit in audits)} are pit-in or pit-out laps, "
            f"{sum(audit.inaccurate_laps for audit in audits)} are marked inaccurate, "
            f"{sum(audit.disrupted_track_status_rows for audit in audits)} have a "
            "disrupted track status, and "
            f"{sum(audit.non_monotonic_time_rows for audit in audits)} have "
            "non-monotonic driver timing.",
            "",
            "The detailed mutually exclusive counts are in "
            "`reports/tables/data-quality-by-event.csv`. Duplicate lap keys, "
            "non-monotonic timing, missing weather, wet running, pit laps, deleted or "
            "inaccurate laps, non-slick compounds, implausible lap times, and "
            "disrupted "
            "track statuses are measured explicitly.",
            "",
            "## Target and Leakage Review",
            "",
            "The target is the lap time of the immediately next eligible consecutive "
            "lap. The pipeline never skips an excluded or missing intervening lap. "
            "Target columns are separated from the feature catalogue, while "
            "previous-lap features use only already-completed laps. Event groups are "
            "assigned from the "
            "frozen event configuration before processing, and automated validation "
            "requires train, validation, and test event IDs to be disjoint.",
            "",
            "## Missing Values and Limitations",
            "",
            "Rows missing required identity, target, tyre, current-lap, or weather "
            "features are excluded and counted. Sector times and previous-lap features "
            "remain nullable because valid FastF1 laps can lack a sector or can be the "
            "first eligible lap in a clean run; downstream preprocessing must learn "
            "any "
            "imputation from training events only.",
            "",
            "FastF1 corrections and source warnings remain recorded in the acquisition "
            "manifest. This dataset describes observed lap-time performance and must "
            "not "
            "be interpreted as a direct or causal measurement of physical tyre wear.",
            "",
        ]
    )
    return "\n".join(lines)


def build_dataset(
    config: DatasetConfig,
    *,
    cache_dir: Path,
    offline: bool = False,
) -> DatasetBuildSummary:
    """Build, validate, split, hash, and audit the analysis dataset."""
    event_config = load_event_config(config.source_event_config)
    acquisition = _load_manifest(config.source_acquisition_manifest)
    if acquisition.get("event_config_sha256") != event_config.source_sha256:
        raise DatasetBuildError(
            "Acquisition manifest does not match the current event configuration."
        )
    records = acquisition["events"]
    configured = {
        (event.year, event.event.casefold(), event.session, event.split)
        for event in event_config.events
    }
    manifested = {
        (
            int(record["year"]),
            str(record["requested_event"]).casefold(),
            str(record["session_code"]),
            str(record["split"]),
        )
        for record in records
    }
    if manifested != configured:
        raise DatasetBuildError(
            "Acquisition manifest event membership differs from the approved "
            "configuration."
        )

    resolved_cache = cache_dir.resolve()
    resolved_cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(resolved_cache))
    fastf1.Cache.offline_mode(offline)

    frames: list[pd.DataFrame] = []
    audits: list[EventAudit] = []
    for record in records:
        try:
            frame, audit = _load_event(record, config)
        except Exception as error:
            raise DatasetBuildError(
                f"Unable to build event '{record.get('requested_event')}': {error}"
            ) from error
        frames.append(frame)
        audits.append(audit)

    dataset = pd.concat(frames, ignore_index=True).sort_values(
        ["event_id", "driver_number", "stint", "lap_number"], kind="mergesort"
    )
    dataset = dataset.reset_index(drop=True).loc[:, ANALYSIS_COLUMNS]
    validate_analysis_dataset(dataset)
    if not dataset["split"].isin(("train", "validation", "test")).all():
        raise DatasetBuildError("Dataset contains an unknown split label.")

    output_records: list[dict[str, object]] = []
    for split in ("train", "validation", "test"):
        split_frame = dataset.loc[dataset["split"].eq(split)].reset_index(drop=True)
        validate_analysis_dataset(split_frame)
        output_path = config.outputs.processed_directory / f"{split}.csv"
        output_records.append(
            {
                "split": split,
                "path": output_path.as_posix(),
                "rows": len(split_frame),
                "sha256": _write_csv(split_frame, output_path),
            }
        )
        read_analysis_csv(str(output_path))

    combined_path = config.outputs.processed_directory / "analysis-dataset.csv"
    dataset_sha256 = _write_csv(dataset, combined_path)
    read_analysis_csv(str(combined_path))
    audit_frame = pd.DataFrame([audit.flat_dict() for audit in audits])
    _write_csv(audit_frame, config.outputs.audit_table)
    source_manifest_sha256 = _sha256(config.source_acquisition_manifest)
    report = _render_quality_report(audits, config, source_manifest_sha256)
    config.outputs.quality_report.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.quality_report.write_text(report, encoding="utf-8", newline="\n")

    events_by_split = event_ids_by_split(dataset)

    split_manifest = {
        "manifest_schema_version": 1,
        "dataset_version": config.dataset_version,
        "dataset_config_sha256": config.source_sha256,
        "event_config_sha256": event_config.source_sha256,
        "dataset_sha256": dataset_sha256,
        "grouping_key": "event_id",
        "frozen_test_split": True,
        "splits": {
            split: {
                "event_ids": events,
                "rows": int(dataset["split"].eq(split).sum()),
            }
            for split, events in events_by_split.items()
        },
    }
    _write_json(config.outputs.split_manifest, split_manifest)

    dataset_manifest = {
        "manifest_schema_version": 1,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "dataset_version": config.dataset_version,
        "dataset_config_path": config.source_path,
        "dataset_config_sha256": config.source_sha256,
        "event_config_path": event_config.source_path,
        "event_config_sha256": event_config.source_sha256,
        "acquisition_manifest_path": config.source_acquisition_manifest.as_posix(),
        "acquisition_manifest_sha256": source_manifest_sha256,
        "fastf1_version": fastf1.__version__,
        "cache_mode": "offline" if offline else "online",
        "feeds": ["laps", "weather", "session_metadata"],
        "dataset_path": combined_path.as_posix(),
        "dataset_sha256": dataset_sha256,
        "columns": list(ANALYSIS_COLUMNS),
        "feature_columns": list(FEATURE_COLUMNS),
        "target_columns": list(TARGET_COLUMNS),
        "rows": len(dataset),
        "raw_laps": sum(audit.raw_laps for audit in audits),
        "outputs": output_records,
        "events": [audit.flat_dict() for audit in audits],
    }
    _write_json(config.outputs.dataset_manifest, dataset_manifest)

    counts = dataset["split"].value_counts()
    return DatasetBuildSummary(
        events=len(audits),
        raw_laps=sum(audit.raw_laps for audit in audits),
        samples=len(dataset),
        train_samples=int(counts.get("train", 0)),
        validation_samples=int(counts.get("validation", 0)),
        test_samples=int(counts.get("test", 0)),
        dataset_sha256=dataset_sha256,
    )
