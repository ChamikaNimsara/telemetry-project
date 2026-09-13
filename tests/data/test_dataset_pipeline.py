"""End-to-end tests for deterministic dataset assembly."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import Mock

import pandas as pd
import pytest

from telemetry_project.data.dataset_config import (
    DatasetConfig,
    EligibilityConfig,
    OutputConfig,
)
from telemetry_project.data.dataset_pipeline import DatasetBuildError, build_dataset
from telemetry_project.data.event_config import load_event_config

from .test_cleaning_features import lap_frame, weather_frame


class FakeLaps(pd.DataFrame):  # type: ignore[misc]
    """Pandas frame exposing the FastF1 lap-weather convenience method."""

    _metadata: ClassVar[list[str]] = ["weather"]

    @property
    def _constructor(self) -> type[FakeLaps]:
        return FakeLaps

    def get_weather_data(self) -> pd.DataFrame:
        return self.weather.copy()


class FakeSession:
    def __init__(self) -> None:
        self.laps = FakeLaps(lap_frame())
        self.laps.weather = weather_frame()
        self.load = Mock()


def configured_build(tmp_path: Path) -> tuple[DatasetConfig, list[dict[str, Any]]]:
    event_path = tmp_path / "events.yaml"
    event_path.write_text(
        """schema_version: 1
season: 2024
session: R
splits:
  train: [Alpha]
  validation: [Bravo]
  test: [Charlie]
""",
        encoding="utf-8",
    )
    event_config = load_event_config(event_path)
    records = [
        {
            "year": 2024,
            "requested_event": name,
            "resolved_event": f"{name} Grand Prix",
            "round_number": number,
            "session_code": "R",
            "split": split,
            "source_id": f"/static/2024/{name.lower()}/",
            "status": "success",
        }
        for number, (name, split) in enumerate(
            [("Alpha", "train"), ("Bravo", "validation"), ("Charlie", "test")],
            start=1,
        )
    ]
    manifest_path = tmp_path / "acquisition.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_schema_version": 1,
                "event_config_sha256": event_config.source_sha256,
                "events": records,
            }
        ),
        encoding="utf-8",
    )
    config = DatasetConfig(
        schema_version=1,
        dataset_version="test-v1",
        source_event_config=event_path,
        source_acquisition_manifest=manifest_path,
        eligibility=EligibilityConfig(
            slick_compounds=frozenset({"MEDIUM"}),
            allowed_track_status=frozenset({"1"}),
            require_accurate_lap=True,
            exclude_deleted_laps=True,
            exclude_pit_in_laps=True,
            exclude_pit_out_laps=True,
            require_dry_weather=True,
            require_weather_coverage=True,
            minimum_consecutive_eligible_laps=3,
        ),
        outputs=OutputConfig(
            processed_directory=tmp_path / "processed",
            dataset_manifest=tmp_path / "dataset-manifest.json",
            split_manifest=tmp_path / "split-manifest.json",
            audit_table=tmp_path / "audit.csv",
            quality_report=tmp_path / "quality.md",
        ),
        source_path="configs/test-dataset.yaml",
        source_sha256="b" * 64,
    )
    return config, records


def test_build_is_deterministic_and_writes_traceable_outputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config, records = configured_build(tmp_path)
    sessions = [FakeSession() for _ in records]
    get_session = Mock(side_effect=sessions)
    monkeypatch.setattr("fastf1.get_session", get_session)
    monkeypatch.setattr("fastf1.Cache.enable_cache", Mock())
    monkeypatch.setattr("fastf1.Cache.offline_mode", Mock())

    first = build_dataset(config, cache_dir=tmp_path / "cache", offline=True)
    first_bytes = (
        config.outputs.processed_directory / "analysis-dataset.csv"
    ).read_bytes()
    get_session.side_effect = [FakeSession() for _ in records]
    second = build_dataset(config, cache_dir=tmp_path / "cache", offline=True)

    assert first == second
    assert first.events == 3
    assert first.samples == 12
    assert first.train_samples == first.validation_samples == first.test_samples == 4
    assert (
        config.outputs.processed_directory / "analysis-dataset.csv"
    ).read_bytes() == first_bytes
    dataset_manifest = json.loads(config.outputs.dataset_manifest.read_text())
    split_manifest = json.loads(config.outputs.split_manifest.read_text())
    assert dataset_manifest["dataset_sha256"] == first.dataset_sha256
    assert dataset_manifest["target_columns"] == [
        "next_lap_time_seconds",
        "next_lap_delta_seconds",
    ]
    assert split_manifest["splits"]["test"]["event_ids"] == ["2024-03-R"]
    assert "Target and Leakage Review" in config.outputs.quality_report.read_text()
    for session in sessions:
        session.load.assert_called_once_with(
            laps=True, telemetry=False, weather=True, messages=False
        )


def test_build_rejects_failed_acquisition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config, _ = configured_build(tmp_path)
    payload = json.loads(config.source_acquisition_manifest.read_text())
    payload["events"][0]["status"] = "failed"
    config.source_acquisition_manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr("fastf1.Cache.enable_cache", Mock())

    with pytest.raises(DatasetBuildError, match="unsuccessful event"):
        build_dataset(config, cache_dir=tmp_path / "cache")


def test_build_rejects_manifest_from_different_event_config(tmp_path: Path) -> None:
    config, _ = configured_build(tmp_path)
    payload = json.loads(config.source_acquisition_manifest.read_text())
    payload["event_config_sha256"] = "0" * 64
    config.source_acquisition_manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DatasetBuildError, match="does not match"):
        build_dataset(config, cache_dir=tmp_path / "cache")
