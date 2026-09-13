"""Tests for the versioned baseline configuration."""

from pathlib import Path

import pytest

from telemetry_project.modeling.baseline_config import (
    BaselineConfigError,
    load_baseline_config,
)


def _write_config(path: Path, *, evaluation_split: str = "validation") -> None:
    path.write_text(
        f"""schema_version: 1
experiment_version: test-v1
source_dataset_manifest: manifest.json
fit_split: train
evaluation_split: {evaluation_split}
target_column: next_lap_time_seconds
training_median_degradation:
  group_columns: [compound, tyre_age_band]
  tyre_age_bin_edges: [0, 5, 10]
  minimum_group_samples: 2
  fallback_order: [compound, global]
outputs:
  metrics: metrics.json
  per_event_metrics: per-event.csv
  experiment_manifest: experiment.json
  model_report: model-report.md
""",
        encoding="utf-8",
    )


def test_load_baseline_config_accepts_frozen_policy(tmp_path: Path) -> None:
    path = tmp_path / "baseline.yaml"
    _write_config(path)

    config = load_baseline_config(path)

    assert config.fit_split == "train"
    assert config.evaluation_split == "validation"
    assert config.median_degradation.minimum_group_samples == 2
    assert len(config.source_sha256) == 64


def test_load_baseline_config_rejects_test_evaluation(tmp_path: Path) -> None:
    path = tmp_path / "baseline.yaml"
    _write_config(path, evaluation_split="test")

    with pytest.raises(BaselineConfigError, match="evaluate only on 'validation'"):
        load_baseline_config(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("schema_version: 1", "schema_version: 2", "schema version"),
        (
            "target_column: next_lap_time_seconds",
            "target_column: future_value",
            "target must be",
        ),
        (
            "group_columns: [compound, tyre_age_band]",
            "group_columns: [driver_number]",
            "groups must be",
        ),
        (
            "tyre_age_bin_edges: [0, 5, 10]",
            "tyre_age_bin_edges: [0, 5, 5]",
            "increasing",
        ),
        (
            "minimum_group_samples: 2",
            "minimum_group_samples: 0",
            "positive integer",
        ),
        (
            "fallback_order: [compound, global]",
            "fallback_order: [global]",
            "Fallback order",
        ),
    ],
)
def test_load_baseline_config_rejects_changed_contract(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "baseline.yaml"
    _write_config(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8"
    )

    with pytest.raises(BaselineConfigError, match=message):
        load_baseline_config(path)


def test_load_baseline_config_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(BaselineConfigError, match="Unable to read"):
        load_baseline_config(tmp_path / "missing.yaml")
