"""Tests for candidate selection and frozen final evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from telemetry_project.modeling.experiments import (
    ModelExperimentError,
    PaceReversionModel,
    evaluate_final,
    select_model,
)
from telemetry_project.modeling.selection_config import (
    FinalModelConfig,
    FinalOutputs,
    ModelConfigError,
    SelectionConfig,
    SelectionOutputs,
    load_final_model_config,
    load_selection_config,
)
from tests.data.test_schema import valid_frame


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frame(split: str, event_number: int) -> pd.DataFrame:
    rows = []
    for index, previous_delta in enumerate((1.0, -1.0, 0.4, -0.4), start=1):
        row = valid_frame().iloc[0].copy()
        current = 90.0 + index
        target_delta = -previous_delta
        row["sample_id"] = f"2024-{event_number:02d}-R:1:1:{index}"
        row["event_id"] = f"2024-{event_number:02d}-R"
        row["event_name"] = f"Event {event_number} Grand Prix"
        row["round_number"] = event_number
        row["split"] = split
        row["lap_number"] = index
        row["stint_lap_index"] = index
        row["tyre_life_laps"] = float(index)
        row["compound"] = ("HARD", "MEDIUM", "SOFT", "HARD")[index - 1]
        row["current_lap_time_seconds"] = current
        row["previous_lap_time_seconds"] = current - previous_delta
        row["previous_lap_delta_seconds"] = previous_delta
        row["next_lap_delta_seconds"] = target_delta
        row["next_lap_time_seconds"] = current + target_delta
        rows.append(row)
    return pd.DataFrame(rows, columns=valid_frame().columns).reset_index(drop=True)


def _dataset_manifest(tmp_path: Path) -> Path:
    outputs = []
    for split, event_number in (("train", 1), ("validation", 2), ("test", 3)):
        path = tmp_path / f"{split}.csv"
        _frame(split, event_number).to_csv(path, index=False)
        outputs.append(
            {"split": split, "path": path.as_posix(), "sha256": _sha256(path)}
        )
    manifest = tmp_path / "dataset.json"
    manifest.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "dataset_sha256": "d" * 64,
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _selection_config(tmp_path: Path) -> SelectionConfig:
    baseline_metrics = tmp_path / "baseline.json"
    baseline_metrics.write_text(
        json.dumps(
            {
                "evaluation_split": "validation",
                "stronger_baseline": "training_median_degradation",
                "stronger_macro_event_mae_seconds": 1.0,
                "candidate_selection_gate": {
                    "maximum_candidate_macro_event_mae_seconds": 10.0,
                    "maximum_per_event_mae_increase_percent": 1000.0,
                },
            }
        ),
        encoding="utf-8",
    )
    baseline_events = tmp_path / "baseline-events.csv"
    pd.DataFrame(
        [
            {
                "baseline": "training_median_degradation",
                "event_id": "2024-02-R",
                "mae_seconds": 1.0,
            }
        ]
    ).to_csv(baseline_events, index=False)
    return SelectionConfig(
        experiment_version="test-v1",
        source_dataset_manifest=_dataset_manifest(tmp_path),
        baseline_metrics=baseline_metrics,
        baseline_per_event_metrics=baseline_events,
        fit_split="train",
        evaluation_split="validation",
        target_column="next_lap_time_seconds",
        random_seed=42,
        candidates=(
            "two_lap_mean",
            "pace_reversion",
            "pace_reversion_compound_tyre_age",
        ),
        two_lap_current_weight=0.5,
        previous_delta_bin_edges=(-120, -2, -1, -0.5, -0.2, 0, 0.2, 0.5, 1, 2, 120),
        tyre_age_bin_edges=(0, 5, 10, 20, 60),
        minimum_group_samples=1,
        outputs=SelectionOutputs(
            candidate_metrics=tmp_path / "candidate.json",
            candidate_per_event_metrics=tmp_path / "candidate-events.csv",
            selection_manifest=tmp_path / "selection-manifest.json",
            final_model_config=tmp_path / "final.yaml",
        ),
        source_path="configs/model-selection.yaml",
        source_sha256="a" * 64,
    )


def test_pace_reversion_uses_training_medians_and_fallbacks() -> None:
    training = _frame("train", 1)
    model = PaceReversionModel.fit(
        training,
        previous_delta_edges=(-120, -0.5, 0, 0.5, 120),
        tyre_age_edges=(0, 5, 10),
        group_columns=(),
        minimum_group_samples=1,
    )
    evaluation = training.iloc[[0]].copy()
    predicted, source = model.predict(evaluation)

    assert predicted.iloc[0] == pytest.approx(90.0)
    assert source.tolist() == ["group"]


def test_selection_is_deterministic_and_does_not_load_test(tmp_path: Path) -> None:
    config = _selection_config(tmp_path)
    manifest = json.loads(config.source_dataset_manifest.read_text())
    Path(manifest["outputs"][2]["path"]).unlink()

    result = select_model(config)
    first_hash = _sha256(config.outputs.candidate_metrics)
    repeated = select_model(config)

    assert result == repeated
    assert result.selected_method == "pace_reversion"
    assert result.frozen_test_loaded is False
    assert _sha256(config.outputs.candidate_metrics) == first_hash
    assert config.outputs.final_model_config.is_file()


def test_final_evaluation_writes_metrics_predictions_and_figures(
    tmp_path: Path,
) -> None:
    selection = _selection_config(tmp_path)
    selected = select_model(selection)
    selection_path = Path("configs/model-selection.yaml")
    baseline_path = Path("configs/baseline.yaml")
    config = FinalModelConfig(
        experiment_version="test-v1",
        selected_method=selected.selected_method,
        previous_delta_bin_edges=selection.previous_delta_bin_edges,
        minimum_group_samples=selection.minimum_group_samples,
        fit_splits=("train", "validation"),
        evaluation_split="test",
        random_seed=42,
        source_dataset_manifest=selection.source_dataset_manifest,
        source_selection_config=selection_path,
        source_selection_config_sha256=_sha256(selection_path),
        candidate_metrics=selection.outputs.candidate_metrics,
        candidate_metrics_sha256=_sha256(selection.outputs.candidate_metrics),
        baseline_config=baseline_path,
        baseline_config_sha256=_sha256(baseline_path),
        model_implementation=Path("src/telemetry_project/modeling/experiments.py"),
        model_implementation_sha256=_sha256(
            Path("src/telemetry_project/modeling/experiments.py")
        ),
        outputs=FinalOutputs(
            predictions=tmp_path / "predictions.csv",
            metrics=tmp_path / "final-metrics.json",
            per_event_metrics=tmp_path / "final-events.csv",
            condition_metrics=tmp_path / "conditions.csv",
            experiment_manifest=tmp_path / "final-manifest.json",
            model_report=tmp_path / "model-report.md",
            figure_directory=tmp_path / "figures",
        ),
        source_path="configs/final-model.yaml",
        source_sha256="f" * 64,
    )

    result = evaluate_final(config)

    assert result.test_rows == 4
    assert config.outputs.predictions.is_file()
    assert len(list(config.outputs.figure_directory.glob("*.png"))) == 3
    assert "test" in config.outputs.metrics.read_text(encoding="utf-8")


def test_final_evaluation_rejects_changed_selection_before_loading_data(
    tmp_path: Path,
) -> None:
    selection = _selection_config(tmp_path)
    select_model(selection)
    config = FinalModelConfig(
        experiment_version="test-v1",
        selected_method="pace_reversion",
        previous_delta_bin_edges=selection.previous_delta_bin_edges,
        minimum_group_samples=1,
        fit_splits=("train", "validation"),
        evaluation_split="test",
        random_seed=42,
        source_dataset_manifest=tmp_path / "must-not-be-read.json",
        source_selection_config=Path("configs/model-selection.yaml"),
        source_selection_config_sha256="0" * 64,
        candidate_metrics=selection.outputs.candidate_metrics,
        candidate_metrics_sha256=_sha256(selection.outputs.candidate_metrics),
        baseline_config=Path("configs/baseline.yaml"),
        baseline_config_sha256=_sha256(Path("configs/baseline.yaml")),
        model_implementation=Path("src/telemetry_project/modeling/experiments.py"),
        model_implementation_sha256=_sha256(
            Path("src/telemetry_project/modeling/experiments.py")
        ),
        outputs=FinalOutputs(
            predictions=tmp_path / "p.csv",
            metrics=tmp_path / "m.json",
            per_event_metrics=tmp_path / "e.csv",
            condition_metrics=tmp_path / "c.csv",
            experiment_manifest=tmp_path / "x.json",
            model_report=tmp_path / "r.md",
            figure_directory=tmp_path / "figures",
        ),
        source_path="configs/final-model.yaml",
        source_sha256="f" * 64,
    )

    with pytest.raises(ModelExperimentError, match="changed after"):
        evaluate_final(config)


def test_committed_model_configs_load_with_frozen_boundaries() -> None:
    selection = load_selection_config(Path("configs/model-selection.yaml"))
    final = load_final_model_config(Path("configs/final-model.yaml"))

    assert selection.evaluation_split == "validation"
    assert final.evaluation_split == "test"
    assert final.fit_splits == ("train", "validation")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("evaluation_split: validation", "evaluation_split: test", "fit on train"),
        (
            "target_column: next_lap_time_seconds",
            "target_column: future",
            "target must be",
        ),
        (
            "two_lap_current_weight: 0.5",
            "two_lap_current_weight: 2.0",
            "between 0 and 1",
        ),
        ("minimum_group_samples: 30", "minimum_group_samples: 0", "positive integer"),
    ],
)
def test_selection_config_rejects_policy_changes(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "selection.yaml"
    content = Path("configs/model-selection.yaml").read_text(encoding="utf-8")
    path.write_text(content.replace(old, new), encoding="utf-8")

    with pytest.raises(ModelConfigError, match=message):
        load_selection_config(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("selected_method: pace_reversion", "selected_method: unknown", "unsupported"),
        ("evaluation_split: test", "evaluation_split: validation", "evaluate test"),
        ("schema_version: 1", "schema_version: 2", "schema version"),
    ],
)
def test_final_config_rejects_policy_changes(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "final.yaml"
    content = Path("configs/final-model.yaml").read_text(encoding="utf-8")
    path.write_text(content.replace(old, new), encoding="utf-8")

    with pytest.raises(ModelConfigError, match=message):
        load_final_model_config(path)
