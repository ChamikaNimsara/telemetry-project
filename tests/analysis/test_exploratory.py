"""Tests for development-only exploratory analysis and figure generation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from telemetry_project.analysis.config import AnalysisConfig, AnalysisOutputs
from telemetry_project.analysis.exploratory import (
    ExploratoryAnalysisError,
    build_event_summary,
    build_tyre_age_profile,
    run_exploratory_analysis,
)
from tests.data.test_schema import valid_frame


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def development_frame(split: str, event_number: int) -> pd.DataFrame:
    rows = []
    for index, compound in enumerate(("HARD", "MEDIUM", "SOFT"), start=1):
        row = valid_frame().iloc[0].copy()
        row["sample_id"] = f"2024-{event_number:02d}-R:1:1:{index}"
        row["event_id"] = f"2024-{event_number:02d}-R"
        row["event_name"] = f"Event {event_number} Grand Prix"
        row["round_number"] = event_number
        row["split"] = split
        row["compound"] = compound
        row["lap_number"] = index
        row["stint_lap_index"] = index
        row["tyre_life_laps"] = float(index * 5)
        row["current_lap_time_seconds"] = 89.0 + index
        row["next_lap_time_seconds"] = 89.5 + index
        row["next_lap_delta_seconds"] = 0.5
        if index > 1:
            row["previous_lap_time_seconds"] = 88.0 + index
            row["previous_lap_delta_seconds"] = 1.0
        rows.append(row)
    return pd.DataFrame(rows, columns=valid_frame().columns)


def analysis_config(tmp_path: Path) -> AnalysisConfig:
    train_path = tmp_path / "train.csv"
    validation_path = tmp_path / "validation.csv"
    development_frame("train", 1).to_csv(train_path, index=False)
    development_frame("validation", 2).to_csv(validation_path, index=False)
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
    return AnalysisConfig(
        schema_version=1,
        analysis_version="test-v1",
        source_dataset_manifest=manifest_path,
        include_splits=("train", "validation"),
        random_seed=42,
        scatter_rows_per_event=3,
        tyre_age_bin_edges=(0, 5, 10, 15, 20),
        outputs=AnalysisOutputs(
            report=tmp_path / "exploratory.md",
            figure_directory=tmp_path / "figures",
            event_summary=tmp_path / "event-summary.csv",
            analysis_manifest=tmp_path / "analysis-manifest.json",
        ),
        source_path="configs/analysis.yaml",
        source_sha256="a" * 64,
    )


def test_summary_and_profile_are_event_and_stint_aware() -> None:
    data = pd.concat(
        [development_frame("train", 1), development_frame("validation", 2)],
        ignore_index=True,
    )

    event_summary = build_event_summary(data)
    age_profile = build_tyre_age_profile(data, (0, 5, 10, 15, 20))

    assert event_summary["samples"].tolist() == [3, 3]
    assert event_summary["persistence_mae_seconds"].tolist() == [0.5, 0.5]
    assert set(age_profile["compound"]) == {"HARD", "MEDIUM", "SOFT"}
    assert age_profile["samples"].sum() == 6


def test_analysis_writes_four_figures_without_loading_test(
    tmp_path: Path,
) -> None:
    config = analysis_config(tmp_path)

    result = run_exploratory_analysis(config)
    first_hashes = {
        path.name: _sha256(path) for path in config.outputs.figure_directory.iterdir()
    }
    repeated = run_exploratory_analysis(config)

    assert result == repeated
    assert result.development_rows == 6
    assert result.events == 2
    assert result.figures == 4
    assert len(first_hashes) == 4
    assert first_hashes == {
        path.name: _sha256(path) for path in config.outputs.figure_directory.iterdir()
    }
    report = config.outputs.report.read_text(encoding="utf-8")
    assert "frozen test rows were not loaded" in report
    assert "does not establish model performance" in report
    manifest = json.loads(config.outputs.analysis_manifest.read_text())
    assert manifest["frozen_test_loaded"] is False
    assert len(manifest["event_ids"]) == 2


def test_analysis_rejects_hash_mismatch(tmp_path: Path) -> None:
    config = analysis_config(tmp_path)
    payload = json.loads(config.source_dataset_manifest.read_text())
    payload["outputs"][0]["sha256"] = "0" * 64
    config.source_dataset_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExploratoryAnalysisError, match="manifest hash"):
        run_exploratory_analysis(config)
