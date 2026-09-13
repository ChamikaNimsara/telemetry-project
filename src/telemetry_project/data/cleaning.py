"""Normalize FastF1 laps and apply explicit, countable eligibility rules."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from telemetry_project.data.dataset_config import EligibilityConfig

LAP_COLUMNS = (
    "DriverNumber",
    "Team",
    "LapTime",
    "LapNumber",
    "Stint",
    "PitOutTime",
    "PitInTime",
    "Sector1Time",
    "Sector2Time",
    "Sector3Time",
    "Compound",
    "TyreLife",
    "FreshTyre",
    "TrackStatus",
    "Position",
    "Deleted",
    "IsAccurate",
    "Time",
)
WEATHER_COLUMNS = (
    "AirTemp",
    "Humidity",
    "Pressure",
    "Rainfall",
    "TrackTemp",
    "WindDirection",
    "WindSpeed",
)
EXCLUSION_ORDER = (
    "duplicate_lap_key",
    "missing_identity",
    "missing_lap_time",
    "implausible_lap_time",
    "missing_tyre_data",
    "non_slick_compound",
    "inaccurate_lap",
    "deleted_lap",
    "pit_in_lap",
    "pit_out_lap",
    "missing_feature",
    "missing_weather",
    "wet_weather",
    "disrupted_track_status",
)


class CleaningError(ValueError):
    """Raised when source tables cannot satisfy the cleaning contract."""


@dataclass(frozen=True, slots=True)
class EventAudit:
    """Aggregate quality evidence for one event."""

    event_id: str
    event_name: str
    split: str
    raw_laps: int
    duplicate_lap_keys: int
    non_monotonic_time_rows: int
    missing_required_rows: int
    weather_missing_rows: int
    wet_weather_rows: int
    disrupted_track_status_rows: int
    pit_laps: int
    inaccurate_laps: int
    deleted_laps: int
    base_eligible_laps: int
    target_pairs_before_minimum: int
    final_samples: int
    excluded_short_segment_pairs: int
    exclusion_counts: dict[str, int]

    def flat_dict(self) -> dict[str, str | int]:
        """Return stable scalar columns for the generated audit CSV."""
        result: dict[str, str | int] = {
            key: value
            for key, value in asdict(self).items()
            if key != "exclusion_counts"
        }
        result.update(
            {
                f"excluded_{reason}": self.exclusion_counts.get(reason, 0)
                for reason in EXCLUSION_ORDER
            }
        )
        return result


def _seconds(series: pd.Series) -> pd.Series:
    return pd.to_timedelta(series, errors="coerce").dt.total_seconds()


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], table: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise CleaningError(
            f"{table} is missing required columns: {', '.join(missing)}"
        )


def clean_event_laps(
    laps: pd.DataFrame,
    weather: pd.DataFrame,
    *,
    event_id: str,
    event_name: str,
    split: str,
    source_id: str,
    season: int,
    round_number: int,
    session_code: str,
    policy: EligibilityConfig,
) -> pd.DataFrame:
    """Return a normalized copy with one primary exclusion reason per raw lap."""
    _require_columns(laps, LAP_COLUMNS, "lap table")
    _require_columns(weather, WEATHER_COLUMNS, "weather table")
    if len(laps) != len(weather):
        raise CleaningError(
            f"Lap/weather alignment differs: {len(laps)} laps and {len(weather)} rows."
        )

    frame = laps.loc[:, LAP_COLUMNS].reset_index(drop=True).copy()
    weather_values = weather.loc[:, WEATHER_COLUMNS].reset_index(drop=True)
    for column in WEATHER_COLUMNS:
        frame[column] = weather_values[column]

    frame["event_id"] = event_id
    frame["event_name"] = event_name
    frame["split"] = split
    frame["source_id"] = source_id
    frame["season"] = season
    frame["round_number"] = round_number
    frame["session_code"] = session_code
    frame["driver_number"] = frame["DriverNumber"].astype("string").str.strip()
    frame["team"] = frame["Team"].astype("string").str.strip()
    frame["lap_number"] = pd.to_numeric(frame["LapNumber"], errors="coerce")
    frame["stint"] = pd.to_numeric(frame["Stint"], errors="coerce")
    frame["compound"] = frame["Compound"].astype("string").str.upper().str.strip()
    frame["tyre_life_laps"] = pd.to_numeric(frame["TyreLife"], errors="coerce")
    frame["position"] = pd.to_numeric(frame["Position"], errors="coerce")
    frame["track_status"] = frame["TrackStatus"].astype("string").str.strip()
    frame["fresh_tyre"] = frame["FreshTyre"].map(
        lambda value: bool(value) if pd.notna(value) else pd.NA
    )
    frame["rainfall"] = frame["Rainfall"].map(
        lambda value: bool(value) if pd.notna(value) else pd.NA
    )
    frame["current_lap_time_seconds"] = _seconds(frame["LapTime"])
    frame["sector1_seconds"] = _seconds(frame["Sector1Time"])
    frame["sector2_seconds"] = _seconds(frame["Sector2Time"])
    frame["sector3_seconds"] = _seconds(frame["Sector3Time"])
    frame["air_temp_c"] = pd.to_numeric(frame["AirTemp"], errors="coerce")
    frame["track_temp_c"] = pd.to_numeric(frame["TrackTemp"], errors="coerce")
    frame["humidity_percent"] = pd.to_numeric(frame["Humidity"], errors="coerce")
    frame["pressure_mbar"] = pd.to_numeric(frame["Pressure"], errors="coerce")
    frame["wind_speed_mps"] = pd.to_numeric(frame["WindSpeed"], errors="coerce")
    frame["wind_direction_deg"] = pd.to_numeric(frame["WindDirection"], errors="coerce")

    frame = frame.sort_values(
        ["driver_number", "lap_number"], kind="mergesort", na_position="last"
    ).reset_index(drop=True)
    frame["stint_lap_index"] = (
        frame.groupby(["driver_number", "stint"], dropna=False).cumcount() + 1
    )
    frame["exclusion_reason"] = pd.Series(pd.NA, index=frame.index, dtype="string")

    duplicate = frame.duplicated(["driver_number", "stint", "lap_number"], keep=False)
    identity_missing = (
        frame[["driver_number", "stint", "lap_number", "team", "position"]]
        .isna()
        .any(axis=1)
        | frame["driver_number"].eq("")
        | frame["team"].eq("")
    )
    tyre_missing = frame[["compound", "tyre_life_laps", "fresh_tyre"]].isna().any(
        axis=1
    ) | frame["compound"].eq("")
    feature_missing = (
        frame[
            [
                "air_temp_c",
                "track_temp_c",
                "humidity_percent",
                "pressure_mbar",
                "wind_speed_mps",
                "wind_direction_deg",
            ]
        ]
        .isna()
        .any(axis=1)
    )
    weather_missing = frame[list(WEATHER_COLUMNS)].isna().any(axis=1)
    wet_weather = frame["rainfall"].eq(True)
    disrupted_track_status = ~frame["track_status"].isin(policy.allowed_track_status)
    frame["_missing_required"] = (
        identity_missing
        | frame["current_lap_time_seconds"].isna()
        | tyre_missing
        | feature_missing
        | weather_missing
    )
    frame["_weather_missing"] = weather_missing
    frame["_wet_weather"] = wet_weather
    frame["_disrupted_track_status"] = disrupted_track_status

    rules: tuple[tuple[str, pd.Series], ...] = (
        ("duplicate_lap_key", duplicate),
        ("missing_identity", identity_missing),
        ("missing_lap_time", frame["current_lap_time_seconds"].isna()),
        (
            "implausible_lap_time",
            ~frame["current_lap_time_seconds"].between(30, 300, inclusive="both"),
        ),
        ("missing_tyre_data", tyre_missing),
        ("non_slick_compound", ~frame["compound"].isin(policy.slick_compounds)),
        (
            "inaccurate_lap",
            frame["IsAccurate"].ne(True)
            if policy.require_accurate_lap
            else pd.Series(False, index=frame.index),
        ),
        (
            "deleted_lap",
            frame["Deleted"].eq(True)
            if policy.exclude_deleted_laps
            else pd.Series(False, index=frame.index),
        ),
        (
            "pit_in_lap",
            frame["PitInTime"].notna()
            if policy.exclude_pit_in_laps
            else pd.Series(False, index=frame.index),
        ),
        (
            "pit_out_lap",
            frame["PitOutTime"].notna()
            if policy.exclude_pit_out_laps
            else pd.Series(False, index=frame.index),
        ),
        (
            "missing_weather",
            weather_missing
            if policy.require_weather_coverage
            else pd.Series(False, index=frame.index),
        ),
        ("missing_feature", feature_missing),
        (
            "wet_weather",
            wet_weather
            if policy.require_dry_weather
            else pd.Series(False, index=frame.index),
        ),
        (
            "disrupted_track_status",
            disrupted_track_status,
        ),
    )
    for reason, mask in rules:
        available = frame["exclusion_reason"].isna()
        frame.loc[available & mask.fillna(True), "exclusion_reason"] = reason
    frame["base_eligible"] = frame["exclusion_reason"].isna()
    return frame


def summarize_event(
    frame: pd.DataFrame,
    *,
    target_pairs_before_minimum: int,
    final_samples: int,
) -> EventAudit:
    """Summarize source quality and mutually exclusive exclusions."""
    same_driver = frame["driver_number"].eq(frame["driver_number"].shift())
    time_values = pd.to_timedelta(frame["Time"], errors="coerce")
    non_monotonic = same_driver & time_values.le(time_values.shift())
    counts = {
        reason: int(frame["exclusion_reason"].eq(reason).sum())
        for reason in EXCLUSION_ORDER
    }
    return EventAudit(
        event_id=str(frame["event_id"].iloc[0]),
        event_name=str(frame["event_name"].iloc[0]),
        split=str(frame["split"].iloc[0]),
        raw_laps=len(frame),
        duplicate_lap_keys=int(
            frame.duplicated(["driver_number", "stint", "lap_number"], keep=False).sum()
        ),
        non_monotonic_time_rows=int(non_monotonic.sum()),
        missing_required_rows=int(frame["_missing_required"].sum()),
        weather_missing_rows=int(frame["_weather_missing"].sum()),
        wet_weather_rows=int(frame["_wet_weather"].sum()),
        disrupted_track_status_rows=int(frame["_disrupted_track_status"].sum()),
        pit_laps=int((frame["PitInTime"].notna() | frame["PitOutTime"].notna()).sum()),
        inaccurate_laps=int(frame["IsAccurate"].ne(True).sum()),
        deleted_laps=int(frame["Deleted"].eq(True).sum()),
        base_eligible_laps=int(frame["base_eligible"].sum()),
        target_pairs_before_minimum=target_pairs_before_minimum,
        final_samples=final_samples,
        excluded_short_segment_pairs=target_pairs_before_minimum - final_samples,
        exclusion_counts=counts,
    )
