"""Distance-aligned driver telemetry comparison for race-performance analysis."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fastf1
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from telemetry_project.analysis.performance_config import Corner, PerformanceConfig

REQUIRED_TELEMETRY_COLUMNS = frozenset(
    {"Distance", "Time", "Speed", "Throttle", "Brake", "nGear", "RPM", "DRS"}
)
FIGURE_NAMES = (
    "08-qualifying-lap-delta.png",
    "09-qualifying-telemetry-comparison.png",
    "10-corner-time-contribution.png",
)


class PerformanceAnalysisError(ValueError):
    """Raised when telemetry cannot support the configured comparison."""


@dataclass(frozen=True, slots=True)
class LapMetadata:
    """Identity and timing metadata for one selected lap."""

    driver: str
    lap_number: int
    lap_time_seconds: float
    compound: str


@dataclass(frozen=True, slots=True)
class PerformanceSummary:
    """Compact result returned by the performance workflow."""

    event: str
    session: str
    reference_driver: str
    comparison_driver: str
    reference_lap_seconds: float
    comparison_lap_seconds: float
    reference_advantage_seconds: float
    corners: int
    mini_sectors: int
    figures: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _elapsed_seconds(values: pd.Series) -> pd.Series:
    if isinstance(values.dtype, pd.DatetimeTZDtype) or pd.api.types.is_datetime64_dtype(
        values.dtype
    ):
        raise PerformanceAnalysisError(
            "Telemetry 'Time' must be elapsed, not absolute."
        )
    if pd.api.types.is_timedelta64_dtype(values.dtype):
        return values.dt.total_seconds()
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any():
        raise PerformanceAnalysisError("Telemetry 'Time' contains non-numeric values.")
    return numeric.astype(float)


def resample_telemetry(telemetry: pd.DataFrame, distance_step_m: float) -> pd.DataFrame:
    """Interpolate one lap onto a regular distance grid.

    Continuous channels are linearly interpolated. Gear, brake, and DRS are
    represented by their nearest/rounded state on the same grid.
    """
    missing = REQUIRED_TELEMETRY_COLUMNS - set(telemetry.columns)
    if missing:
        raise PerformanceAnalysisError(
            f"Telemetry is missing required columns: {sorted(missing)}"
        )
    if distance_step_m <= 0:
        raise PerformanceAnalysisError("Distance step must be positive.")

    frame = telemetry.loc[:, sorted(REQUIRED_TELEMETRY_COLUMNS)].copy()
    frame["Distance"] = pd.to_numeric(frame["Distance"], errors="coerce")
    frame["elapsed_seconds"] = _elapsed_seconds(frame["Time"])
    for column in ("Speed", "Throttle", "Brake", "nGear", "RPM", "DRS"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = (
        frame.dropna(subset=["Distance", "elapsed_seconds", "Speed"])
        .sort_values("Distance")
        .drop_duplicates("Distance", keep="last")
    )
    if len(frame) < 2 or float(frame["Distance"].max()) <= 0:
        raise PerformanceAnalysisError("Telemetry must contain two ordered distances.")

    frame["elapsed_seconds"] -= float(frame["elapsed_seconds"].iloc[0])
    maximum = float(frame["Distance"].max())
    grid = np.arange(0.0, maximum + distance_step_m / 2, distance_step_m)
    output = pd.DataFrame({"distance_m": grid})
    for column in ("elapsed_seconds", "Speed", "Throttle", "RPM"):
        valid = frame[["Distance", column]].dropna()
        if len(valid) < 2:
            raise PerformanceAnalysisError(
                f"Telemetry channel '{column}' has insufficient data."
            )
        output[column.lower()] = np.interp(
            grid,
            valid["Distance"].to_numpy(dtype=float),
            valid[column].to_numpy(dtype=float),
        )
    for column in ("Brake", "nGear", "DRS"):
        valid = frame[["Distance", column]].dropna()
        if valid.empty:
            raise PerformanceAnalysisError(f"Telemetry channel '{column}' is empty.")
        interpolated = np.interp(
            grid,
            valid["Distance"].to_numpy(dtype=float),
            valid[column].to_numpy(dtype=float),
        )
        output[column.lower()] = np.rint(interpolated)
    return output


def build_lap_comparison(
    reference: pd.DataFrame, comparison: pd.DataFrame
) -> pd.DataFrame:
    """Align resampled laps and calculate comparison-minus-reference delta."""
    aligned = reference.merge(
        comparison,
        on="distance_m",
        how="inner",
        suffixes=("_reference", "_comparison"),
        validate="one_to_one",
    )
    if aligned.empty:
        raise PerformanceAnalysisError(
            "The selected laps have no shared distance grid."
        )
    aligned["delta_seconds"] = (
        aligned["elapsed_seconds_comparison"] - aligned["elapsed_seconds_reference"]
    )
    return aligned


def _value_at(frame: pd.DataFrame, column: str, distance_m: float) -> float:
    return float(
        np.interp(
            distance_m,
            frame["distance_m"].to_numpy(dtype=float),
            frame[column].to_numpy(dtype=float),
        )
    )


def _first_sustained(
    distances: pd.Series,
    state: pd.Series,
    sustained_samples: int,
) -> float:
    sustained = state.astype(int).rolling(sustained_samples).sum()
    matches = sustained[sustained >= sustained_samples]
    if matches.empty:
        return float("nan")
    start_index = max(0, int(matches.index[0]) - sustained_samples + 1)
    return float(distances.loc[start_index])


def _brake_point(
    frame: pd.DataFrame,
    column: str,
    apex_m: float,
    lookback_m: float,
    sustained_samples: int,
) -> float:
    window = frame.loc[
        frame["distance_m"].between(max(0.0, apex_m - lookback_m), apex_m),
        ["distance_m", column],
    ].reset_index(drop=True)
    if window.empty:
        return float("nan")
    return _first_sustained(
        window["distance_m"], window[column] >= 0.5, sustained_samples
    )


def _throttle_pickup(
    frame: pd.DataFrame,
    column: str,
    apex_m: float,
    lookahead_m: float,
    threshold: float,
    sustained_samples: int,
) -> float:
    context = frame.loc[
        frame["distance_m"].between(max(0.0, apex_m - 50.0), apex_m + lookahead_m),
        ["distance_m", column],
    ]
    if context.empty or bool((context[column] >= threshold).all()):
        return float("nan")
    window = context.loc[context["distance_m"] >= apex_m].reset_index(drop=True)
    return _first_sustained(
        window["distance_m"], window[column] >= threshold, sustained_samples
    )


def _corner_bounds(
    corners: tuple[Corner, ...],
    index: int,
    track_length_m: float,
    before_m: float,
    after_m: float,
) -> tuple[float, float]:
    apex = corners[index].distance_m
    previous_midpoint = (
        0.0 if index == 0 else (corners[index - 1].distance_m + apex) / 2
    )
    next_midpoint = (
        track_length_m
        if index == len(corners) - 1
        else (apex + corners[index + 1].distance_m) / 2
    )
    return max(previous_midpoint, apex - before_m), min(next_midpoint, apex + after_m)


def build_corner_metrics(
    comparison: pd.DataFrame, config: PerformanceConfig
) -> pd.DataFrame:
    """Summarize timing and control differences around configured corners."""
    track_length = float(comparison["distance_m"].max())
    if config.corners[-1].distance_m >= track_length:
        raise PerformanceAnalysisError(
            "Configured corner distances must be shorter than the aligned lap."
        )
    records: list[dict[str, object]] = []
    for index, corner in enumerate(config.corners):
        start, end = _corner_bounds(
            config.corners,
            index,
            track_length,
            config.corner_window_before_m,
            config.corner_window_after_m,
        )
        window = comparison.loc[comparison["distance_m"].between(start, end)]
        reference_brake = _brake_point(
            comparison,
            "brake_reference",
            corner.distance_m,
            config.brake_lookback_m,
            config.sustained_samples,
        )
        comparison_brake = _brake_point(
            comparison,
            "brake_comparison",
            corner.distance_m,
            config.brake_lookback_m,
            config.sustained_samples,
        )
        reference_pickup = _throttle_pickup(
            comparison,
            "throttle_reference",
            corner.distance_m,
            config.throttle_lookahead_m,
            config.throttle_pickup_percent,
            config.sustained_samples,
        )
        comparison_pickup = _throttle_pickup(
            comparison,
            "throttle_comparison",
            corner.distance_m,
            config.throttle_lookahead_m,
            config.throttle_pickup_percent,
            config.sustained_samples,
        )
        reference_minimum = float(window["speed_reference"].min())
        comparison_minimum = float(window["speed_comparison"].min())
        mean_minimum = (reference_minimum + comparison_minimum) / 2
        speed_class = "low" if mean_minimum < 130 else "medium"
        if mean_minimum >= 200:
            speed_class = "high"
        records.append(
            {
                "corner": corner.label,
                "speed_class": speed_class,
                "apex_distance_m": round(corner.distance_m, 1),
                "window_start_m": round(start, 1),
                "window_end_m": round(end, 1),
                "reference_min_speed_kph": round(reference_minimum, 1),
                "comparison_min_speed_kph": round(comparison_minimum, 1),
                "reference_min_speed_delta_kph": round(
                    reference_minimum - comparison_minimum, 1
                ),
                "reference_brake_point_m": round(reference_brake, 1),
                "comparison_brake_point_m": round(comparison_brake, 1),
                "reference_later_braking_m": round(
                    reference_brake - comparison_brake, 1
                ),
                "reference_throttle_pickup_m": round(reference_pickup, 1),
                "comparison_throttle_pickup_m": round(comparison_pickup, 1),
                "reference_earlier_throttle_m": round(
                    comparison_pickup - reference_pickup, 1
                ),
                "reference_gain_seconds": round(
                    _value_at(comparison, "delta_seconds", end)
                    - _value_at(comparison, "delta_seconds", start),
                    4,
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def build_mini_sector_metrics(
    comparison: pd.DataFrame, mini_sector_length_m: float
) -> pd.DataFrame:
    """Build fixed-distance timing segments and a descriptive phase label."""
    frame = comparison.copy()
    frame["mini_sector"] = (frame["distance_m"] // mini_sector_length_m).astype(int)
    records: list[dict[str, object]] = []
    for sector, group in frame.groupby("mini_sector", sort=True):
        if len(group) < 2:
            continue
        brake_fraction = float(
            pd.concat(
                [group["brake_reference"], group["brake_comparison"]],
                ignore_index=True,
            ).mean()
        )
        throttle_mean = float(
            pd.concat(
                [group["throttle_reference"], group["throttle_comparison"]],
                ignore_index=True,
            ).mean()
        )
        speed_minimum = float(
            min(group["speed_reference"].min(), group["speed_comparison"].min())
        )
        drs_mean = float(
            pd.concat(
                [group["drs_reference"], group["drs_comparison"]],
                ignore_index=True,
            ).mean()
        )
        phase = "mixed"
        if brake_fraction >= 0.15:
            phase = "braking"
        elif throttle_mean >= 97 and speed_minimum >= 220:
            phase = "straight-line/DRS" if drs_mean >= 10 else "straight-line"
        elif speed_minimum < 200:
            phase = "corner/traction"
        records.append(
            {
                "mini_sector": int(sector) + 1,
                "start_distance_m": round(float(group["distance_m"].iloc[0]), 1),
                "end_distance_m": round(float(group["distance_m"].iloc[-1]), 1),
                "phase": phase,
                "reference_gain_seconds": round(
                    float(group["delta_seconds"].iloc[-1])
                    - float(group["delta_seconds"].iloc[0]),
                    4,
                ),
                "reference_mean_speed_delta_kph": round(
                    float(
                        (group["speed_reference"] - group["speed_comparison"]).mean()
                    ),
                    1,
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def _style() -> None:
    plt.rcParams.update(
        {
            "axes.grid": True,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "figure.dpi": 130,
            "font.size": 9,
            "grid.alpha": 0.25,
        }
    )


def _save_figure(figure: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, bbox_inches="tight", dpi=180)
    plt.close(figure)


def _annotation_evidence(row: pd.Series) -> str:
    evidence: list[str] = []
    brake = row["reference_later_braking_m"]
    if pd.notna(brake) and abs(float(brake)) >= 10:
        evidence.append(f"{float(brake):+g} m brake point")
    speed = float(row["reference_min_speed_delta_kph"])
    if abs(speed) >= 2:
        evidence.append(f"{speed:+g} km/h minimum")
    throttle = row["reference_earlier_throttle_m"]
    if pd.notna(throttle) and abs(float(throttle)) >= 10:
        evidence.append(f"{float(throttle):+g} m earlier throttle")
    return "; ".join(evidence[:2]) or "net speed-profile difference"


def _plot_delta(
    frame: pd.DataFrame,
    corners: pd.DataFrame,
    config: PerformanceConfig,
    path: Path,
) -> None:
    _style()
    figure, axis = plt.subplots(figsize=(12, 5.5))
    axis.plot(frame["distance_m"], frame["delta_seconds"], color="#0072B2", lw=2)
    axis.axhline(0, color="#333333", lw=0.8)
    axis.fill_between(
        frame["distance_m"],
        0,
        frame["delta_seconds"],
        where=frame["delta_seconds"] >= 0,
        color="#56B4E9",
        alpha=0.22,
        label=f"{config.drivers.reference} ahead",
    )
    axis.fill_between(
        frame["distance_m"],
        0,
        frame["delta_seconds"],
        where=frame["delta_seconds"] < 0,
        color="#E69F00",
        alpha=0.22,
        label=f"{config.drivers.comparison} ahead",
    )
    previous_apex = float("-inf")
    for row in corners.itertuples(index=False):
        axis.axvline(row.apex_distance_m, color="#777777", alpha=0.12, lw=0.7)
        label_height = 0.91 if row.apex_distance_m - previous_apex < 125 else 0.98
        axis.text(
            row.apex_distance_m,
            label_height,
            str(row.corner),
            ha="center",
            va="top",
            fontsize=7,
            transform=axis.get_xaxis_transform(),
        )
        previous_apex = row.apex_distance_m
    maximum_delta = float(frame["delta_seconds"].max())
    maximum_distance = float(frame["distance_m"].max())
    for row, height in (
        (corners.loc[corners["reference_gain_seconds"].idxmax()], 0.82),
        (corners.loc[corners["reference_gain_seconds"].idxmin()], 0.58),
    ):
        apex = float(row["apex_distance_m"])
        axis.annotate(
            (
                f"{row['corner']}: {float(row['reference_gain_seconds']):+.3f} s\n"
                f"{_annotation_evidence(row)}"
            ),
            xy=(apex, _value_at(frame, "delta_seconds", apex)),
            xytext=(min(apex + 400, maximum_distance * 0.78), maximum_delta * height),
            textcoords="data",
            arrowprops={"arrowstyle": "->", "color": "#444444", "lw": 0.8},
            fontsize=8,
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.85},
        )
    axis.set(
        title=(
            f"2024 Abu Dhabi qualifying lap delta: "
            f"{config.drivers.reference} vs {config.drivers.comparison}"
        ),
        xlabel="Lap distance (m)",
        ylabel=(f"Cumulative delta (s)\npositive = {config.drivers.reference} ahead"),
    )
    axis.legend(loc="best")
    figure.text(
        0.01,
        0.01,
        (
            "FastF1 telemetry; distance-aligned interpolation. "
            "Associations are descriptive, not causal."
        ),
        fontsize=8,
    )
    _save_figure(figure, path)


def _plot_telemetry(frame: pd.DataFrame, config: PerformanceConfig, path: Path) -> None:
    _style()
    figure, axes = plt.subplots(5, 1, figsize=(12, 11), sharex=True)
    colors = {"reference": "#0072B2", "comparison": "#E69F00"}
    labels = {
        "reference": config.drivers.reference,
        "comparison": config.drivers.comparison,
    }
    for role in ("reference", "comparison"):
        axes[0].plot(
            frame["distance_m"],
            frame[f"speed_{role}"],
            color=colors[role],
            label=labels[role],
            lw=1.3,
        )
        axes[1].plot(
            frame["distance_m"],
            frame[f"throttle_{role}"],
            color=colors[role],
            lw=1.1,
        )
        axes[1].fill_between(
            frame["distance_m"],
            0,
            frame[f"brake_{role}"] * 100,
            color=colors[role],
            alpha=0.14,
            step="mid",
        )
        axes[1].step(
            frame["distance_m"],
            frame[f"brake_{role}"] * 100,
            color=colors[role],
            alpha=0.8,
            linestyle=":",
            where="mid",
            lw=1.0,
        )
        axes[2].step(
            frame["distance_m"],
            frame[f"ngear_{role}"],
            color=colors[role],
            where="mid",
            lw=1.1,
        )
        axes[3].plot(
            frame["distance_m"],
            frame[f"rpm_{role}"],
            color=colors[role],
            lw=1.1,
        )
        axes[4].step(
            frame["distance_m"],
            frame[f"drs_{role}"],
            color=colors[role],
            where="mid",
            lw=1.1,
        )
    axes[0].set_ylabel("Speed\n(km/h)")
    axes[1].set_ylabel("Throttle /\nbrake (%)")
    axes[2].set_ylabel("Gear")
    axes[3].set_ylabel("RPM")
    axes[4].set_ylabel("DRS code")
    axes[4].set_xlabel("Lap distance (m)")
    axes[0].legend(loc="best")
    axes[0].set_title("Fastest accurate lap telemetry comparison")
    figure.suptitle(
        "Solid = throttle; dotted/fill = brake state; DRS is the FastF1 status code",
        y=0.985,
        fontsize=9,
    )
    figure.text(
        0.01,
        0.005,
        (
            "FastF1 public telemetry is sampled and interpolated; small point "
            "differences are not sensor-grade measurements."
        ),
        fontsize=8,
    )
    figure.tight_layout(rect=(0, 0.02, 1, 0.97))
    _save_figure(figure, path)


def _plot_corner_contributions(
    corners: pd.DataFrame, config: PerformanceConfig, path: Path
) -> None:
    _style()
    figure, axis = plt.subplots(figsize=(10, 6))
    values = corners["reference_gain_seconds"]
    colors = np.where(values >= 0, "#0072B2", "#E69F00")
    axis.barh(corners["corner"], values, color=colors)
    axis.axvline(0, color="#333333", lw=0.8)
    axis.invert_yaxis()
    axis.set(
        title="Corner-window contribution to lap delta",
        xlabel=(
            f"Time contribution (s): positive = {config.drivers.reference} gain, "
            f"negative = {config.drivers.comparison} gain"
        ),
        ylabel="Corner",
    )
    figure.text(
        0.01,
        0.01,
        (
            "Windows are bounded around configured apex distances and exclude "
            "most intervening straights."
        ),
        fontsize=8,
    )
    _save_figure(figure, path)


def _driver_insight(row: pd.Series, reference: str) -> str:
    evidence: list[str] = []
    if pd.notna(row["reference_later_braking_m"]):
        difference = float(row["reference_later_braking_m"])
        if abs(difference) >= 10:
            evidence.append(
                f"{abs(difference):.0f} m "
                f"{'later' if difference > 0 else 'earlier'} brake application"
            )
    speed_difference = float(row["reference_min_speed_delta_kph"])
    if abs(speed_difference) >= 2:
        evidence.append(
            f"{abs(speed_difference):.1f} km/h "
            f"{'higher' if speed_difference > 0 else 'lower'} minimum speed"
        )
    if pd.notna(row["reference_earlier_throttle_m"]):
        pickup = float(row["reference_earlier_throttle_m"])
        if abs(pickup) >= 10:
            evidence.append(
                f"{abs(pickup):.0f} m "
                f"{'earlier' if pickup > 0 else 'later'} full-throttle pickup"
            )
    if not evidence:
        return "a net speed-profile difference within the analysis window"
    return " and ".join(evidence[:2]) + f" for {reference}"


def _format_optional(value: float) -> str:
    return "" if pd.isna(value) else f"{float(value):.1f}"


def _render_report(
    config: PerformanceConfig,
    reference_lap: LapMetadata,
    comparison_lap: LapMetadata,
    corners: pd.DataFrame,
    mini_sectors: pd.DataFrame,
) -> str:
    lap_delta = comparison_lap.lap_time_seconds - reference_lap.lap_time_seconds
    gain = corners.loc[corners["reference_gain_seconds"].idxmax()]
    loss = corners.loc[corners["reference_gain_seconds"].idxmin()]
    linked_gain = float(gain["reference_gain_seconds"]) + float(
        loss["reference_gain_seconds"]
    )
    phase = (
        mini_sectors.groupby("phase", as_index=False)["reference_gain_seconds"]
        .sum()
        .sort_values("reference_gain_seconds", ascending=False)
    )
    corner_header = (
        f"| Corner | Class | {reference_lap.driver} min (km/h) | "
        f"{comparison_lap.driver} min (km/h) | Later braking (m) | "
        f"Earlier throttle (m) | {reference_lap.driver} gain (s) |"
    )
    corner_rows = "\n".join(
        "| "
        f"{row.corner} | {row.speed_class} | "
        f"{row.reference_min_speed_kph:.1f} | "
        f"{row.comparison_min_speed_kph:.1f} | "
        f"{_format_optional(row.reference_later_braking_m)} | "
        f"{_format_optional(row.reference_earlier_throttle_m)} | "
        f"{row.reference_gain_seconds:+.3f} |"
        for row in corners.itertuples(index=False)
    )
    return f"""# Race Performance Analysis

## Engineering question

Where did **{config.drivers.reference_name} ({reference_lap.driver})** gain or
lose time relative to **{config.drivers.comparison_name}
({comparison_lap.driver})** on their fastest accurate qualifying laps at the
{config.session.year} {config.session.event}, and which measured control or
speed differences are associated with those changes?

## Session and method

- Session: {config.session.year} {config.session.event} {config.session.session}
- Reference: {config.drivers.reference_name} ({reference_lap.driver}),
  lap {reference_lap.lap_number},
  {reference_lap.lap_time_seconds:.3f} s, {reference_lap.compound}
- Comparison: {config.drivers.comparison_name} ({comparison_lap.driver}),
  lap {comparison_lap.lap_number},
  {comparison_lap.lap_time_seconds:.3f} s, {comparison_lap.compound}
- Recorded advantage: **{lap_delta:.3f} s to {reference_lap.driver}**
- Alignment: linear interpolation on a {config.distance_step_m:g} m distance grid
- Segmentation: {len(corners)} configured corner windows and
  {len(mini_sectors)} fixed {config.mini_sector_length_m:g} m mini-sectors

The cumulative delta is comparison elapsed time minus reference elapsed time;
an increasing trace means {reference_lap.driver} is gaining. Brake and DRS are
discrete FastF1 status channels. Brake point and throttle pickup are rule-based
markers requiring {config.sustained_samples} consecutive samples. They are
diagnostic approximations, not exact physical pedal or GPS measurements.

![Lap delta](figures/{FIGURE_NAMES[0]})

## Main observations

- The largest positive corner-window contribution is **{gain["corner"]}** at
  **{float(gain["reference_gain_seconds"]):+.3f} s**. It is associated with
  {_driver_insight(gain, config.drivers.reference_name)}.
- The largest negative corner-window contribution is **{loss["corner"]}** at
  **{float(loss["reference_gain_seconds"]):+.3f} s** for
  {reference_lap.driver}. It is associated with
  {_driver_insight(loss, config.drivers.reference_name)}.
- The strongest aggregate mini-sector phase for {reference_lap.driver} is
  **{phase.iloc[0]["phase"]}** at
  **{float(phase.iloc[0]["reference_gain_seconds"]):+.3f} s**. Phase labels are
  descriptive rules based on sampled brake, throttle, speed, and DRS channels.
- T6 and T7 are only 60.6 m apart. Their windows share a midpoint and should be
  reviewed as one linked complex: together they contribute **{linked_gain:+.3f} s**
  to the reference delta, rather than the isolated T6 value alone.

![Telemetry comparison](figures/{FIGURE_NAMES[1]})

![Corner contributions](figures/{FIGURE_NAMES[2]})

## Corner comparison

The complete table is in
[`tables/qualifying-corner-comparison.csv`](tables/qualifying-corner-comparison.csv).
Positive minimum-speed, later-braking, earlier-throttle, and time-gain values
favor {reference_lap.driver}. Blank brake or throttle markers mean the rule did
not find a defensible transition in the configured search window.

{corner_header}
|---|---|---:|---:|---:|---:|---:|
{corner_rows}

## Engineering interpretation and next checks

The traces identify **where** the laps differ and which public telemetry signals
coincide with the difference. They do not establish why. Before attributing a
difference to setup, tyre preparation, energy deployment, or driver technique,
review onboard video, steering angle, track position, wind, tyre temperatures,
and repeated laps. The same-car comparison reduces but does not remove fuel,
run-plan, tow, track-evolution, and telemetry-alignment confounding.

## Limitations

- This is a two-lap case study, not evidence of persistent driver performance.
- FastF1 public telemetry is sampled, merged, and distance-integrated; derived
  transition distances have finite resolution and should be treated as estimates.
- Corner windows are configured from FastF1 circuit metadata and are not an
  official timing-sector definition.
- DRS status can be compared, but public data cannot isolate drag, ERS deployment,
  tow, wind, or setup effects.
- Conclusions are observational and non-causal.
"""


def _render_brief(
    config: PerformanceConfig,
    reference_lap: LapMetadata,
    comparison_lap: LapMetadata,
    corners: pd.DataFrame,
) -> str:
    lap_delta = comparison_lap.lap_time_seconds - reference_lap.lap_time_seconds
    gain = corners.loc[corners["reference_gain_seconds"].idxmax()]
    loss = corners.loc[corners["reference_gain_seconds"].idxmin()]
    linked_gain = float(gain["reference_gain_seconds"]) + float(
        loss["reference_gain_seconds"]
    )
    return f"""# Engineer's Brief — 2024 Abu Dhabi Qualifying

**Objective:** Compare the fastest accurate qualifying laps of
{config.drivers.reference_name} ({reference_lap.driver}) and
{config.drivers.comparison_name} ({comparison_lap.driver}) using
distance-aligned FastF1 telemetry.

**Headline:** {config.drivers.reference_name} recorded
**{reference_lap.lap_time_seconds:.3f} s**,
**{lap_delta:.3f} s** faster than {config.drivers.comparison_name}
({comparison_lap.lap_time_seconds:.3f} s).

**Primary gain:** {gain["corner"]} contributed
**{float(gain["reference_gain_seconds"]):+.3f} s** to the reference delta,
associated with {_driver_insight(gain, config.drivers.reference_name)}.

**Primary loss:** {loss["corner"]} contributed
**{float(loss["reference_gain_seconds"]):+.3f} s** to the reference delta,
associated with {_driver_insight(loss, config.drivers.reference_name)}.

**Linked-complex caution:** T6 and T7 are only 60.6 m apart and share a window
boundary. Review them together; their combined contribution is
**{linked_gain:+.3f} s** to Norris, not the isolated T6 value alone.

**Evidence:** [lap-delta trace](figures/{FIGURE_NAMES[0]}),
[telemetry traces](figures/{FIGURE_NAMES[1]}), and
[corner table](tables/qualifying-corner-comparison.csv).

**Recommended investigation:** Overlay onboard and steering traces at
{gain["corner"]} and {loss["corner"]}; check track position, tyre preparation,
wind/tow, and repeated-lap consistency before discussing braking approach,
balance, setup, or deployment changes.

**Decision caution:** This is an observational two-lap comparison. Public
telemetry shows associations and cannot identify setup state or causality.
"""


def _select_lap(session: Any, driver: str) -> tuple[Any, LapMetadata]:
    driver_laps = session.laps.pick_drivers(driver)
    if driver_laps.empty:
        raise PerformanceAnalysisError(f"No laps found for driver '{driver}'.")
    if "IsAccurate" in driver_laps.columns:
        driver_laps = driver_laps.loc[driver_laps["IsAccurate"] == True]  # noqa: E712
    if "Deleted" in driver_laps.columns:
        driver_laps = driver_laps.loc[driver_laps["Deleted"] != True]  # noqa: E712
    lap = driver_laps.pick_fastest()
    if lap is None or pd.isna(lap.get("LapTime")):
        raise PerformanceAnalysisError(
            f"No accurate timed lap found for driver '{driver}'."
        )
    lap_time = pd.to_timedelta(lap["LapTime"]).total_seconds()
    return lap, LapMetadata(
        driver=driver,
        lap_number=int(float(lap["LapNumber"])),
        lap_time_seconds=float(lap_time),
        compound=str(lap.get("Compound", "UNKNOWN")),
    )


def run_race_performance_analysis(
    config: PerformanceConfig,
    *,
    cache_dir: Path,
    offline: bool = False,
) -> PerformanceSummary:
    """Run the configured comparison and write aggregate portfolio evidence."""
    resolved_cache = cache_dir.resolve()
    resolved_cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(resolved_cache))
    fastf1.Cache.offline_mode(offline)
    try:
        session = fastf1.get_session(
            config.session.year, config.session.event, config.session.session
        )
        session.load(laps=True, telemetry=True, weather=False, messages=False)
        reference_lap, reference_metadata = _select_lap(
            session, config.drivers.reference
        )
        comparison_lap, comparison_metadata = _select_lap(
            session, config.drivers.comparison
        )
        reference = resample_telemetry(
            reference_lap.get_telemetry(), config.distance_step_m
        )
        comparison = resample_telemetry(
            comparison_lap.get_telemetry(), config.distance_step_m
        )
    except PerformanceAnalysisError:
        raise
    except Exception as error:
        raise PerformanceAnalysisError(
            f"Unable to load configured FastF1 telemetry: {error}"
        ) from error

    aligned = build_lap_comparison(reference, comparison)
    corners = build_corner_metrics(aligned, config)
    mini_sectors = build_mini_sector_metrics(aligned, config.mini_sector_length_m)
    config.outputs.corner_table.parent.mkdir(parents=True, exist_ok=True)
    corners.to_csv(config.outputs.corner_table, index=False, lineterminator="\n")
    config.outputs.mini_sector_table.parent.mkdir(parents=True, exist_ok=True)
    mini_sectors.to_csv(
        config.outputs.mini_sector_table, index=False, lineterminator="\n"
    )

    figure_paths = [config.outputs.figure_directory / name for name in FIGURE_NAMES]
    _plot_delta(aligned, corners, config, figure_paths[0])
    _plot_telemetry(aligned, config, figure_paths[1])
    _plot_corner_contributions(corners, config, figure_paths[2])

    report = _render_report(
        config, reference_metadata, comparison_metadata, corners, mini_sectors
    )
    config.outputs.report.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.report.write_text(report, encoding="utf-8", newline="\n")
    brief = _render_brief(config, reference_metadata, comparison_metadata, corners)
    config.outputs.engineering_brief.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.engineering_brief.write_text(brief, encoding="utf-8", newline="\n")

    output_paths = [
        *figure_paths,
        config.outputs.corner_table,
        config.outputs.mini_sector_table,
        config.outputs.report,
        config.outputs.engineering_brief,
    ]
    _write_json(
        config.outputs.manifest,
        {
            "manifest_schema_version": 1,
            "analysis_version": config.analysis_version,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "fastf1_version": fastf1.__version__,
            "config_path": config.source_path,
            "config_sha256": config.source_sha256,
            "session": asdict(config.session),
            "selected_laps": {
                "reference": asdict(reference_metadata),
                "comparison": asdict(comparison_metadata),
            },
            "distance_step_m": config.distance_step_m,
            "corner_source": "FastF1 circuit metadata copied into versioned config",
            "outputs": [
                {"path": path.as_posix(), "sha256": _sha256(path)}
                for path in output_paths
            ],
            "limitations": [
                "observational two-lap comparison",
                "sampled and interpolated public telemetry",
                "no setup, tyre-temperature, steering, wind, or tow controls",
            ],
        },
    )

    advantage = (
        comparison_metadata.lap_time_seconds - reference_metadata.lap_time_seconds
    )
    return PerformanceSummary(
        event=config.session.event,
        session=config.session.session,
        reference_driver=config.drivers.reference,
        comparison_driver=config.drivers.comparison,
        reference_lap_seconds=reference_metadata.lap_time_seconds,
        comparison_lap_seconds=comparison_metadata.lap_time_seconds,
        reference_advantage_seconds=round(advantage, 3),
        corners=len(corners),
        mini_sectors=len(mini_sectors),
        figures=len(figure_paths),
    )
