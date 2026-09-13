"""Tests for fixed regression metric calculations."""

from math import sqrt

import pandas as pd
import pytest

from telemetry_project.modeling.metrics import event_metrics, regression_metrics


def test_regression_metrics_use_prediction_minus_actual_sign() -> None:
    result = regression_metrics(pd.Series([1.0, 3.0]), pd.Series([2.0, 1.0]))

    assert result.samples == 2
    assert result.mae_seconds == 1.5
    assert result.rmse_seconds == sqrt(2.5)
    assert result.median_absolute_error_seconds == 1.5
    assert result.signed_error_seconds == -0.5


def test_event_metrics_macro_average_weights_events_equally() -> None:
    predictions = pd.DataFrame(
        {
            "baseline": ["rule"] * 4,
            "event_id": ["event-1", "event-2", "event-2", "event-2"],
            "event_name": ["One", "Two", "Two", "Two"],
            "actual": [0.0, 0.0, 0.0, 0.0],
            "predicted": [2.0, 0.0, 0.0, 0.0],
        }
    )

    per_event, aggregate = event_metrics(predictions)

    assert per_event["mae_seconds"].tolist() == [2.0, 0.0]
    assert aggregate["rule"]["macro_event_mae_seconds"] == 1.0
    assert aggregate["rule"]["pooled_mae_seconds"] == 0.5


def test_regression_metrics_reject_non_numeric_values() -> None:
    with pytest.raises(ValueError, match="finite numeric"):
        regression_metrics(pd.Series([1.0]), pd.Series(["bad"]))


def test_event_metrics_requires_prediction_contract() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        event_metrics(pd.DataFrame({"actual": [1.0]}))


def test_regression_metrics_rejects_empty_and_infinite_values() -> None:
    with pytest.raises(ValueError, match="non-empty and aligned"):
        regression_metrics(pd.Series(dtype=float), pd.Series(dtype=float))
    with pytest.raises(ValueError, match="finite numeric"):
        regression_metrics(pd.Series([1.0]), pd.Series([float("inf")]))
