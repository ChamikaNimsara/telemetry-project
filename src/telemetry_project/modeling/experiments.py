"""Leakage-safe candidate selection and one-time final evaluation."""

from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import asdict, dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "telemetry-project-matplotlib")
)
import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt

from telemetry_project import __version__
from telemetry_project.modeling.baseline_config import load_baseline_config
from telemetry_project.modeling.baselines import (
    PERSISTENCE,
    TRAINING_MEDIAN,
    MedianDegradationBaseline,
    _load_json,
    _load_split,
    _rounded,
    _sha256,
    _write_json,
)
from telemetry_project.modeling.metrics import event_metrics, regression_metrics
from telemetry_project.modeling.selection_config import (
    FinalModelConfig,
    SelectionConfig,
    load_selection_config,
)

TWO_LAP_MEAN = "two_lap_mean"
PACE_REVERSION = "pace_reversion"
PACE_REVERSION_CONTEXT = "pace_reversion_compound_tyre_age"
FINAL_FIGURES = (
    "05-final-predicted-vs-observed.png",
    "06-final-mae-by-compound.png",
    "07-final-pace-change-by-tyre-age.png",
)


class ModelExperimentError(ValueError):
    """Raised when selection or final-evaluation safeguards fail."""


@dataclass(frozen=True, slots=True)
class SelectionSummary:
    """Compact result from training/validation candidate selection."""

    training_rows: int
    validation_rows: int
    candidates: int
    qualifying_candidates: int
    selected_method: str
    selected_macro_event_mae_seconds: float
    frozen_test_loaded: bool


@dataclass(frozen=True, slots=True)
class FinalEvaluationSummary:
    """Compact result from the frozen held-out evaluation."""

    development_rows: int
    test_rows: int
    test_events: int
    selected_method: str
    selected_macro_event_mae_seconds: float
    stronger_baseline_macro_event_mae_seconds: float
    improvement_percent: float


def _bands(values: pd.Series, edges: tuple[float, ...]) -> pd.Series:
    labels = [f"{left:g}..{right:g}" for left, right in pairwise(edges)]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True).astype(
        "string"
    )


def _age_bands(values: pd.Series, edges: tuple[int, ...]) -> pd.Series:
    labels = [f"{left + 1}-{right}" for left, right in pairwise(edges)]
    return pd.cut(values, bins=edges, labels=labels, include_lowest=True).astype(
        "string"
    )


@dataclass(frozen=True, slots=True)
class PaceReversionModel:
    """Median next-lap change conditioned on the latest observed pace change."""

    previous_delta_edges: tuple[float, ...]
    tyre_age_edges: tuple[int, ...]
    group_columns: tuple[str, ...]
    minimum_group_samples: int
    group_medians: dict[tuple[str, ...], float]
    band_medians: dict[str, float]
    global_median: float

    @classmethod
    def fit(
        cls,
        training: pd.DataFrame,
        *,
        previous_delta_edges: tuple[float, ...],
        tyre_age_edges: tuple[int, ...],
        group_columns: tuple[str, ...],
        minimum_group_samples: int,
    ) -> PaceReversionModel:
        """Fit robust lookup statistics using training targets only."""
        working = training.assign(
            previous_delta_band=_bands(
                training["previous_lap_delta_seconds"], previous_delta_edges
            ),
            tyre_age_band=_age_bands(training["tyre_life_laps"], tyre_age_edges),
        ).dropna(subset="previous_delta_band")
        keys = [*group_columns, "previous_delta_band"]
        statistics = working.groupby(keys, observed=True, sort=True)[
            "next_lap_delta_seconds"
        ].agg(["size", "median"])
        retained = statistics.loc[statistics["size"].ge(minimum_group_samples)]
        group_medians: dict[tuple[str, ...], float] = {}
        for raw_key, value in retained["median"].items():
            key = raw_key if isinstance(raw_key, tuple) else (raw_key,)
            group_medians[tuple(str(item) for item in key)] = float(value)
        band_medians = {
            str(key): float(value)
            for key, value in working.groupby(
                "previous_delta_band", observed=True, sort=True
            )["next_lap_delta_seconds"]
            .median()
            .items()
        }
        return cls(
            previous_delta_edges=previous_delta_edges,
            tyre_age_edges=tyre_age_edges,
            group_columns=group_columns,
            minimum_group_samples=minimum_group_samples,
            group_medians=group_medians,
            band_medians=band_medians,
            global_median=float(training["next_lap_delta_seconds"].median()),
        )

    def predict(self, rows: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Predict from the most specific retained cell, then documented fallbacks."""
        previous_bands = _bands(
            rows["previous_lap_delta_seconds"], self.previous_delta_edges
        )
        age_bands = _age_bands(rows["tyre_life_laps"], self.tyre_age_edges)
        deltas: list[float] = []
        sources: list[str] = []
        for position in range(len(rows)):
            previous_band = previous_bands.iloc[position]
            if pd.isna(previous_band):
                deltas.append(self.global_median)
                sources.append("global_missing_history")
                continue
            values = {
                "compound": str(rows["compound"].iloc[position]),
                "tyre_age_band": str(age_bands.iloc[position]),
            }
            key = tuple(
                [*(values[column] for column in self.group_columns), str(previous_band)]
            )
            if key in self.group_medians:
                deltas.append(self.group_medians[key])
                sources.append("group")
            elif str(previous_band) in self.band_medians:
                deltas.append(self.band_medians[str(previous_band)])
                sources.append("previous_delta_band")
            else:
                deltas.append(self.global_median)
                sources.append("global")
        predicted = rows["current_lap_time_seconds"].reset_index(drop=True) + pd.Series(
            deltas, dtype="float64"
        )
        return predicted, pd.Series(sources, dtype="string")


def _fit_candidate(
    name: str, training: pd.DataFrame, config: SelectionConfig
) -> PaceReversionModel | None:
    if name == TWO_LAP_MEAN:
        return None
    groups = () if name == PACE_REVERSION else ("compound", "tyre_age_band")
    return PaceReversionModel.fit(
        training,
        previous_delta_edges=config.previous_delta_bin_edges,
        tyre_age_edges=config.tyre_age_bin_edges,
        group_columns=groups,
        minimum_group_samples=config.minimum_group_samples,
    )


def _predict_candidate(
    name: str,
    rows: pd.DataFrame,
    config: SelectionConfig,
    model: PaceReversionModel | None,
) -> tuple[pd.Series, pd.Series]:
    if name == TWO_LAP_MEAN:
        previous = rows["previous_lap_time_seconds"].fillna(
            rows["current_lap_time_seconds"]
        )
        predicted = (
            config.two_lap_current_weight * rows["current_lap_time_seconds"]
            + (1 - config.two_lap_current_weight) * previous
        ).reset_index(drop=True)
        sources = pd.Series(
            [
                "current_only" if missing else "two_lap_mean"
                for missing in rows["previous_lap_time_seconds"].isna()
            ],
            dtype="string",
        )
        return predicted, sources
    if model is None:
        raise AssertionError(f"Candidate '{name}' requires a fitted model.")
    return model.predict(rows)


def _as_prediction_frame(
    rows: pd.DataFrame, name: str, predicted: pd.Series
) -> pd.DataFrame:
    return (
        rows[["event_id", "event_name"]]
        .reset_index(drop=True)
        .assign(
            baseline=name,
            actual=rows["next_lap_time_seconds"].reset_index(drop=True),
            predicted=predicted,
        )
    )


def _load_baseline_reference(
    config: SelectionConfig,
) -> tuple[dict[str, Any], pd.DataFrame]:
    metrics = _load_json(config.baseline_metrics)
    try:
        per_event = pd.read_csv(config.baseline_per_event_metrics)
    except OSError as error:
        raise ModelExperimentError(
            f"Unable to read baseline event metrics: {error}"
        ) from error
    if metrics.get("evaluation_split") != "validation":
        raise ModelExperimentError("Baseline reference is not validation-only.")
    return metrics, per_event


def _final_config_payload(
    config: SelectionConfig, selected: str, candidate_metrics_sha256: str
) -> dict[str, object]:
    baseline_path = Path("configs/baseline.yaml")
    implementation_path = Path("src/telemetry_project/modeling/experiments.py")
    return {
        "schema_version": 1,
        "experiment_version": config.experiment_version,
        "selected_method": selected,
        "previous_delta_bin_edges": list(config.previous_delta_bin_edges),
        "minimum_group_samples": config.minimum_group_samples,
        "fit_splits": ["train", "validation"],
        "evaluation_split": "test",
        "random_seed": config.random_seed,
        "source_dataset_manifest": config.source_dataset_manifest.as_posix(),
        "source_selection_config": config.source_path,
        "source_selection_config_sha256": config.source_sha256,
        "candidate_metrics": config.outputs.candidate_metrics.as_posix(),
        "candidate_metrics_sha256": candidate_metrics_sha256,
        "baseline_config": baseline_path.as_posix(),
        "baseline_config_sha256": _sha256(baseline_path),
        "model_implementation": implementation_path.as_posix(),
        "model_implementation_sha256": _sha256(implementation_path),
        "outputs": {
            "predictions": "artifacts/predictions/final-test-predictions.csv",
            "metrics": "reports/final-test-metrics.json",
            "per_event_metrics": "reports/tables/final-test-by-event.csv",
            "condition_metrics": "reports/tables/final-test-by-condition.csv",
            "experiment_manifest": "reports/final-experiment-manifest.json",
            "model_report": "reports/model-report.md",
            "figure_directory": "reports/figures",
        },
    }


def select_model(config: SelectionConfig) -> SelectionSummary:
    """Compare the frozen candidate set without loading final test rows."""
    manifest = _load_json(config.source_dataset_manifest)
    training, _ = _load_split(manifest, config.fit_split)
    validation, _ = _load_split(manifest, config.evaluation_split)
    if set(training["event_id"]) & set(validation["event_id"]):
        raise ModelExperimentError("Training and validation event groups overlap.")
    baseline_metrics, baseline_per_event = _load_baseline_reference(config)
    stronger = str(baseline_metrics.get("stronger_baseline"))
    gate = baseline_metrics.get("candidate_selection_gate")
    if not isinstance(gate, dict):
        raise ModelExperimentError("Baseline metrics do not define the candidate gate.")
    maximum_mae = float(gate["maximum_candidate_macro_event_mae_seconds"])
    maximum_event_ratio = (
        1 + float(gate["maximum_per_event_mae_increase_percent"]) / 100
    )
    baseline_events = baseline_per_event.loc[
        baseline_per_event["baseline"].eq(stronger)
    ].set_index("event_id")["mae_seconds"]

    frames: list[pd.DataFrame] = []
    sources: dict[str, dict[str, int]] = {}
    for name in config.candidates:
        model = _fit_candidate(name, training, config)
        predicted, prediction_sources = _predict_candidate(
            name, validation, config, model
        )
        frames.append(_as_prediction_frame(validation, name, predicted))
        sources[name] = {
            str(key): int(value)
            for key, value in prediction_sources.value_counts(sort=False).items()
        }
    predictions = pd.concat(frames, ignore_index=True)
    per_event, aggregate = event_metrics(predictions)
    per_event = per_event.round(6)
    aggregate = _rounded(aggregate)  # type: ignore[assignment]

    qualification: dict[str, dict[str, object]] = {}
    for name in config.candidates:
        candidate_events = per_event.loc[per_event["baseline"].eq(name)].set_index(
            "event_id"
        )["mae_seconds"]
        event_ratios = candidate_events / baseline_events
        mae_pass = float(aggregate[name]["macro_event_mae_seconds"]) <= maximum_mae
        event_pass = bool(event_ratios.le(maximum_event_ratio).all())
        qualification[name] = {
            "qualifies": mae_pass and event_pass,
            "macro_event_mae_gate_pass": mae_pass,
            "per_event_regression_gate_pass": event_pass,
            "maximum_event_mae_ratio": round(float(event_ratios.max()), 6),
            "prediction_sources": sources[name],
        }
    qualifying = [
        name for name in config.candidates if qualification[name]["qualifies"] is True
    ]
    if not qualifying:
        raise ModelExperimentError(
            "No candidate passed the frozen validation gates; "
            "final test remains unopened."
        )
    selected = min(
        qualifying, key=lambda name: aggregate[name]["macro_event_mae_seconds"]
    )
    metrics_payload = {
        "metrics_schema_version": 1,
        "experiment_version": config.experiment_version,
        "fit_split": "train",
        "evaluation_split": "validation",
        "target_column": config.target_column,
        "primary_metric": "macro_event_mae_seconds",
        "baseline_reference": {
            "name": stronger,
            "macro_event_mae_seconds": baseline_metrics[
                "stronger_macro_event_mae_seconds"
            ],
            "candidate_gate": gate,
        },
        "candidates": aggregate,
        "qualification": qualification,
        "selected_method": selected,
        "selection_rule": "lowest qualifying validation macro-event MAE",
        "frozen_test_loaded": False,
    }
    _write_json(config.outputs.candidate_metrics, metrics_payload)
    config.outputs.candidate_per_event_metrics.parent.mkdir(parents=True, exist_ok=True)
    per_event.to_csv(
        config.outputs.candidate_per_event_metrics, index=False, lineterminator="\n"
    )
    final_payload = _final_config_payload(
        config, selected, _sha256(config.outputs.candidate_metrics)
    )
    config.outputs.final_model_config.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.final_model_config.write_text(
        yaml.safe_dump(final_payload, sort_keys=False), encoding="utf-8", newline="\n"
    )
    selection_manifest = {
        "manifest_schema_version": 1,
        "experiment_version": config.experiment_version,
        "project_version": __version__,
        "python_version": platform.python_version(),
        "random_seed": config.random_seed,
        "selection_config_path": config.source_path,
        "selection_config_sha256": config.source_sha256,
        "model_implementation_sha256": _sha256(Path(__file__)),
        "dataset_manifest_sha256": _sha256(config.source_dataset_manifest),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "training_event_ids": sorted(
            str(value) for value in training["event_id"].unique()
        ),
        "validation_event_ids": sorted(
            str(value) for value in validation["event_id"].unique()
        ),
        "selected_method": selected,
        "frozen_test_loaded": False,
        "outputs": {
            path.as_posix(): _sha256(path)
            for path in (
                config.outputs.candidate_metrics,
                config.outputs.candidate_per_event_metrics,
                config.outputs.final_model_config,
            )
        },
    }
    _write_json(config.outputs.selection_manifest, selection_manifest)
    return SelectionSummary(
        training_rows=len(training),
        validation_rows=len(validation),
        candidates=len(config.candidates),
        qualifying_candidates=len(qualifying),
        selected_method=selected,
        selected_macro_event_mae_seconds=float(
            aggregate[selected]["macro_event_mae_seconds"]
        ),
        frozen_test_loaded=False,
    )


def _condition_metrics(predictions: pd.DataFrame, test: pd.DataFrame) -> pd.DataFrame:
    context = test[["compound", "tyre_life_laps", "previous_lap_time_seconds"]].copy()
    context["tyre_age_band"] = _age_bands(
        context["tyre_life_laps"], (0, 5, 10, 15, 20, 30, 40, 60)
    )
    context["history_available"] = (
        context["previous_lap_time_seconds"]
        .notna()
        .map({True: "available", False: "missing"})
    )
    rows: list[dict[str, object]] = []
    for model_name, model_rows in predictions.groupby("baseline", sort=True):
        for condition in ("compound", "tyre_age_band", "history_available"):
            for level, indexes in context.groupby(
                condition, observed=True
            ).groups.items():
                group = model_rows.iloc[list(indexes)]
                values = regression_metrics(group["actual"], group["predicted"])
                rows.append(
                    {
                        "model": model_name,
                        "condition": condition,
                        "level": str(level),
                        **asdict(values),
                    }
                )
    return pd.DataFrame(rows).round(6)


def _save_figure(figure: Any, path: Path) -> None:
    figure.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        metadata={"Software": "telemetry-project"},
    )
    plt.close(figure)


def _plot_final_diagnostics(
    *,
    test: pd.DataFrame,
    selected_predictions: pd.Series,
    condition_metrics: pd.DataFrame,
    selected_method: str,
    stronger_baseline: str,
    output_directory: Path,
) -> tuple[Path, ...]:
    output_directory.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.25,
            "font.size": 10,
        }
    )
    paths = tuple(output_directory / name for name in FINAL_FIGURES)

    figure, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    actual = test["next_lap_time_seconds"].reset_index(drop=True)
    colors = {"2024-20-R": "#4477AA", "2024-24-R": "#EE6677"}
    for event_id, indexes in test.groupby("event_id", sort=True).groups.items():
        positions = list(indexes)
        axes[0].scatter(
            actual.iloc[positions],
            selected_predictions.iloc[positions],
            s=12,
            alpha=0.35,
            edgecolors="none",
            color=colors.get(str(event_id), "#228833"),
            label=str(test.loc[positions[0], "event_name"]),
        )
    lower = float(min(actual.min(), selected_predictions.min()))
    upper = float(max(actual.max(), selected_predictions.max()))
    axes[0].plot([lower, upper], [lower, upper], "--", color="#333333")
    axes[0].set(
        title="Held-out next-lap predictions",
        xlabel="Observed next lap (s)",
        ylabel="Predicted next lap (s)",
    )
    axes[0].legend()
    residual = actual - selected_predictions
    axes[1].hist(residual, bins=45, color="#66CCEE", edgecolor="white")
    axes[1].axvline(0, color="#333333", linestyle="--")
    axes[1].set(
        title="Held-out residual distribution",
        xlabel="Observed minus predicted (s)",
        ylabel="Samples",
    )
    figure.suptitle("Frozen pace-reversion model: final test diagnostics", fontsize=14)
    figure.tight_layout()
    _save_figure(figure, paths[0])

    compounds = ["HARD", "MEDIUM", "SOFT"]
    figure, axis = plt.subplots(figsize=(8.5, 5.4))
    width = 0.36
    for offset, model in (
        (-width / 2, stronger_baseline),
        (width / 2, selected_method),
    ):
        subset = condition_metrics.loc[
            condition_metrics["model"].eq(model)
            & condition_metrics["condition"].eq("compound")
        ].set_index("level")
        axis.bar(
            [index + offset for index in range(len(compounds))],
            [
                float(subset["mae_seconds"].get(compound, float("nan")))
                for compound in compounds
            ],
            width,
            label=model.replace("_", " ").title(),
        )
    axis.set_xticks(range(len(compounds)), [value.title() for value in compounds])
    axis.set(
        title="Final error varies by tyre compound",
        xlabel="Reported compound",
        ylabel="Mean absolute error (s)",
    )
    axis.legend()
    figure.tight_layout()
    _save_figure(figure, paths[1])

    profile = test.assign(
        tyre_age_band=_age_bands(
            test["tyre_life_laps"], (0, 5, 10, 15, 20, 30, 40, 60)
        ),
        predicted_delta=(
            selected_predictions.to_numpy()
            - test["current_lap_time_seconds"].to_numpy()
        ),
    ).dropna(subset="tyre_age_band")
    summary = profile.groupby("tyre_age_band", observed=True, sort=False).agg(
        observed_median=("next_lap_delta_seconds", "median"),
        observed_q25=("next_lap_delta_seconds", lambda values: values.quantile(0.25)),
        observed_q75=("next_lap_delta_seconds", lambda values: values.quantile(0.75)),
        predicted_median=("predicted_delta", "median"),
    )
    ordered_age_bands = [
        "1-5",
        "6-10",
        "11-15",
        "16-20",
        "21-30",
        "31-40",
        "41-60",
    ]
    summary = summary.reindex(ordered_age_bands).dropna(how="all")
    x = list(range(len(summary)))
    figure, axis = plt.subplots(figsize=(9, 5.4))
    axis.plot(x, summary["observed_median"], marker="o", label="Observed median")
    axis.fill_between(
        x,
        summary["observed_q25"],
        summary["observed_q75"],
        alpha=0.18,
        label="Observed interquartile range",
    )
    axis.plot(
        x,
        summary["predicted_median"],
        marker="s",
        label="Predicted median",
    )
    axis.axhline(0, color="#333333", linestyle="--")
    axis.set_xticks(x, summary.index, rotation=20)
    axis.set(
        title="Predicted and observed pace change across reported tyre age",
        xlabel="Reported tyre-life band (laps)",
        ylabel="Next minus current lap time (s)",
    )
    axis.legend()
    figure.text(
        0.5,
        0.01,
        "2024 Mexico City + Abu Dhabi test events; descriptive association, "
        "not physical tyre wear",
        ha="center",
        fontsize=9,
    )
    figure.tight_layout(rect=(0, 0.05, 1, 1))
    _save_figure(figure, paths[2])
    return paths


def _render_final_report(
    config: FinalModelConfig,
    candidate_metrics: dict[str, Any],
    final_metrics: dict[str, Any],
    per_event: pd.DataFrame,
    condition_metrics: pd.DataFrame,
    implausible: int,
) -> str:
    selected = config.selected_method
    validation = candidate_metrics["candidates"][selected]
    final = final_metrics["models"][selected]
    baseline_name = final_metrics["stronger_baseline"]
    baseline = final_metrics["models"][baseline_name]
    event_rows = per_event.loc[per_event["baseline"].eq(selected)]
    compound_rows = condition_metrics.loc[
        condition_metrics["model"].eq(selected)
        & condition_metrics["condition"].eq("compound")
    ]
    event_lines = "\n".join(
        f"| {row.event_name} | {row.samples:,} | {row.mae_seconds:.4f} | "
        f"{row.rmse_seconds:.4f} | {row.signed_error_seconds:.4f} |"
        for row in event_rows.itertuples()
    )
    compound_lines = "\n".join(
        f"| {row.level} | {row.samples:,} | {row.mae_seconds:.4f} |"
        for row in compound_rows.itertuples()
    )
    return f"""# Model Report

## US-06 — Baseline benchmark

Current-lap persistence predicts that the next clean lap will equal the lap just
completed. Training-median degradation adds the training median next-lap change
for the current compound and reported tyre-age band, falling back to compound
and then global training medians for sparse cells. Both operate at the same
prediction point and use the same eligible rows and metrics as candidates.

Persistence is vulnerable to an unrepresentative current lap. The median rule
is coarse and cannot adjust for circuit, driver, fuel, traffic, track evolution,
or interacting conditions. On validation, training-median degradation was the
stronger fixed baseline at 0.419979 s macro-event MAE; neither rule represents a
causal estimate of physical tyre wear.

## Final method and evaluation

The selected method is **pace reversion**: it places the latest observed
current-minus-previous lap change into one of ten predeclared bands and adds the
training median next-lap change for that band to the current lap. It is a robust,
interpretable conditional-median model. Missing history falls back to the global
development median. No future-lap value is an input.

Selection used six training events and two validation events only. Pace
reversion achieved {validation["macro_event_mae_seconds"]:.6f} s validation
macro-event MAE, passed the frozen 0.398980 s gate, and was frozen in
`configs/final-model.yaml` before test rows were loaded. The compound/tyre-age
variant was evaluated but not selected because the extra segmentation did not
improve validation MAE.

For the one-time final evaluation, the selected method and training-median
baseline were refitted on train plus validation, then compared on the two frozen
test races. The selected method achieved {final["macro_event_mae_seconds"]:.4f}
s macro-event MAE versus {baseline["macro_event_mae_seconds"]:.4f} s for the
stronger final baseline ({final_metrics["improvement_percent"]:.2f}% change).

### Held-out event variation

| Event | Samples | MAE (s) | RMSE (s) | Signed error (s) |
|---|---:|---:|---:|---:|
{event_lines}

### Error by compound

| Compound | Samples | MAE (s) |
|---|---:|---:|
{compound_lines}

### Error analysis, robustness, and limitations

The per-event range is the most defensible uncertainty signal with only two
held-out races; it is not enough to estimate a stable population confidence
interval. Condition-level results in
`reports/tables/final-test-by-condition.csv` cover compound, tyre-age band, and
missing previous-lap context. The selected method produced {implausible}
predictions outside the dataset's 30-300 s physical range.

The model mainly captures short-term pace reversion, not physical tyre wear.
Tyre age, compound, fuel load, traffic, circuit, and track evolution remain
associated and cannot be interpreted causally. Large disruptions are excluded
by the dataset policy, so accuracy does not establish performance during safety
cars, pit transitions, wet running, other seasons, or live operations. A poor
current or previous lap can still anchor a poor prediction.

### Reproduction

```shell
uv run python -m telemetry_project.cli select-model
uv run python -m telemetry_project.cli evaluate-final
```

The first command is development-only. The second verifies the frozen selection
hashes, writes row-level predictions to an ignored local artifact, and publishes
only aggregate metrics and figures. Do not rerun final evaluation to tune or
replace the selected method.
"""


def evaluate_final(config: FinalModelConfig) -> FinalEvaluationSummary:
    """Run the frozen method once on final test events and publish honest results."""
    if _sha256(config.source_selection_config) != config.source_selection_config_sha256:
        raise ModelExperimentError(
            "Selection config changed after the method was frozen."
        )
    if _sha256(config.candidate_metrics) != config.candidate_metrics_sha256:
        raise ModelExperimentError(
            "Candidate metrics changed after the method was frozen."
        )
    if _sha256(config.baseline_config) != config.baseline_config_sha256:
        raise ModelExperimentError(
            "Baseline config changed after the method was frozen."
        )
    if _sha256(config.model_implementation) != config.model_implementation_sha256:
        raise ModelExperimentError(
            "Model implementation changed after selection freeze."
        )
    candidate_metrics = _load_json(config.candidate_metrics)
    if candidate_metrics.get("selected_method") != config.selected_method:
        raise ModelExperimentError("Frozen method disagrees with candidate selection.")
    selection = load_selection_config(config.source_selection_config)
    manifest = _load_json(config.source_dataset_manifest)
    train, _ = _load_split(manifest, "train")
    validation, _ = _load_split(manifest, "validation")
    development = pd.concat([train, validation], ignore_index=True)
    test, test_output = _load_split(manifest, config.evaluation_split)
    if set(development["event_id"]) & set(test["event_id"]):
        raise ModelExperimentError("Development and test event groups overlap.")

    selected_model = _fit_candidate(config.selected_method, development, selection)
    selected_predictions, selected_sources = _predict_candidate(
        config.selected_method, test, selection, selected_model
    )
    persistence = test["current_lap_time_seconds"].reset_index(drop=True)
    baseline_config = load_baseline_config(config.baseline_config)
    median_model = MedianDegradationBaseline.fit(
        development,
        edges=baseline_config.median_degradation.tyre_age_bin_edges,
        minimum=baseline_config.median_degradation.minimum_group_samples,
    )
    median_predictions, median_sources = median_model.predict(test)
    prediction_frames = [
        _as_prediction_frame(test, PERSISTENCE, persistence),
        _as_prediction_frame(test, TRAINING_MEDIAN, median_predictions),
        _as_prediction_frame(test, config.selected_method, selected_predictions),
    ]
    predictions = pd.concat(prediction_frames, ignore_index=True)
    per_event, aggregate = event_metrics(predictions)
    per_event = per_event.round(6)
    aggregate = _rounded(aggregate)  # type: ignore[assignment]
    baseline_name = min(
        (PERSISTENCE, TRAINING_MEDIAN),
        key=lambda name: aggregate[name]["macro_event_mae_seconds"],
    )
    selected_mae = float(aggregate[config.selected_method]["macro_event_mae_seconds"])
    baseline_mae = float(aggregate[baseline_name]["macro_event_mae_seconds"])
    improvement = (baseline_mae - selected_mae) / baseline_mae * 100
    condition_metrics = _condition_metrics(predictions, test)
    implausible = int(
        ((selected_predictions < 30) | (selected_predictions > 300)).sum()
    )

    local_predictions = test[
        [
            "sample_id",
            "event_id",
            "event_name",
            "driver_number",
            "stint",
            "lap_number",
            "compound",
            "tyre_life_laps",
        ]
    ].reset_index(drop=True)
    local_predictions = local_predictions.assign(
        actual_next_lap_seconds=test["next_lap_time_seconds"].reset_index(drop=True),
        predicted_next_lap_seconds=selected_predictions,
        residual_seconds=(
            test["next_lap_time_seconds"].reset_index(drop=True) - selected_predictions
        ),
        prediction_source=selected_sources,
    )
    config.outputs.predictions.parent.mkdir(parents=True, exist_ok=True)
    local_predictions.to_csv(
        config.outputs.predictions, index=False, lineterminator="\n"
    )
    config.outputs.per_event_metrics.parent.mkdir(parents=True, exist_ok=True)
    per_event.to_csv(config.outputs.per_event_metrics, index=False, lineterminator="\n")
    condition_metrics.to_csv(
        config.outputs.condition_metrics, index=False, lineterminator="\n"
    )
    final_metrics = {
        "metrics_schema_version": 1,
        "experiment_version": config.experiment_version,
        "evaluation_split": "test",
        "evaluation_was_frozen_before_load": True,
        "selected_method": config.selected_method,
        "stronger_baseline": baseline_name,
        "primary_metric": "macro_event_mae_seconds",
        "models": aggregate,
        "improvement_percent": round(improvement, 6),
        "physically_implausible_predictions": implausible,
    }
    _write_json(config.outputs.metrics, final_metrics)
    figure_paths = _plot_final_diagnostics(
        test=test,
        selected_predictions=selected_predictions,
        condition_metrics=condition_metrics,
        selected_method=config.selected_method,
        stronger_baseline=baseline_name,
        output_directory=config.outputs.figure_directory,
    )
    report = _render_final_report(
        config,
        candidate_metrics,
        final_metrics,
        per_event,
        condition_metrics,
        implausible,
    )
    config.outputs.model_report.write_text(report, encoding="utf-8", newline="\n")
    experiment_manifest = {
        "manifest_schema_version": 1,
        "experiment_version": config.experiment_version,
        "project_version": __version__,
        "python_version": platform.python_version(),
        "random_seed": config.random_seed,
        "final_model_config_path": config.source_path,
        "final_model_config_sha256": config.source_sha256,
        "dataset_manifest_sha256": _sha256(config.source_dataset_manifest),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "selected_method": config.selected_method,
        "development_event_ids": sorted(
            str(value) for value in development["event_id"].unique()
        ),
        "test_event_ids": sorted(str(value) for value in test["event_id"].unique()),
        "test_rows": len(test),
        "test_file_sha256": test_output.get("sha256"),
        "test_evaluation_performed_once_after_selection_freeze": True,
        "selected_prediction_sources": {
            str(key): int(value)
            for key, value in selected_sources.value_counts(sort=False).items()
        },
        "baseline_prediction_sources": {
            str(key): int(value)
            for key, value in median_sources.value_counts(sort=False).items()
        },
        "outputs": {
            path.as_posix(): _sha256(path)
            for path in (
                config.outputs.predictions,
                config.outputs.metrics,
                config.outputs.per_event_metrics,
                config.outputs.condition_metrics,
                config.outputs.model_report,
                *figure_paths,
            )
        },
    }
    _write_json(config.outputs.experiment_manifest, experiment_manifest)
    return FinalEvaluationSummary(
        development_rows=len(development),
        test_rows=len(test),
        test_events=int(test["event_id"].nunique()),
        selected_method=config.selected_method,
        selected_macro_event_mae_seconds=selected_mae,
        stronger_baseline_macro_event_mae_seconds=baseline_mae,
        improvement_percent=round(improvement, 6),
    )
