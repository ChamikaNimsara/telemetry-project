"""Tests for the executable analysis dataset contract."""

from pathlib import Path

import pandas as pd
import pytest

from telemetry_project.data.schema import (
    ANALYSIS_COLUMNS,
    FEATURE_COLUMNS,
    TARGET_COLUMNS,
    SchemaValidationError,
    read_analysis_csv,
    validate_analysis_dataset,
)


def valid_frame() -> pd.DataFrame:
    values: dict[str, list[object]] = {
        "sample_id": ["2024-01-R:1:1:1"],
        "event_id": ["2024-01-R"],
        "season": [2024],
        "round_number": [1],
        "event_name": ["Example Grand Prix"],
        "session_code": ["R"],
        "split": ["train"],
        "source_id": ["/static/2024/example/"],
        "driver_number": ["1"],
        "team": ["Example"],
        "stint": [1],
        "lap_number": [1],
        "stint_lap_index": [1],
        "compound": ["MEDIUM"],
        "tyre_life_laps": [1.0],
        "fresh_tyre": [True],
        "position": [1],
        "track_status": ["1"],
        "air_temp_c": [25.0],
        "track_temp_c": [35.0],
        "humidity_percent": [50.0],
        "pressure_mbar": [1000.0],
        "wind_speed_mps": [2.0],
        "wind_direction_deg": [180.0],
        "rainfall": [False],
        "current_lap_time_seconds": [90.0],
        "sector1_seconds": [30.0],
        "sector2_seconds": [30.0],
        "sector3_seconds": [30.0],
        "previous_lap_time_seconds": [None],
        "previous_lap_delta_seconds": [None],
        "next_lap_time_seconds": [91.0],
        "next_lap_delta_seconds": [1.0],
    }
    return pd.DataFrame(values, columns=ANALYSIS_COLUMNS)


def test_valid_dataset_satisfies_contract() -> None:
    validate_analysis_dataset(valid_frame())


def test_schema_reports_missing_column() -> None:
    with pytest.raises(SchemaValidationError, match="missing columns: team"):
        validate_analysis_dataset(valid_frame().drop(columns="team"))


def test_schema_reports_range_and_nullability_violations() -> None:
    frame = valid_frame()
    frame.loc[0, "humidity_percent"] = 101.0
    frame.loc[0, "next_lap_time_seconds"] = None

    with pytest.raises(SchemaValidationError) as error:
        validate_analysis_dataset(frame)

    assert "humidity_percent contains values above 100" in str(error.value)
    assert "next_lap_time_seconds contains null values" in str(error.value)


def test_targets_are_never_declared_as_features() -> None:
    assert set(FEATURE_COLUMNS).isdisjoint(TARGET_COLUMNS)


def test_generated_csv_preserves_string_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "dataset.csv"
    valid_frame().to_csv(path, index=False)

    loaded = read_analysis_csv(str(path))

    assert loaded.loc[0, "driver_number"] == "1"
    assert loaded.loc[0, "track_status"] == "1"
