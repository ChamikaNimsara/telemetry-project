"""Explainable, validation-only baselines for next-lap prediction."""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from telemetry_project import __version__
from telemetry_project.data.schema import read_analysis_csv
from telemetry_project.modeling.baseline_config import BaselineConfig
from telemetry_project.modeling.metrics import event_metrics

PERSISTENCE = "current_lap_persistence"
TRAINING_MEDIAN = "training_median_degradation"


class BaselineEvaluationError(ValueError):
    """Raised when baseline inputs or traceability checks are invalid."""


@dataclass(frozen=True, slots=True)
class BaselineEvaluationSummary:
    """Compact result returned by the baseline command."""

    training_rows: int
    validation_rows: int
    validation_events: int
    stronger_baseline: str
    stronger_macro_event_mae_seconds: float
    frozen_test_loaded: bool
    dataset_sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BaselineEvaluationError(
            f"Unable to read manifest '{path}': {error}"
        ) from error
    if not isinstance(payload, dict):
        raise BaselineEvaluationError(f"Manifest '{path}' must contain an object.")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_split(
    manifest: dict[str, Any], split: str
) -> tuple[pd.DataFrame, dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise BaselineEvaluationError("Dataset manifest outputs must be a list.")
    matches = [
        output
        for output in outputs
        if isinstance(output, dict) and output.get("split") == split
    ]
    if len(matches) != 1:
        raise BaselineEvaluationError(
            f"Dataset manifest must contain exactly one '{split}' output."
        )
    output = matches[0]
    path = Path(str(output.get("path", "")))
    if not path.is_file():
        raise BaselineEvaluationError(
            f"Processed '{split}' data is missing; run build-dataset first."
        )
    if _sha256(path) != output.get("sha256"):
        raise BaselineEvaluationError(
            f"Processed '{split}' data does not match its manifest hash."
        )
    frame = read_analysis_csv(str(path))
    if not frame["split"].eq(split).all():
        raise BaselineEvaluationError(f"Processed '{split}' data has wrong labels.")
    return frame, output


def _age_bands(values: pd.Series, edges: tuple[int, ...]) -> pd.Series:
    labels = [f"{left + 1}-{right}" for left, right in pairwise(edges)]
    return pd.cut(
        values,
        bins=edges,
        labels=labels,
        include_lowest=True,
    ).astype("string")


@dataclass(frozen=True, slots=True)
class MedianDegradationBaseline:
    """Training-only median next-lap change with an explicit fallback chain."""

    edges: tuple[int, ...]
    minimum_group_samples: int
    group_medians: dict[tuple[str, str], float]
    compound_medians: dict[str, float]
    global_median: float

    @classmethod
    def fit(
        cls, training: pd.DataFrame, *, edges: tuple[int, ...], minimum: int
    ) -> MedianDegradationBaseline:
        """Fit all target-derived statistics using training rows only."""
        working = training.assign(
            tyre_age_band=_age_bands(training["tyre_life_laps"], edges)
        )
        grouped = working.dropna(subset="tyre_age_band").groupby(
            ["compound", "tyre_age_band"], observed=True, sort=True
        )["next_lap_delta_seconds"]
        statistics = grouped.agg(["size", "median"])
        eligible = statistics.loc[statistics["size"].ge(minimum), "median"]
        group_medians = {
            (str(compound), str(age_band)): float(value)
            for (compound, age_band), value in eligible.items()
        }
        compound_medians = {
            str(compound): float(value)
            for compound, value in training.groupby("compound", sort=True)[
                "next_lap_delta_seconds"
            ]
            .median()
            .items()
        }
        return cls(
            edges=edges,
            minimum_group_samples=minimum,
            group_medians=group_medians,
            compound_medians=compound_medians,
            global_median=float(training["next_lap_delta_seconds"].median()),
        )

    def predict(self, rows: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Predict next-lap time and identify the statistic used for every row."""
        bands = _age_bands(rows["tyre_life_laps"], self.edges)
        deltas: list[float] = []
        sources: list[str] = []
        for compound, age_band in zip(rows["compound"], bands, strict=True):
            group_key = (str(compound), str(age_band))
            if pd.notna(age_band) and group_key in self.group_medians:
                deltas.append(self.group_medians[group_key])
                sources.append("compound_tyre_age_band")
            elif str(compound) in self.compound_medians:
                deltas.append(self.compound_medians[str(compound)])
                sources.append("compound")
            else:
                deltas.append(self.global_median)
                sources.append("global")
        predicted = rows["current_lap_time_seconds"].reset_index(drop=True) + pd.Series(
            deltas, dtype="float64"
        )
        return predicted, pd.Series(sources, dtype="string")


def _prediction_frame(
    validation: pd.DataFrame, model: MedianDegradationBaseline
) -> tuple[pd.DataFrame, dict[str, int]]:
    identity = validation[["event_id", "event_name"]].reset_index(drop=True)
    actual = validation["next_lap_time_seconds"].reset_index(drop=True)
    persistence = identity.assign(
        baseline=PERSISTENCE,
        actual=actual,
        predicted=validation["current_lap_time_seconds"].reset_index(drop=True),
    )
    median_predictions, sources = model.predict(validation)
    median = identity.assign(
        baseline=TRAINING_MEDIAN,
        actual=actual,
        predicted=median_predictions,
    )
    fallback_counts = {
        str(key): int(value) for key, value in sources.value_counts(sort=False).items()
    }
    return pd.concat([persistence, median], ignore_index=True), fallback_counts


def _rounded(value: object) -> object:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def _render_report(
    *,
    aggregate: dict[str, dict[str, float | int]],
    fallback_counts: dict[str, int],
    config: BaselineConfig,
    training_rows: int,
    validation_rows: int,
    event_ids: list[str],
) -> str:
    persistence = aggregate[PERSISTENCE]
    median = aggregate[TRAINING_MEDIAN]
    stronger = min(
        aggregate, key=lambda name: aggregate[name]["macro_event_mae_seconds"]
    )
    candidate_mae_limit = float(aggregate[stronger]["macro_event_mae_seconds"]) * 0.95
    table_header = (
        "| Baseline | Explanation | Macro-event MAE (s) | "
        "Macro-event RMSE (s) | Macro-event signed error (s) |"
    )
    persistence_row = (
        "| Current-lap persistence | Predict that the next clean lap equals the "
        f"just-completed lap. | {persistence['macro_event_mae_seconds']:.4f} | "
        f"{persistence['macro_event_rmse_seconds']:.4f} | "
        f"{persistence['macro_event_signed_error_seconds']:.4f} |"
    )
    median_row = (
        "| Training-median degradation | Add the training median next-lap change "
        "for the current compound and reported tyre-age band. | "
        f"{median['macro_event_mae_seconds']:.4f} | "
        f"{median['macro_event_rmse_seconds']:.4f} | "
        f"{median['macro_event_signed_error_seconds']:.4f} |"
    )
    return f"""# Model Report

## US-06 — Validation Baselines

### Evaluation boundary

Both rules predict `next_lap_time_seconds` at the end of the current eligible
lap. Their metrics use the same {validation_rows:,} validation rows and complete
held-out events ({", ".join(event_ids)}) that later candidates must use during
selection. Only the {training_rows:,} training rows are used to estimate the
second rule. The frozen test files are not loaded by this command.

The primary metric is unweighted macro-event mean absolute error (MAE), so each
race contributes equally even when sample counts differ. Secondary diagnostics
are event-macro RMSE, median absolute error, and signed error, plus pooled
versions for auditability. All errors are in seconds.

### Rules and results

{table_header}
|---|---|---:|---:|---:|
{persistence_row}
{median_row}

The stronger fixed benchmark on validation is **{stronger.replace("_", " ")}**.
Under D-008, a candidate must reduce validation macro-event MAE by at least 5%
relative to this rule: the maximum qualifying MAE is
**{candidate_mae_limit:.6f} s**. It also may not worsen either validation event
by more than 10% before it can be selected.

### What the training-median rule knows

The rule knows the current lap time, reported compound, and reported tyre life,
all available at prediction time. It learns only the median observed
`next_lap_delta_seconds` from training events. A compound/age cell is used only
when it has at least {config.median_degradation.minimum_group_samples} training
samples. Otherwise the rule falls back first to the compound median and then to
the global training median. Validation fallback counts were:
{", ".join(f"{key}={value:,}" for key, value in sorted(fallback_counts.items()))}.

This rule is deliberately not a fitted physical tyre-wear model. Its age bands
are coarse, and its medians do not adjust for driver, circuit, fuel mass,
traffic, track evolution, temperature, setup, or interactions among them. It
can underperform when a validation event has conditions unlike training, when
reported tyre life is outside well-covered cells, or when the current lap is an
unrepresentative anchor. These are predictive associations, not causal tyre
effects.

### Reproduction and evidence

Run:

```shell
uv run python -m telemetry_project.cli evaluate-baselines
```

The command verifies input hashes, fits on `train`, evaluates only on
`validation`, and rewrites the aggregate metrics, per-event table, this report,
and experiment manifest deterministically. See
`reports/baseline-validation-metrics.json` and
`reports/tables/baseline-validation-by-event.csv` for exact values.
"""


def run_baseline_evaluation(config: BaselineConfig) -> BaselineEvaluationSummary:
    """Fit explainable rules on train and evaluate only on validation events."""
    manifest = _load_json(config.source_dataset_manifest)
    if manifest.get("manifest_schema_version") != 1:
        raise BaselineEvaluationError("Dataset manifest schema version must be 1.")
    training, training_output = _load_split(manifest, config.fit_split)
    validation, validation_output = _load_split(manifest, config.evaluation_split)
    overlap = set(training["event_id"]) & set(validation["event_id"])
    if overlap:
        raise BaselineEvaluationError(
            f"Training and validation events overlap: {', '.join(sorted(overlap))}"
        )

    median_model = MedianDegradationBaseline.fit(
        training,
        edges=config.median_degradation.tyre_age_bin_edges,
        minimum=config.median_degradation.minimum_group_samples,
    )
    predictions, fallback_counts = _prediction_frame(validation, median_model)
    per_event, aggregate = event_metrics(predictions)
    per_event = per_event.round(6)
    aggregate = _rounded(aggregate)  # type: ignore[assignment]
    stronger = min(
        aggregate, key=lambda name: aggregate[name]["macro_event_mae_seconds"]
    )
    event_ids = sorted(str(value) for value in validation["event_id"].unique())
    stronger_mae = float(aggregate[stronger]["macro_event_mae_seconds"])

    metrics_payload = {
        "metrics_schema_version": 1,
        "experiment_version": config.experiment_version,
        "fit_split": config.fit_split,
        "evaluation_split": config.evaluation_split,
        "target_column": config.target_column,
        "primary_metric": "macro_event_mae_seconds",
        "units": "seconds",
        "stronger_baseline": stronger,
        "stronger_macro_event_mae_seconds": stronger_mae,
        "candidate_selection_gate": {
            "minimum_macro_event_mae_reduction_percent": 5.0,
            "maximum_candidate_macro_event_mae_seconds": round(stronger_mae * 0.95, 6),
            "maximum_per_event_mae_increase_percent": 10.0,
        },
        "baselines": aggregate,
    }
    _write_json(config.outputs.metrics, metrics_payload)
    config.outputs.per_event_metrics.parent.mkdir(parents=True, exist_ok=True)
    per_event.to_csv(config.outputs.per_event_metrics, index=False, lineterminator="\n")
    report = _render_report(
        aggregate=aggregate,
        fallback_counts=fallback_counts,
        config=config,
        training_rows=len(training),
        validation_rows=len(validation),
        event_ids=event_ids,
    )
    config.outputs.model_report.parent.mkdir(parents=True, exist_ok=True)
    config.outputs.model_report.write_text(report, encoding="utf-8", newline="\n")

    output_hashes = {
        path.as_posix(): _sha256(path)
        for path in (
            config.outputs.metrics,
            config.outputs.per_event_metrics,
            config.outputs.model_report,
        )
    }
    experiment_manifest = {
        "manifest_schema_version": 1,
        "experiment_version": config.experiment_version,
        "project_version": __version__,
        "python_version": platform.python_version(),
        "baseline_config_path": config.source_path,
        "baseline_config_sha256": config.source_sha256,
        "dataset_manifest_path": config.source_dataset_manifest.as_posix(),
        "dataset_manifest_sha256": _sha256(config.source_dataset_manifest),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "fit": {
            "split": config.fit_split,
            "event_ids": sorted(str(value) for value in training["event_id"].unique()),
            "rows": len(training),
            "file_sha256": training_output.get("sha256"),
        },
        "evaluation": {
            "split": config.evaluation_split,
            "event_ids": event_ids,
            "rows": len(validation),
            "file_sha256": validation_output.get("sha256"),
        },
        "frozen_test_loaded": False,
        "median_degradation_fit": {
            "group_columns": list(config.median_degradation.group_columns),
            "tyre_age_bin_edges": list(config.median_degradation.tyre_age_bin_edges),
            "minimum_group_samples": config.median_degradation.minimum_group_samples,
            "fallback_order": list(config.median_degradation.fallback_order),
            "retained_group_cells": len(median_model.group_medians),
            "compound_medians": _rounded(median_model.compound_medians),
            "global_median_seconds": round(median_model.global_median, 6),
            "validation_prediction_sources": fallback_counts,
        },
        "outputs": output_hashes,
    }
    _write_json(config.outputs.experiment_manifest, experiment_manifest)

    return BaselineEvaluationSummary(
        training_rows=len(training),
        validation_rows=len(validation),
        validation_events=len(event_ids),
        stronger_baseline=stronger,
        stronger_macro_event_mae_seconds=float(
            aggregate[stronger]["macro_event_mae_seconds"]
        ),
        frozen_test_loaded=False,
        dataset_sha256=str(manifest.get("dataset_sha256")),
    )
