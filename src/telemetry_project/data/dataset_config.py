"""Load the versioned analysis-dataset policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class DatasetConfigError(ValueError):
    """Raised when the dataset configuration is invalid."""


@dataclass(frozen=True, slots=True)
class EligibilityConfig:
    """Rules applied to each current and target lap."""

    slick_compounds: frozenset[str]
    allowed_track_status: frozenset[str]
    require_accurate_lap: bool
    exclude_deleted_laps: bool
    exclude_pit_in_laps: bool
    exclude_pit_out_laps: bool
    require_dry_weather: bool
    require_weather_coverage: bool
    minimum_consecutive_eligible_laps: int


@dataclass(frozen=True, slots=True)
class OutputConfig:
    """Repository-relative generated output locations."""

    processed_directory: Path
    dataset_manifest: Path
    split_manifest: Path
    audit_table: Path
    quality_report: Path


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    """Validated dataset policy and its content fingerprint."""

    schema_version: int
    dataset_version: str
    source_event_config: Path
    source_acquisition_manifest: Path
    eligibility: EligibilityConfig
    outputs: OutputConfig
    source_path: str
    source_sha256: str


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise DatasetConfigError(f"'{field}' must be a mapping with string keys.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetConfigError(f"'{field}' must be a non-empty string.")
    return value.strip()


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise DatasetConfigError(f"'{field}' must be true or false.")
    return value


def _string_set(value: object, field: str) -> frozenset[str]:
    if not isinstance(value, list) or not value:
        raise DatasetConfigError(f"'{field}' must be a non-empty list.")
    strings = frozenset(_string(item, field).upper() for item in value)
    if len(strings) != len(value):
        raise DatasetConfigError(f"'{field}' must not contain duplicates.")
    return strings


def load_dataset_config(path: Path) -> DatasetConfig:
    """Read and validate a dataset YAML file."""
    try:
        content = path.read_bytes()
        loaded: object = yaml.safe_load(content)
    except OSError as error:
        raise DatasetConfigError(
            f"Unable to read dataset config '{path}': {error}"
        ) from error
    except yaml.YAMLError as error:
        raise DatasetConfigError(
            f"Invalid YAML in dataset config '{path}': {error}"
        ) from error

    root = _mapping(loaded, "root")
    schema_version = root.get("schema_version")
    if schema_version != 1:
        raise DatasetConfigError(
            f"Unsupported dataset configuration schema version: {schema_version}"
        )
    dataset_version = _string(root.get("dataset_version"), "dataset_version")
    eligibility_values = _mapping(root.get("eligibility"), "eligibility")
    outputs = _mapping(root.get("outputs"), "outputs")
    minimum = eligibility_values.get("minimum_consecutive_eligible_laps")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 2:
        raise DatasetConfigError(
            "'eligibility.minimum_consecutive_eligible_laps' must be an integer >= 2."
        )

    eligibility = EligibilityConfig(
        slick_compounds=_string_set(
            eligibility_values.get("slick_compounds"), "eligibility.slick_compounds"
        ),
        allowed_track_status=_string_set(
            eligibility_values.get("allowed_track_status"),
            "eligibility.allowed_track_status",
        ),
        require_accurate_lap=_boolean(
            eligibility_values.get("require_accurate_lap"),
            "eligibility.require_accurate_lap",
        ),
        exclude_deleted_laps=_boolean(
            eligibility_values.get("exclude_deleted_laps"),
            "eligibility.exclude_deleted_laps",
        ),
        exclude_pit_in_laps=_boolean(
            eligibility_values.get("exclude_pit_in_laps"),
            "eligibility.exclude_pit_in_laps",
        ),
        exclude_pit_out_laps=_boolean(
            eligibility_values.get("exclude_pit_out_laps"),
            "eligibility.exclude_pit_out_laps",
        ),
        require_dry_weather=_boolean(
            eligibility_values.get("require_dry_weather"),
            "eligibility.require_dry_weather",
        ),
        require_weather_coverage=_boolean(
            eligibility_values.get("require_weather_coverage"),
            "eligibility.require_weather_coverage",
        ),
        minimum_consecutive_eligible_laps=minimum,
    )
    output_config = OutputConfig(
        processed_directory=Path(
            _string(outputs.get("processed_directory"), "outputs.processed_directory")
        ),
        dataset_manifest=Path(
            _string(outputs.get("dataset_manifest"), "outputs.dataset_manifest")
        ),
        split_manifest=Path(
            _string(outputs.get("split_manifest"), "outputs.split_manifest")
        ),
        audit_table=Path(_string(outputs.get("audit_table"), "outputs.audit_table")),
        quality_report=Path(
            _string(outputs.get("quality_report"), "outputs.quality_report")
        ),
    )
    return DatasetConfig(
        schema_version=1,
        dataset_version=dataset_version,
        source_event_config=Path(
            _string(root.get("source_event_config"), "source_event_config")
        ),
        source_acquisition_manifest=Path(
            _string(
                root.get("source_acquisition_manifest"),
                "source_acquisition_manifest",
            )
        ),
        eligibility=eligibility,
        outputs=output_config,
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
