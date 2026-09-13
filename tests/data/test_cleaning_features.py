"""Tests for cleaning, eligibility, and time-valid target construction."""

import pandas as pd

from telemetry_project.data.cleaning import clean_event_laps, summarize_event
from telemetry_project.data.dataset_config import EligibilityConfig
from telemetry_project.data.features import build_analysis_rows


def policy() -> EligibilityConfig:
    return EligibilityConfig(
        slick_compounds=frozenset({"SOFT", "MEDIUM", "HARD"}),
        allowed_track_status=frozenset({"1"}),
        require_accurate_lap=True,
        exclude_deleted_laps=True,
        exclude_pit_in_laps=True,
        exclude_pit_out_laps=True,
        require_dry_weather=True,
        require_weather_coverage=True,
        minimum_consecutive_eligible_laps=2,
    )


def lap_frame(track_status: list[str] | None = None) -> pd.DataFrame:
    count = 5
    return pd.DataFrame(
        {
            "DriverNumber": ["1"] * count,
            "Team": ["Example"] * count,
            "LapTime": pd.to_timedelta([90, 91, 92, 93, 94], unit="s"),
            "LapNumber": [1.0, 2.0, 3.0, 4.0, 5.0],
            "Stint": [1.0] * count,
            "PitOutTime": [pd.NaT] * count,
            "PitInTime": [pd.NaT] * count,
            "Sector1Time": pd.to_timedelta([30] * count, unit="s"),
            "Sector2Time": pd.to_timedelta([30] * count, unit="s"),
            "Sector3Time": pd.to_timedelta([30, 31, 32, 33, 34], unit="s"),
            "Compound": ["MEDIUM"] * count,
            "TyreLife": [1.0, 2.0, 3.0, 4.0, 5.0],
            "FreshTyre": [True] * count,
            "TrackStatus": track_status or ["1"] * count,
            "Position": [1.0] * count,
            "Deleted": [False] * count,
            "IsAccurate": [True] * count,
            "Time": pd.to_timedelta([100, 191, 283, 376, 470], unit="s"),
        }
    )


def weather_frame(*, rainfall: list[bool] | None = None) -> pd.DataFrame:
    count = 5
    return pd.DataFrame(
        {
            "AirTemp": [25.0] * count,
            "Humidity": [45.0] * count,
            "Pressure": [1000.0] * count,
            "Rainfall": rainfall or [False] * count,
            "TrackTemp": [35.0] * count,
            "WindDirection": [180.0] * count,
            "WindSpeed": [2.0] * count,
        }
    )


def cleaned_frame(
    track_status: list[str] | None = None,
    rainfall: list[bool] | None = None,
) -> pd.DataFrame:
    return clean_event_laps(
        lap_frame(track_status),
        weather_frame(rainfall=rainfall),
        event_id="2024-01-R",
        event_name="Example Grand Prix",
        split="train",
        source_id="/static/2024/example/",
        season=2024,
        round_number=1,
        session_code="R",
        policy=policy(),
    )


def test_target_is_immediately_consecutive_and_never_skips_flagged_lap() -> None:
    cleaned = cleaned_frame(["1", "1", "4", "1", "1"])

    rows, pairs = build_analysis_rows(cleaned, minimum_consecutive_laps=2)

    assert pairs == 2
    assert rows["lap_number"].tolist() == [1, 4]
    assert rows["next_lap_time_seconds"].tolist() == [91.0, 94.0]
    assert rows["previous_lap_time_seconds"].isna().all()


def test_previous_lap_features_only_use_completed_laps() -> None:
    rows, pairs = build_analysis_rows(cleaned_frame(), minimum_consecutive_laps=3)

    assert pairs == 4
    assert rows["lap_number"].tolist() == [1, 2, 3, 4]
    assert pd.isna(rows.loc[0, "previous_lap_time_seconds"])
    assert rows.loc[1, "previous_lap_time_seconds"] == 90.0
    assert rows.loc[1, "previous_lap_delta_seconds"] == 1.0


def test_wet_lap_breaks_target_sequence_and_is_counted() -> None:
    cleaned = cleaned_frame(rainfall=[False, False, True, False, False])
    rows, pairs = build_analysis_rows(cleaned, minimum_consecutive_laps=2)
    audit = summarize_event(
        cleaned, target_pairs_before_minimum=pairs, final_samples=len(rows)
    )

    assert cleaned.loc[2, "exclusion_reason"] == "wet_weather"
    assert audit.wet_weather_rows == 1
    assert audit.exclusion_counts["wet_weather"] == 1
    assert audit.final_samples == 2


def test_minimum_run_length_excludes_short_pairs() -> None:
    cleaned = cleaned_frame(["1", "1", "4", "1", "1"])

    rows, pairs = build_analysis_rows(cleaned, minimum_consecutive_laps=3)

    assert pairs == 2
    assert rows.empty
