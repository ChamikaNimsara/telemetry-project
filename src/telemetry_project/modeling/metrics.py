"""Fixed regression metrics for event-grouped model evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite, sqrt

import pandas as pd


@dataclass(frozen=True, slots=True)
class RegressionMetrics:
    """Required error metrics, expressed in seconds."""

    samples: int
    mae_seconds: float
    rmse_seconds: float
    median_absolute_error_seconds: float
    signed_error_seconds: float


def regression_metrics(actual: pd.Series, predicted: pd.Series) -> RegressionMetrics:
    """Calculate fixed metrics after validating aligned finite inputs."""
    if len(actual) == 0 or len(actual) != len(predicted):
        raise ValueError("Actual and predicted values must be non-empty and aligned.")
    actual_numeric = pd.to_numeric(actual, errors="coerce")
    predicted_numeric = pd.to_numeric(predicted, errors="coerce")
    if (
        actual_numeric.isna().any()
        or predicted_numeric.isna().any()
        or not actual_numeric.map(isfinite).all()
        or not predicted_numeric.map(isfinite).all()
    ):
        raise ValueError("Actual and predicted values must be finite numeric values.")
    errors = predicted_numeric - actual_numeric
    return RegressionMetrics(
        samples=len(errors),
        mae_seconds=float(errors.abs().mean()),
        rmse_seconds=sqrt(float(errors.pow(2).mean())),
        median_absolute_error_seconds=float(errors.abs().median()),
        signed_error_seconds=float(errors.mean()),
    )


def event_metrics(
    predictions: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict[str, float | int]]]:
    """Return per-event metrics and pooled/macro-event summaries."""
    required = {"baseline", "event_id", "event_name", "actual", "predicted"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"Predictions are missing columns: {', '.join(missing)}")

    rows: list[dict[str, object]] = []
    aggregate: dict[str, dict[str, float | int]] = {}
    for baseline, baseline_rows in predictions.groupby("baseline", sort=True):
        for (event_id, event_name), group in baseline_rows.groupby(
            ["event_id", "event_name"], sort=True
        ):
            values = regression_metrics(group["actual"], group["predicted"])
            rows.append(
                {
                    "baseline": baseline,
                    "event_id": event_id,
                    "event_name": event_name,
                    **asdict(values),
                }
            )
        all_events = pd.DataFrame(rows)
        per_event = all_events.loc[all_events["baseline"].eq(baseline)]
        pooled = regression_metrics(baseline_rows["actual"], baseline_rows["predicted"])
        aggregate[str(baseline)] = {
            "events": len(per_event),
            "samples": pooled.samples,
            "macro_event_mae_seconds": float(per_event["mae_seconds"].mean()),
            "macro_event_rmse_seconds": float(per_event["rmse_seconds"].mean()),
            "macro_event_median_absolute_error_seconds": float(
                per_event["median_absolute_error_seconds"].mean()
            ),
            "macro_event_signed_error_seconds": float(
                per_event["signed_error_seconds"].mean()
            ),
            "pooled_mae_seconds": pooled.mae_seconds,
            "pooled_rmse_seconds": pooled.rmse_seconds,
            "pooled_median_absolute_error_seconds": (
                pooled.median_absolute_error_seconds
            ),
            "pooled_signed_error_seconds": pooled.signed_error_seconds,
        }
    return pd.DataFrame(rows), aggregate
