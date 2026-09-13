"""Tests for leakage-safe baseline fitting and evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from telemetry_project.modeling.baseline_config import (
    BaselineConfig,
    BaselineOutputs,
    MedianDegradationConfig,
)
from telemetry_project.modeling.baselines import (
    BaselineEvaluationError,
    MedianDegradationBaseline,
    run_baseline_evaluation,
)
from tests.data.test_schema import valid_frame


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(split: str, event_number: int, deltas: list[float]) -> pd.DataFrame:
    rows = []
    for index, delta in enumerate(deltas, start=1):
        row = valid_frame().iloc[0].copy()
        row["sample_id"] = f"2024-{event_number:02d}-R:1:1:{index}"
        row["event_id"] = f"2024-{event_number:02d}-R"
        row["event_name"] = f"Event {event_number} Grand Prix"
        row["round_number"] = event_number
        row["split"] = split
        row["lap_number"] = index
        row["stint_lap_index"] = index
        row["tyre_life_laps"] = float(index)
        row["compound"] = "HARD" if index <= 3 else "SOFT"
        row["current_lap_time_seconds"] = 90.0 + index
        row["next_lap_delta_seconds"] = delta
        row["next_lap_time_seconds"] = row["current_lap_time_seconds"] + delta
        rows.append(row)
    return pd.DataFrame(rows, columns=valid_frame().columns).reset_index(drop=True)


def _config(tmp_path: Path) -> BaselineConfig:
    train_path = tmp_path / "train.csv"
    validation_path = tmp_path / "validation.csv"
    _frame("train", 1, [0.1, 0.3, 0.5, -0.2]).to_csv(train_path, index=False)
    _frame("validation", 2, [0.2, 0.2, 0.2, -0.1]).to_csv(validation_path, index=False)
    manifest_path = tmp_path / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "dataset_sha256": "d" * 64,
                "outputs": [
                    {
                        "split": "train",
                        "path": train_path.as_posix(),
                        "sha256": _sha256(train_path),
                    },
                    {
                        "split": "validation",
                        "path": validation_path.as_posix(),
                        "sha256": _sha256(validation_path),
                    },
                    {
                        "split": "test",
                        "path": (tmp_path / "must-not-be-read.csv").as_posix(),
                        "sha256": "0" * 64,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return BaselineConfig(
        schema_version=1,
        experiment_version="test-v1",
        source_dataset_manifest=manifest_path,
        fit_split="train",
        evaluation_split="validation",
        target_column="next_lap_time_seconds",
        median_degradation=MedianDegradationConfig(
            group_columns=("compound", "tyre_age_band"),
            tyre_age_bin_edges=(0, 3, 5),
            minimum_group_samples=2,
            fallback_order=("compound", "global"),
        ),
        outputs=BaselineOutputs(
            metrics=tmp_path / "metrics.json",
            per_event_metrics=tmp_path / "per-event.csv",
            experiment_manifest=tmp_path / "experiment.json",
            model_report=tmp_path / "model-report.md",
        ),
        source_path="configs/baseline.yaml",
        source_sha256="a" * 64,
    )


def test_median_baseline_uses_group_then_fallback_chain() -> None:
    training = _frame("train", 1, [0.1, 0.3, 0.5, -0.2])
    model = MedianDegradationBaseline.fit(training, edges=(0, 3, 5), minimum=2)
    rows = _frame("validation", 2, [0.0, 0.0, 0.0, 0.0]).iloc[[0, 3]].copy()
    rows.loc[rows.index[1], "compound"] = "UNKNOWN"

    predicted, sources = model.predict(rows)

    assert predicted.iloc[0] == pytest.approx(
        rows.iloc[0]["current_lap_time_seconds"] + 0.3
    )
    assert sources.tolist() == ["compound_tyre_age_band", "global"]


def test_evaluation_is_deterministic_and_never_loads_test(tmp_path: Path) -> None:
    config = _config(tmp_path)

    result = run_baseline_evaluation(config)
    first_hashes = {
        path.name: _sha256(path)
        for path in (
            config.outputs.metrics,
            config.outputs.per_event_metrics,
            config.outputs.experiment_manifest,
            config.outputs.model_report,
        )
    }
    repeated = run_baseline_evaluation(config)

    assert result == repeated
    assert result.training_rows == 4
    assert result.validation_rows == 4
    assert result.frozen_test_loaded is False
    assert first_hashes == {
        path.name: _sha256(path)
        for path in (
            config.outputs.metrics,
            config.outputs.per_event_metrics,
            config.outputs.experiment_manifest,
            config.outputs.model_report,
        )
    }
    manifest = json.loads(config.outputs.experiment_manifest.read_text())
    metrics = json.loads(config.outputs.metrics.read_text())
    assert manifest["frozen_test_loaded"] is False
    assert manifest["evaluation"]["event_ids"] == ["2024-02-R"]
    assert (
        metrics["candidate_selection_gate"]["minimum_macro_event_mae_reduction_percent"]
        == 5.0
    )


def test_evaluation_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    config = _config(tmp_path)
    payload = json.loads(config.source_dataset_manifest.read_text())
    payload["outputs"][1]["sha256"] = "0" * 64
    config.source_dataset_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BaselineEvaluationError, match="manifest hash"):
        run_baseline_evaluation(config)
