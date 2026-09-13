"""Executable contract for the version 1 analysis dataset."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import pandas as pd

DATASET_SCHEMA_VERSION = 1
ColumnKind = Literal["string", "integer", "number", "boolean"]
ColumnRole = Literal["identifier", "feature", "target", "provenance"]


class SchemaValidationError(ValueError):
    """Raised with all detected dataset-contract violations."""


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """Machine-readable definition of one canonical column."""

    name: str
    kind: ColumnKind
    role: ColumnRole
    nullable: bool
    unit: str | None
    minimum: float | None = None
    maximum: float | None = None


ANALYSIS_SCHEMA = (
    ColumnSpec("sample_id", "string", "identifier", False, None),
    ColumnSpec("event_id", "string", "identifier", False, None),
    ColumnSpec("season", "integer", "identifier", False, "year", 1950),
    ColumnSpec("round_number", "integer", "identifier", False, "round", 1),
    ColumnSpec("event_name", "string", "identifier", False, None),
    ColumnSpec("session_code", "string", "identifier", False, None),
    ColumnSpec("split", "string", "provenance", False, None),
    ColumnSpec("source_id", "string", "provenance", False, None),
    ColumnSpec("driver_number", "string", "identifier", False, None),
    ColumnSpec("team", "string", "feature", False, None),
    ColumnSpec("stint", "integer", "identifier", False, "stint", 1),
    ColumnSpec("lap_number", "integer", "identifier", False, "lap", 1),
    ColumnSpec("stint_lap_index", "integer", "feature", False, "lap", 1),
    ColumnSpec("compound", "string", "feature", False, None),
    ColumnSpec("tyre_life_laps", "number", "feature", False, "lap", 1),
    ColumnSpec("fresh_tyre", "boolean", "feature", False, None),
    ColumnSpec("position", "integer", "feature", False, "position", 1),
    ColumnSpec("track_status", "string", "feature", False, None),
    ColumnSpec("air_temp_c", "number", "feature", False, "degC", -20, 70),
    ColumnSpec("track_temp_c", "number", "feature", False, "degC", -20, 90),
    ColumnSpec("humidity_percent", "number", "feature", False, "%", 0, 100),
    ColumnSpec("pressure_mbar", "number", "feature", False, "mbar", 700, 1100),
    ColumnSpec("wind_speed_mps", "number", "feature", False, "m/s", 0),
    ColumnSpec("wind_direction_deg", "number", "feature", False, "degree", 0, 360),
    ColumnSpec("rainfall", "boolean", "feature", False, None),
    ColumnSpec("current_lap_time_seconds", "number", "feature", False, "s", 30, 300),
    ColumnSpec("sector1_seconds", "number", "feature", True, "s", 5, 150),
    ColumnSpec("sector2_seconds", "number", "feature", True, "s", 5, 150),
    ColumnSpec("sector3_seconds", "number", "feature", True, "s", 5, 150),
    ColumnSpec("previous_lap_time_seconds", "number", "feature", True, "s", 30, 300),
    ColumnSpec("previous_lap_delta_seconds", "number", "feature", True, "s", -120, 120),
    ColumnSpec("next_lap_time_seconds", "number", "target", False, "s", 30, 300),
    ColumnSpec("next_lap_delta_seconds", "number", "target", False, "s", -120, 120),
)
ANALYSIS_COLUMNS = tuple(spec.name for spec in ANALYSIS_SCHEMA)
FEATURE_COLUMNS = tuple(spec.name for spec in ANALYSIS_SCHEMA if spec.role == "feature")
TARGET_COLUMNS = tuple(spec.name for spec in ANALYSIS_SCHEMA if spec.role == "target")
UNIQUE_KEY = ("event_id", "driver_number", "stint", "lap_number")
STRING_COLUMNS = tuple(spec.name for spec in ANALYSIS_SCHEMA if spec.kind == "string")


def validate_analysis_dataset(frame: pd.DataFrame) -> None:
    """Validate canonical columns, nullability, types, ranges, and keys."""
    errors: list[str] = []
    missing = [column for column in ANALYSIS_COLUMNS if column not in frame.columns]
    extra = [column for column in frame.columns if column not in ANALYSIS_COLUMNS]
    if missing:
        errors.append(f"missing columns: {', '.join(missing)}")
    if extra:
        errors.append(f"unexpected columns: {', '.join(extra)}")
    if missing or extra:
        raise SchemaValidationError(
            "Dataset schema validation failed: " + "; ".join(errors)
        )
    for spec in ANALYSIS_SCHEMA:
        values = frame[spec.name]
        if not spec.nullable and values.isna().any():
            errors.append(f"{spec.name} contains null values")
        non_null = values.dropna()
        if (
            spec.kind == "string"
            and not non_null.map(lambda value: isinstance(value, str)).all()
        ):
            errors.append(f"{spec.name} must contain strings")
        elif (
            spec.kind == "boolean"
            and not non_null.map(lambda value: isinstance(value, bool)).all()
        ):
            errors.append(f"{spec.name} must contain booleans")
        elif spec.kind in {"integer", "number"}:
            numeric = pd.to_numeric(non_null, errors="coerce")
            if numeric.isna().any():
                errors.append(f"{spec.name} must contain numeric values")
            elif not numeric.map(isfinite).all():
                errors.append(f"{spec.name} must contain finite values")
            elif spec.kind == "integer" and not (numeric % 1 == 0).all():
                errors.append(f"{spec.name} must contain whole numbers")
            if spec.minimum is not None and (numeric < spec.minimum).any():
                errors.append(f"{spec.name} contains values below {spec.minimum}")
            if spec.maximum is not None and (numeric > spec.maximum).any():
                errors.append(f"{spec.name} contains values above {spec.maximum}")

    if frame.duplicated(list(UNIQUE_KEY)).any():
        errors.append(f"duplicate key values for {', '.join(UNIQUE_KEY)}")
    if frame["sample_id"].duplicated().any():
        errors.append("duplicate sample_id")
    if not frame["split"].isin(["train", "validation", "test"]).all():
        errors.append("split contains an unsupported value")
    if (frame["rainfall"] != False).any():  # noqa: E712
        errors.append("rainfall must be false for the dry-running dataset")
    if errors:
        raise SchemaValidationError(
            "Dataset schema validation failed: " + "; ".join(errors)
        )


def read_analysis_csv(path: str) -> pd.DataFrame:
    """Read a generated CSV without losing string identifier semantics."""
    frame = pd.read_csv(path, dtype={column: "string" for column in STRING_COLUMNS})
    validate_analysis_dataset(frame)
    return frame
