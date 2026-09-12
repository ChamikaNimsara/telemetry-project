"""Tests for validated event configuration loading."""

from pathlib import Path

import pytest

from telemetry_project.data.event_config import EventConfigError, load_event_config

VALID_CONFIG = """\
schema_version: 1
season: 2024
session: R
splits:
  train: [Bahrain]
  validation: [Spain]
  test: [Abu Dhabi]
"""


def test_load_event_config_normalizes_requests(tmp_path: Path) -> None:
    path = tmp_path / "events.yaml"
    path.write_text(VALID_CONFIG, encoding="utf-8")

    config = load_event_config(path)

    assert config.schema_version == 1
    assert len(config.source_sha256) == 64
    assert [event.event for event in config.events] == ["Bahrain", "Spain", "Abu Dhabi"]
    assert [event.split for event in config.events] == ["train", "validation", "test"]
    assert all(event.year == 2024 and event.session == "R" for event in config.events)


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("- not\n- a mapping\n", "root.*mapping"),
        (
            VALID_CONFIG.replace("schema_version: 1", "schema_version: 2"),
            "Unsupported.*schema version",
        ),
        (
            VALID_CONFIG.replace("season: 2024", "season: twenty-twenty-four"),
            "season.*integer",
        ),
        (
            VALID_CONFIG.replace("session: R", "session: ''"),
            "session.*non-empty string",
        ),
        (VALID_CONFIG.replace("splits:\n", "splits: []\n"), "Invalid YAML"),
        (
            VALID_CONFIG.replace("  train: [Bahrain]", "  train: []"),
            "splits.train.*non-empty list",
        ),
    ],
)
def test_load_event_config_rejects_invalid_fields(
    tmp_path: Path, document: str, message: str
) -> None:
    path = tmp_path / "events.yaml"
    path.write_text(document, encoding="utf-8")

    with pytest.raises(EventConfigError, match=message):
        load_event_config(path)


def test_load_event_config_rejects_duplicate_event(tmp_path: Path) -> None:
    path = tmp_path / "events.yaml"
    path.write_text(VALID_CONFIG.replace("Spain", "bahrain"), encoding="utf-8")

    with pytest.raises(EventConfigError, match="appears more than once"):
        load_event_config(path)


def test_load_event_config_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(EventConfigError, match="Unable to read"):
        load_event_config(tmp_path / "missing.yaml")


def test_load_event_config_reports_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "events.yaml"
    path.write_text("splits: [unterminated", encoding="utf-8")

    with pytest.raises(EventConfigError, match="Invalid YAML"):
        load_event_config(path)
