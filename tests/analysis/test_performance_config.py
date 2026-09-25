"""Tests for race-performance configuration."""

from pathlib import Path

import pytest

from telemetry_project.analysis.performance_config import (
    PerformanceConfigError,
    load_performance_config,
)


def test_repository_performance_config_loads_specific_comparison() -> None:
    config = load_performance_config(Path("configs/race-performance.yaml"))

    assert config.session.year == 2024
    assert config.session.event == "Abu Dhabi"
    assert config.session.session == "Q"
    assert config.drivers.reference == "NOR"
    assert config.drivers.reference_name == "Lando Norris"
    assert config.drivers.comparison == "PIA"
    assert len(config.corners) == 16
    assert config.corners[0].label == "T1"
    assert config.corners[-1].label == "T16"


@pytest.mark.parametrize(
    "replacement, message",
    [
        ("comparison: PIA", "comparison: NOR"),
        ("session: Q", "session: FP1"),
        ("distance_step_m: 5", "distance_step_m: 0"),
        ("throttle_pickup_percent: 90", "throttle_pickup_percent: 101"),
    ],
)
def test_performance_config_rejects_invalid_policy(
    tmp_path: Path, replacement: str, message: str
) -> None:
    source = Path("configs/race-performance.yaml").read_text(encoding="utf-8")
    path = tmp_path / "performance.yaml"
    path.write_text(source.replace(replacement, message), encoding="utf-8")

    with pytest.raises(PerformanceConfigError):
        load_performance_config(path)


def test_performance_config_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PerformanceConfigError, match="Unable to read"):
        load_performance_config(tmp_path / "missing.yaml")
