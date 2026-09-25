"""Tests for distance-aligned race-performance analysis."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from telemetry_project.analysis.performance import (
    LapMetadata,
    PerformanceAnalysisError,
    _select_lap,
    build_corner_metrics,
    build_lap_comparison,
    build_mini_sector_metrics,
    resample_telemetry,
    run_race_performance_analysis,
)
from telemetry_project.analysis.performance_config import (
    Corner,
    DriverConfig,
    PerformanceConfig,
    PerformanceOutputs,
    SessionConfig,
)


def telemetry_frame(*, slower: bool = False) -> pd.DataFrame:
    distance = np.arange(0.0, 601.0, 10.0)
    elapsed = distance / (70.0 if slower else 72.0)
    speed = np.full(len(distance), 250.0)
    speed[(distance >= 250) & (distance <= 350)] = 100 if not slower else 95
    brake = ((distance >= (250 if not slower else 230)) & (distance <= 300)).astype(int)
    throttle = np.full(len(distance), 100.0)
    pickup = 340 if not slower else 360
    throttle[(distance >= 250) & (distance < pickup)] = 30
    return pd.DataFrame(
        {
            "Distance": distance,
            "Time": pd.to_timedelta(elapsed, unit="s"),
            "Speed": speed,
            "Throttle": throttle,
            "Brake": brake,
            "nGear": np.where(speed < 150, 3, 8),
            "RPM": np.where(speed < 150, 9000, 11000),
            "DRS": np.where(distance < 200, 12, 0),
        }
    )


def performance_config(tmp_path: Path) -> PerformanceConfig:
    return PerformanceConfig(
        schema_version=1,
        analysis_version="test",
        session=SessionConfig(2024, "Test Grand Prix", "Q"),
        drivers=DriverConfig("AAA", "Driver Alpha", "BBB", "Driver Beta"),
        distance_step_m=10,
        mini_sector_length_m=200,
        corner_window_before_m=100,
        corner_window_after_m=100,
        brake_lookback_m=100,
        throttle_lookahead_m=100,
        throttle_pickup_percent=90,
        sustained_samples=2,
        corners=(Corner("T1", 300),),
        outputs=PerformanceOutputs(
            report=tmp_path / "report.md",
            engineering_brief=tmp_path / "brief.md",
            figure_directory=tmp_path / "figures",
            corner_table=tmp_path / "tables" / "corners.csv",
            mini_sector_table=tmp_path / "tables" / "mini.csv",
            manifest=tmp_path / "manifest.json",
        ),
        source_path="config.yaml",
        source_sha256="a" * 64,
    )


def test_resampling_and_delta_preserve_sign_convention() -> None:
    reference = resample_telemetry(telemetry_frame(), 10)
    slower = resample_telemetry(telemetry_frame(slower=True), 10)
    comparison = build_lap_comparison(reference, slower)

    assert comparison["distance_m"].is_monotonic_increasing
    assert comparison["delta_seconds"].iloc[0] == pytest.approx(0)
    assert comparison["delta_seconds"].iloc[-1] > 0
    assert set(reference.columns) == {
        "distance_m",
        "elapsed_seconds",
        "speed",
        "throttle",
        "rpm",
        "brake",
        "ngear",
        "drs",
    }


def test_corner_metrics_capture_braking_speed_throttle_and_time(
    tmp_path: Path,
) -> None:
    reference = resample_telemetry(telemetry_frame(), 10)
    slower = resample_telemetry(telemetry_frame(slower=True), 10)
    comparison = build_lap_comparison(reference, slower)

    corners = build_corner_metrics(comparison, performance_config(tmp_path))
    mini_sectors = build_mini_sector_metrics(comparison, 200)

    row = corners.iloc[0]
    assert row["reference_min_speed_delta_kph"] == pytest.approx(5)
    assert row["reference_later_braking_m"] == pytest.approx(20)
    assert row["reference_earlier_throttle_m"] == pytest.approx(20)
    assert row["reference_gain_seconds"] > 0
    assert list(mini_sectors["mini_sector"]) == [1, 2, 3]
    assert "braking" in set(mini_sectors["phase"])


def test_resampling_rejects_incomplete_telemetry() -> None:
    with pytest.raises(PerformanceAnalysisError, match="missing required"):
        resample_telemetry(pd.DataFrame({"Distance": [0, 1]}), 1)


class FakeLap:
    """Small lap double exposing only telemetry retrieval."""

    def __init__(self, telemetry: pd.DataFrame) -> None:
        self.telemetry = telemetry

    def get_telemetry(self) -> pd.DataFrame:
        return self.telemetry


class FakeLoc:
    """Boolean-selection double that preserves the fake laps collection."""

    def __init__(self, laps: "FakeDriverLaps") -> None:
        self.laps = laps

    def __getitem__(self, _key: object) -> "FakeDriverLaps":
        return self.laps


class FakeSelectedLap(dict[str, object]):
    """Mapping-shaped fastest-lap double."""


class FakeDriverLaps:
    """Minimal FastF1 Laps double for selection-policy coverage."""

    empty = False
    columns = ("IsAccurate", "Deleted")

    def __init__(self) -> None:
        self.loc = FakeLoc(self)

    def __getitem__(self, key: str) -> pd.Series:
        return pd.Series([True]) if key == "IsAccurate" else pd.Series([False])

    def pick_fastest(self) -> FakeSelectedLap:
        return FakeSelectedLap(
            LapTime=pd.to_timedelta(90.5, unit="s"),
            LapNumber=7.0,
            Compound="SOFT",
        )


def test_lap_selection_keeps_accurate_non_deleted_fastest_lap() -> None:
    session = Mock()
    session.laps.pick_drivers.return_value = FakeDriverLaps()

    _lap, metadata = _select_lap(session, "AAA")

    assert metadata == LapMetadata("AAA", 7, 90.5, "SOFT")


def test_workflow_writes_figures_tables_reports_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = performance_config(tmp_path)
    session = Mock()
    reference_lap = FakeLap(telemetry_frame())
    comparison_lap = FakeLap(telemetry_frame(slower=True))
    selections: dict[str, tuple[Any, LapMetadata]] = {
        "AAA": (reference_lap, LapMetadata("AAA", 3, 8.333, "SOFT")),
        "BBB": (comparison_lap, LapMetadata("BBB", 4, 8.571, "SOFT")),
    }
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.get_session",
        Mock(return_value=session),
    )
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.Cache.enable_cache", Mock()
    )
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.Cache.offline_mode", Mock()
    )
    monkeypatch.setattr(
        "telemetry_project.analysis.performance._select_lap",
        lambda _session, driver: selections[driver],
    )

    summary = run_race_performance_analysis(
        config, cache_dir=tmp_path / "cache", offline=True
    )

    assert summary.reference_advantage_seconds == pytest.approx(0.238)
    assert summary.figures == 3
    assert config.outputs.report.exists()
    assert "observational and non-causal" in config.outputs.report.read_text(
        encoding="utf-8"
    )
    assert config.outputs.engineering_brief.exists()
    assert config.outputs.corner_table.exists()
    manifest = json.loads(config.outputs.manifest.read_text(encoding="utf-8"))
    assert manifest["selected_laps"]["reference"]["driver"] == "AAA"
    assert len(manifest["outputs"]) == 7
    session.load.assert_called_once_with(
        laps=True, telemetry=True, weather=False, messages=False
    )


def test_workflow_wraps_fastf1_loading_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.get_session",
        Mock(side_effect=RuntimeError("source unavailable")),
    )
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.Cache.enable_cache", Mock()
    )
    monkeypatch.setattr(
        "telemetry_project.analysis.performance.fastf1.Cache.offline_mode", Mock()
    )

    with pytest.raises(PerformanceAnalysisError, match="source unavailable"):
        run_race_performance_analysis(
            performance_config(tmp_path), cache_dir=tmp_path / "cache"
        )
