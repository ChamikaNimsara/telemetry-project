"""Tests for the versioned dataset configuration."""

from pathlib import Path

import pytest

from telemetry_project.data.dataset_config import (
    DatasetConfigError,
    load_dataset_config,
)


def test_repository_dataset_config_loads() -> None:
    config = load_dataset_config(Path("configs/dataset.yaml"))

    assert config.dataset_version == "1.0.0"
    assert config.eligibility.minimum_consecutive_eligible_laps == 3
    assert config.eligibility.slick_compounds == {"SOFT", "MEDIUM", "HARD"}
    assert len(config.source_sha256) == 64


def test_dataset_config_rejects_short_minimum(tmp_path: Path) -> None:
    path = tmp_path / "dataset.yaml"
    source = Path("configs/dataset.yaml").read_text(encoding="utf-8")
    path.write_text(
        source.replace(
            "minimum_consecutive_eligible_laps: 3",
            "minimum_consecutive_eligible_laps: 1",
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetConfigError, match="integer >= 2"):
        load_dataset_config(path)
