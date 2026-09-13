"""Construct time-valid features and the strictly next-lap target."""

from __future__ import annotations

import pandas as pd

from telemetry_project.data.schema import ANALYSIS_COLUMNS


def build_analysis_rows(
    cleaned: pd.DataFrame, *, minimum_consecutive_laps: int
) -> tuple[pd.DataFrame, int]:
    """Create samples without skipping an ineligible or non-consecutive lap."""
    frame = cleaned.copy()
    previous_same = (
        frame["driver_number"].eq(frame["driver_number"].shift())
        & frame["stint"].eq(frame["stint"].shift())
        & frame["lap_number"].eq(frame["lap_number"].shift() + 1)
        & frame["base_eligible"]
        & frame["base_eligible"].shift(fill_value=False)
    )
    next_same = (
        frame["driver_number"].eq(frame["driver_number"].shift(-1))
        & frame["stint"].eq(frame["stint"].shift(-1))
        & frame["lap_number"].add(1).eq(frame["lap_number"].shift(-1))
        & frame["base_eligible"]
        & frame["base_eligible"].shift(-1, fill_value=False)
    )

    break_run = ~previous_same
    run_id = break_run.cumsum()
    run_length = frame["base_eligible"].groupby(run_id).transform("sum")
    target_pairs_before_minimum = int(next_same.sum())
    selected = next_same & run_length.ge(minimum_consecutive_laps)

    frame["previous_lap_time_seconds"] = (
        frame["current_lap_time_seconds"].shift().where(previous_same)
    )
    frame["previous_lap_delta_seconds"] = (
        frame["current_lap_time_seconds"] - frame["previous_lap_time_seconds"]
    )
    frame["next_lap_time_seconds"] = frame["current_lap_time_seconds"].shift(-1)
    frame["next_lap_delta_seconds"] = (
        frame["next_lap_time_seconds"] - frame["current_lap_time_seconds"]
    )
    frame["sample_id"] = (
        frame["event_id"].astype(str)
        + ":"
        + frame["driver_number"].astype(str)
        + ":"
        + frame["stint"].astype("Int64").astype(str)
        + ":"
        + frame["lap_number"].astype("Int64").astype(str)
    )

    result = frame.loc[selected, ANALYSIS_COLUMNS].copy()
    for column in (
        "season",
        "round_number",
        "stint",
        "lap_number",
        "stint_lap_index",
        "position",
    ):
        result[column] = result[column].astype(int)
    for column in ("fresh_tyre", "rainfall"):
        result[column] = result[column].map(bool).astype(object)
    return result.reset_index(drop=True), target_pairs_before_minimum
