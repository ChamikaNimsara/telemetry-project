"""Reproducible exploratory analysis for the development event groups."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "telemetry-project-matplotlib")
)
import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from telemetry_project.analysis.config import AnalysisConfig
from telemetry_project.data.schema import read_analysis_csv

COMPOUND_COLORS = {
    "HARD": "#4477AA",
    "MEDIUM": "#EE6677",
    "SOFT": "#CCBB44",
}
NULLABLE_FEATURES = (
    "sector1_seconds",
    "sector2_seconds",
    "sector3_seconds",
    "previous_lap_time_seconds",
    "previous_lap_delta_seconds",
)
FIGURE_NAMES = (
    "01-current-vs-next-lap.png",
    "02-tyre-age-pace-profile.png",
    "03-event-compound-coverage.png",
    "04-nullable-feature-missingness.png",
)


class ExploratoryAnalysisError(ValueError):
    """Raised when traceability or analysis inputs are invalid."""


@dataclass(frozen=True, slots=True)
class ExploratorySummary:
    """Compact result returned by the analysis command."""

    development_rows: int
    events: int
    figures: int
    current_next_correlation: float
    persistence_mae_seconds: float
    dataset_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExploratoryAnalysisError(
            f"Unable to read manifest '{path}': {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ExploratoryAnalysisError(f"Manifest '{path}' must contain an object.")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_development_data(
    config: AnalysisConfig,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = _load_json(config.source_dataset_manifest)
    if manifest.get("manifest_schema_version") != 1:
        raise ExploratoryAnalysisError("Dataset manifest schema version must be 1.")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise ExploratoryAnalysisError("Dataset manifest outputs must be a list.")

    by_split = {
        str(output.get("split")): output
        for output in outputs
        if isinstance(output, dict)
    }
    frames: list[pd.DataFrame] = []
    for split in config.include_splits:
        output = by_split.get(split)
        if output is None:
            raise ExploratoryAnalysisError(f"Dataset manifest has no '{split}' output.")
        path = Path(str(output["path"]))
        if not path.is_file():
            raise ExploratoryAnalysisError(
                f"Processed '{split}' data is missing; run build-dataset first."
            )
        if _sha256(path) != output.get("sha256"):
            raise ExploratoryAnalysisError(
                f"Processed '{split}' data does not match its manifest hash."
            )
        frame = read_analysis_csv(str(path))
        if not frame["split"].eq(split).all():
            raise ExploratoryAnalysisError(
                f"Processed '{split}' data has wrong labels."
            )
        frames.append(frame)

    data = pd.concat(frames, ignore_index=True)
    if data["split"].eq("test").any():
        raise ExploratoryAnalysisError("Frozen test rows must not enter exploration.")
    return data, manifest


def build_event_summary(data: pd.DataFrame) -> pd.DataFrame:
    """Calculate auditable per-event descriptive statistics."""
    working = data.assign(
        absolute_persistence_error=(
            data["next_lap_time_seconds"] - data["current_lap_time_seconds"]
        ).abs(),
        previous_missing=data["previous_lap_time_seconds"].isna().astype(float) * 100,
    )
    grouped = working.groupby(["split", "event_id", "event_name"], sort=True)
    summary = grouped.agg(
        samples=("sample_id", "size"),
        median_next_lap_seconds=("next_lap_time_seconds", "median"),
        median_next_lap_delta_seconds=("next_lap_delta_seconds", "median"),
        persistence_mae_seconds=("absolute_persistence_error", "mean"),
        median_track_temp_c=("track_temp_c", "median"),
        maximum_tyre_life_laps=("tyre_life_laps", "max"),
        previous_lap_missing_percent=("previous_missing", "mean"),
    ).reset_index()
    numeric = summary.select_dtypes(include="number").columns
    summary[numeric] = summary[numeric].round(4)
    return summary


def build_tyre_age_profile(data: pd.DataFrame, edges: tuple[int, ...]) -> pd.DataFrame:
    """Create an analysis-only within-stint centered pace profile."""
    working = data.copy()
    stint_groups = ["event_id", "driver_number", "stint"]
    working["stint_centered_lap_seconds"] = working[
        "current_lap_time_seconds"
    ] - working.groupby(stint_groups)["current_lap_time_seconds"].transform("median")
    labels = [f"{left + 1}-{right}" for left, right in pairwise(edges)]
    working["tyre_age_band"] = pd.cut(
        working["tyre_life_laps"], bins=edges, labels=labels, include_lowest=True
    )
    profile = (
        working.dropna(subset="tyre_age_band")
        .groupby(["compound", "tyre_age_band"], observed=True)[
            "stint_centered_lap_seconds"
        ]
        .agg(
            samples="size",
            median="median",
            q25=lambda values: values.quantile(0.25),
            q75=lambda values: values.quantile(0.75),
        )
        .reset_index()
    )
    profile["tyre_age_band"] = profile["tyre_age_band"].astype(str)
    return profile


def _style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.25,
            "font.size": 10,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "legend.frameon": False,
        }
    )


def _save_figure(fig: Any, path: Path) -> None:
    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        metadata={"Software": "telemetry-project"},
    )
    plt.close(fig)


def _plot_current_vs_next(
    data: pd.DataFrame, config: AnalysisConfig, path: Path
) -> None:
    samples = []
    for _, group in data.groupby("event_id", sort=True):
        count = min(config.scatter_rows_per_event, len(group))
        samples.append(group.sample(n=count, random_state=config.random_seed))
    sampled = pd.concat(samples, ignore_index=True)
    fig, ax = plt.subplots(figsize=(8.5, 6.2))
    for compound in ("HARD", "MEDIUM", "SOFT"):
        rows = sampled.loc[sampled["compound"].eq(compound)]
        ax.scatter(
            rows["current_lap_time_seconds"],
            rows["next_lap_time_seconds"],
            s=16,
            alpha=0.42,
            color=COMPOUND_COLORS[compound],
            label=f"{compound.title()} (n={len(rows):,})",
            edgecolors="none",
        )
    lower = min(
        sampled["current_lap_time_seconds"].min(),
        sampled["next_lap_time_seconds"].min(),
    )
    upper = max(
        sampled["current_lap_time_seconds"].max(),
        sampled["next_lap_time_seconds"].max(),
    )
    ax.plot(
        [lower, upper],
        [lower, upper],
        color="#333333",
        linewidth=1.2,
        linestyle="--",
        label="No change",
    )
    ax.set(
        title="Current lap strongly anchors the next clean lap",
        xlabel="Current lap time (s)",
        ylabel="Next consecutive lap time (s)",
    )
    ax.legend(ncols=2)
    fig.text(
        0.5,
        0.01,
        "2024 train + validation events; deterministic sample, "
        "up to 250 rows per event",
        ha="center",
        fontsize=9,
    )
    _save_figure(fig, path)


def _plot_tyre_age_profile(profile: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5.8))
    ordered_bands = list(dict.fromkeys(profile["tyre_age_band"]))
    positions = {band: index for index, band in enumerate(ordered_bands)}
    for compound in ("HARD", "MEDIUM", "SOFT"):
        rows = profile.loc[profile["compound"].eq(compound)].copy()
        if rows.empty:
            continue
        x = rows["tyre_age_band"].map(positions).astype(float)
        ax.plot(
            x,
            rows["median"],
            marker="o",
            linewidth=2,
            color=COMPOUND_COLORS[compound],
            label=compound.title(),
        )
        ax.fill_between(
            x, rows["q25"], rows["q75"], color=COMPOUND_COLORS[compound], alpha=0.16
        )
    ax.axhline(0, color="#333333", linewidth=1, linestyle="--")
    ax.set_xticks(range(len(ordered_bands)), ordered_bands)
    ax.set(
        title="Observed pace varies with reported tyre life",
        xlabel="Reported tyre life band (laps)",
        ylabel="Current lap minus driver-stint median (s)",
    )
    ax.legend(title="Compound")
    fig.text(
        0.5,
        0.01,
        "Lines show medians; bands show interquartile ranges. Descriptive only; "
        "not a causal tyre-wear estimate.",
        ha="center",
        fontsize=9,
    )
    _save_figure(fig, path)


def _plot_coverage(data: pd.DataFrame, path: Path) -> None:
    coverage = data.pivot_table(
        index="event_name",
        columns="compound",
        values="sample_id",
        aggfunc="size",
        fill_value=0,
    )
    event_order = data.groupby("event_name")["round_number"].first().sort_values().index
    coverage = coverage.reindex(event_order)
    fig, ax = plt.subplots(figsize=(9, 6.2))
    left = pd.Series(0.0, index=coverage.index)
    for compound in ("HARD", "MEDIUM", "SOFT"):
        values = coverage.get(compound, pd.Series(0, index=coverage.index))
        ax.barh(
            coverage.index,
            values,
            left=left,
            color=COMPOUND_COLORS[compound],
            label=compound.title(),
        )
        left += values
    ax.invert_yaxis()
    ax.set(
        title="Development coverage differs by event and compound",
        xlabel="Validated current-to-next-lap samples",
        ylabel="2024 race event",
    )
    ax.legend(title="Compound", ncols=3)
    fig.text(
        0.5,
        0.01,
        "Training and validation events only; counts reflect US-04 eligibility rules",
        ha="center",
        fontsize=9,
    )
    _save_figure(fig, path)


def _plot_missingness(data: pd.DataFrame, path: Path) -> None:
    missing = data.groupby("event_name")[list(NULLABLE_FEATURES)].apply(
        lambda frame: frame.isna().mean().mul(100)
    )
    order = data.groupby("event_name")["round_number"].first().sort_values().index
    missing = missing.reindex(order)
    fig, ax = plt.subplots(figsize=(10, 6.2))
    image = ax.imshow(
        missing.to_numpy(),
        cmap="cividis",
        vmin=0,
        vmax=max(10, float(missing.max().max())),
    )
    ax.set_xticks(
        range(len(NULLABLE_FEATURES)),
        ["Sector 1", "Sector 2", "Sector 3", "Previous lap", "Previous delta"],
        rotation=20,
        ha="right",
    )
    ax.set_yticks(range(len(missing.index)), missing.index)
    for row in range(len(missing.index)):
        for column in range(len(NULLABLE_FEATURES)):
            ax.text(
                column,
                row,
                f"{missing.iloc[row, column]:.1f}%",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if missing.iloc[row, column] < 4 else "black",
            )
    ax.set(
        title=(
            "Previous-lap context drives nullable feature gaps\n"
            "2024 training + validation events"
        ),
        xlabel="Nullable feature",
        ylabel="2024 race event",
    )
    colorbar = fig.colorbar(image, ax=ax, pad=0.02)
    colorbar.set_label("Missing rows (%)")
    _save_figure(fig, path)


def _render_report(
    data: pd.DataFrame,
    event_summary: pd.DataFrame,
    age_profile: pd.DataFrame,
    config: AnalysisConfig,
    dataset_sha256: str,
) -> str:
    correlation = data["current_lap_time_seconds"].corr(data["next_lap_time_seconds"])
    persistence_error = (
        data["next_lap_time_seconds"] - data["current_lap_time_seconds"]
    ).abs()
    compound_counts = data["compound"].value_counts()
    previous_missing = data["previous_lap_time_seconds"].isna().mean() * 100
    event_min = event_summary.loc[event_summary["persistence_mae_seconds"].idxmin()]
    event_max = event_summary.loc[event_summary["persistence_mae_seconds"].idxmax()]
    profile_range = age_profile["median"].max() - age_profile["median"].min()
    lines = [
        "# Exploratory Motorsport Analysis",
        "",
        f"**Analysis version:** {config.analysis_version}",
        f"**Dataset SHA-256:** `{dataset_sha256}`",
        (
            "**Exploration boundary:** training and validation events only; "
            "frozen test rows were not loaded"
        ),
        "",
        "## Engineering Questions",
        "",
        (
            "1. How strongly does the completed current lap anchor the immediately "
            "next clean lap, and how demanding is the persistence baseline?"
        ),
        (
            "2. How does observed within-stint pace vary across reported tyre-life "
            "bands and compounds, without treating the association as causal wear?"
        ),
        "3. Is development coverage balanced across events and slick compounds?",
        (
            "4. Where are nullable feature gaps concentrated, and what "
            "preprocessing constraint follows?"
        ),
        "",
        "## Scope and Measurement Types",
        "",
        (
            f"The analysis uses {len(data):,} validated samples from "
            f"{data['event_id'].nunique()} development events: six training and two "
            "validation races. Measured FastF1 fields include lap and sector times, "
            "compound, reported tyre life, position, team, and weather. Engineered "
            "modelling fields include next-lap and previous-lap deltas. Figure 2 adds "
            "an analysis-only driver-stint median centering that uses the complete "
            "stint and is forbidden as a prediction feature."
        ),
        "",
        (
            "The analysis assumes the US-04 eligibility rules adequately remove "
            "wet, pit, inaccurate, deleted, and disrupted laps. Reported tyre life "
            "is not direct physical wear, long stints are selected by race strategy "
            "and survival, and fuel load, traffic, driver management, car "
            "performance, and circuit layout remain plausible confounders."
        ),
        "",
        "## Findings",
        "",
        "### Q1 — Current-to-next-lap persistence",
        "",
        (
            "Current and next clean lap times have Pearson correlation "
            f"`{correlation:.4f}`. The descriptive persistence error is "
            f"{persistence_error.mean():.3f} s MAE overall, ranging from "
            f"{event_min['persistence_mae_seconds']:.3f} s at "
            f"{event_min['event_name']} to "
            f"{event_max['persistence_mae_seconds']:.3f} s at "
            f"{event_max['event_name']}. This supports a strong mandatory "
            "persistence baseline; it does not establish model performance."
        ),
        "",
        "![Current versus next lap](figures/01-current-vs-next-lap.png)",
        "",
        (
            "*Figure 1. Current versus immediately consecutive next-lap time for a "
            "deterministic event-balanced sample. The dashed identity line denotes "
            "no lap-time change.*"
        ),
        "",
        "### Q2 — Tyre age and observed pace",
        "",
        (
            "Across compound-by-age summaries, the median analysis-only centered "
            f"pace spans {profile_range:.3f} s. The direction is not interpreted as "
            "a tyre-only effect because fuel burn, traffic, driver pace management, "
            "stint selection, circuit, and temperature vary with lap and tyre age."
        ),
        "",
        "![Tyre-age pace profile](figures/02-tyre-age-pace-profile.png)",
        "",
        (
            "*Figure 2. Median current lap time relative to each driver-stint "
            "median, with interquartile ranges. This post-event centered measure is "
            "descriptive and must never enter a predictive feature set.*"
        ),
        "",
        "### Q3 — Event and compound coverage",
        "",
        (
            f"The development data contain {compound_counts.get('HARD', 0):,} "
            f"hard, {compound_counts.get('MEDIUM', 0):,} medium, and "
            f"{compound_counts.get('SOFT', 0):,} soft samples. Event and compound "
            "counts are visibly unequal, so row-weighted aggregate metrics alone "
            "would overrepresent common contexts."
        ),
        "",
        "![Event and compound coverage](figures/03-event-compound-coverage.png)",
        "",
        (
            "*Figure 3. Validated sample counts by development event and compound. "
            "Complete events, not individual rows, remain the evaluation groups.*"
        ),
        "",
        "### Q4 — Nullable feature coverage",
        "",
        (
            "All retained sector times are complete, while previous-lap context is "
            f"missing for {previous_missing:.2f}% of development samples, "
            "principally the first targetable lap after each eligibility break. "
            "Missingness is structural rather than evidence that later laps should "
            "be used to fill the gap."
        ),
        "",
        "![Nullable feature missingness](figures/04-nullable-feature-missingness.png)",
        "",
        (
            "*Figure 4. Per-event missing percentages for fields allowed to be "
            "nullable by the dataset contract.*"
        ),
        "",
        "## Modelling Implications",
        "",
        (
            "- Always compare against current-lap persistence, using macro-event "
            "MAE as the primary selection metric."
        ),
        (
            "- Before candidate selection, require validation macro-event MAE at "
            "least 5% below the stronger fixed baseline, with no validation event "
            "degrading by more than 10%."
        ),
        (
            "- Retain current lap time, reported tyre life, compound, current "
            "weather, current position, team, and past-only pace context as candidate "
            "inputs. Treat driver, team, and event fields as categorical/grouping "
            "context rather than numeric magnitudes."
        ),
        (
            "- Exclude `rainfall` and `track_status` from version 1 model inputs "
            "because eligibility makes them constant; retain them as scope evidence."
        ),
        (
            "- Never use the analysis-only stint-centered pace, full-stint length, "
            "later-lap summaries, or either target column as a feature."
        ),
        (
            "- Fit missing-value handling, categorical encoding, scaling, and any "
            "robust outlier thresholds on training events only. Add explicit "
            "indicators for structurally missing previous-lap context if used."
        ),
        (
            "- Report per-event results plus compound, tyre-age, team/driver, "
            "fresh/used tyre, and temperature subgroups. Use event weighting so "
            "high-lap-count races and common hard-tyre samples do not dominate."
        ),
        (
            "- Treat fuel burn, traffic, driver management, circuit, car "
            "performance, stint-selection bias, and FastF1 corrections as unresolved "
            "confounding or measurement risks. Do not make causal tyre-wear claims."
        ),
        (
            "- Keep the frozen Mexico City and Abu Dhabi test events unopened until "
            "the method and numeric success margin are fixed."
        ),
        "",
        "## Reproduction",
        "",
        "```shell",
        "uv run python -m telemetry_project.cli analyze-data",
        "```",
        "",
        (
            "The command verifies each processed split against the US-04 manifest "
            "before reading it. Aggregate event evidence is saved in "
            "`reports/tables/exploratory-event-summary.csv`; figure and input hashes "
            "are recorded in `reports/exploratory-analysis-manifest.json`."
        ),
        "",
    ]
    return "\n".join(lines)


def run_exploratory_analysis(config: AnalysisConfig) -> ExploratorySummary:
    """Validate development data and generate all US-05 outputs."""
    data, dataset_manifest = _load_development_data(config)
    dataset_sha256 = str(dataset_manifest.get("dataset_sha256"))
    event_summary = build_event_summary(data)
    age_profile = build_tyre_age_profile(data, config.tyre_age_bin_edges)
    config.outputs.figure_directory.mkdir(parents=True, exist_ok=True)
    _style()
    figure_paths = [config.outputs.figure_directory / name for name in FIGURE_NAMES]
    _plot_current_vs_next(data, config, figure_paths[0])
    _plot_tyre_age_profile(age_profile, figure_paths[1])
    _plot_coverage(data, figure_paths[2])
    _plot_missingness(data, figure_paths[3])

    config.outputs.event_summary.parent.mkdir(parents=True, exist_ok=True)
    event_summary.to_csv(config.outputs.event_summary, index=False, lineterminator="\n")
    report = _render_report(data, event_summary, age_profile, config, dataset_sha256)
    config.outputs.report.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.report.write_text(report, encoding="utf-8", newline="\n")

    correlation = float(
        data["current_lap_time_seconds"].corr(data["next_lap_time_seconds"])
    )
    persistence_mae = float(
        (data["next_lap_time_seconds"] - data["current_lap_time_seconds"]).abs().mean()
    )
    manifest = {
        "manifest_schema_version": 1,
        "analysis_version": config.analysis_version,
        "analysis_config_path": config.source_path,
        "analysis_config_sha256": config.source_sha256,
        "dataset_manifest_path": config.source_dataset_manifest.as_posix(),
        "dataset_manifest_sha256": _sha256(config.source_dataset_manifest),
        "dataset_sha256": dataset_sha256,
        "included_splits": list(config.include_splits),
        "frozen_test_loaded": False,
        "random_seed": config.random_seed,
        "development_rows": len(data),
        "event_ids": sorted(str(value) for value in data["event_id"].unique()),
        "figures": [
            {"path": path.as_posix(), "sha256": _sha256(path)} for path in figure_paths
        ],
        "event_summary": {
            "path": config.outputs.event_summary.as_posix(),
            "sha256": _sha256(config.outputs.event_summary),
        },
        "report": {
            "path": config.outputs.report.as_posix(),
            "sha256": _sha256(config.outputs.report),
        },
    }
    _write_json(config.outputs.analysis_manifest, manifest)
    return ExploratorySummary(
        development_rows=len(data),
        events=data["event_id"].nunique(),
        figures=len(figure_paths),
        current_next_correlation=round(correlation, 6),
        persistence_mae_seconds=round(persistence_mae, 6),
        dataset_sha256=dataset_sha256,
    )
