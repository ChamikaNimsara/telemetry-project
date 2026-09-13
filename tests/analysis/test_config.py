"""Tests for the safe exploratory-analysis configuration."""

from pathlib import Path

import pytest

from telemetry_project.analysis.config import (
    AnalysisConfigError,
    load_analysis_config,
)


def test_repository_analysis_config_excludes_frozen_test() -> None:
    config = load_analysis_config(Path("configs/analysis.yaml"))

    assert config.include_splits == ("train", "validation")
    assert config.random_seed == 20260913
    assert len(config.tyre_age_bin_edges) == 8


def test_analysis_config_rejects_test_split(tmp_path: Path) -> None:
    source = Path("configs/analysis.yaml").read_text(encoding="utf-8")
    path = tmp_path / "analysis.yaml"
    path.write_text(
        source.replace("  - validation", "  - validation\n  - test"),
        encoding="utf-8",
    )

    with pytest.raises(AnalysisConfigError, match="only train and validation"):
        load_analysis_config(path)
