"""Load and validate the validation-only baseline experiment policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class BaselineConfigError(ValueError):
    """Raised when baseline configuration is invalid or leakage-prone."""


@dataclass(frozen=True, slots=True)
class BaselineOutputs:
    """Repository-relative baseline artifacts."""

    metrics: Path
    per_event_metrics: Path
    experiment_manifest: Path
    model_report: Path


@dataclass(frozen=True, slots=True)
class MedianDegradationConfig:
    """Training-median grouping and fallback policy."""

    group_columns: tuple[str, ...]
    tyre_age_bin_edges: tuple[int, ...]
    minimum_group_samples: int
    fallback_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BaselineConfig:
    """Validated baseline configuration and content fingerprint."""

    schema_version: int
    experiment_version: str
    source_dataset_manifest: Path
    fit_split: str
    evaluation_split: str
    target_column: str
    median_degradation: MedianDegradationConfig
    outputs: BaselineOutputs
    source_path: str
    source_sha256: str


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise BaselineConfigError(f"'{field}' must be a mapping with string keys.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BaselineConfigError(f"'{field}' must be a non-empty string.")
    return value.strip()


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise BaselineConfigError(f"'{field}' must be a non-empty list.")
    result = tuple(_string(item, field) for item in value)
    if len(set(result)) != len(result):
        raise BaselineConfigError(f"'{field}' must not contain duplicates.")
    return result


def load_baseline_config(path: Path) -> BaselineConfig:
    """Read YAML and enforce the frozen train/validation boundary."""
    try:
        content = path.read_bytes()
        loaded: object = yaml.safe_load(content)
    except OSError as error:
        raise BaselineConfigError(
            f"Unable to read baseline config '{path}': {error}"
        ) from error
    except yaml.YAMLError as error:
        raise BaselineConfigError(
            f"Invalid YAML in baseline config '{path}': {error}"
        ) from error

    root = _mapping(loaded, "root")
    if root.get("schema_version") != 1:
        raise BaselineConfigError("Baseline configuration schema version must be 1.")
    fit_split = _string(root.get("fit_split"), "fit_split")
    evaluation_split = _string(root.get("evaluation_split"), "evaluation_split")
    if (fit_split, evaluation_split) != ("train", "validation"):
        raise BaselineConfigError(
            "US-06 must fit on 'train' and evaluate only on 'validation'."
        )
    target = _string(root.get("target_column"), "target_column")
    if target != "next_lap_time_seconds":
        raise BaselineConfigError("US-06 target must be 'next_lap_time_seconds'.")

    median = _mapping(
        root.get("training_median_degradation"), "training_median_degradation"
    )
    groups = _string_list(median.get("group_columns"), "group_columns")
    if groups != ("compound", "tyre_age_band"):
        raise BaselineConfigError(
            "Median degradation groups must be compound then tyre_age_band."
        )
    edge_values = median.get("tyre_age_bin_edges")
    if (
        not isinstance(edge_values, list)
        or len(edge_values) < 3
        or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in edge_values
        )
    ):
        raise BaselineConfigError(
            "'tyre_age_bin_edges' must contain at least 3 integers."
        )
    edges = tuple(edge_values)
    if tuple(sorted(set(edges))) != edges:
        raise BaselineConfigError("'tyre_age_bin_edges' must be strictly increasing.")
    minimum = median.get("minimum_group_samples")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise BaselineConfigError("'minimum_group_samples' must be a positive integer.")
    fallbacks = _string_list(median.get("fallback_order"), "fallback_order")
    if fallbacks != ("compound", "global"):
        raise BaselineConfigError("Fallback order must be compound then global.")

    output_values = _mapping(root.get("outputs"), "outputs")
    return BaselineConfig(
        schema_version=1,
        experiment_version=_string(
            root.get("experiment_version"), "experiment_version"
        ),
        source_dataset_manifest=Path(
            _string(root.get("source_dataset_manifest"), "source_dataset_manifest")
        ),
        fit_split=fit_split,
        evaluation_split=evaluation_split,
        target_column=target,
        median_degradation=MedianDegradationConfig(
            group_columns=groups,
            tyre_age_bin_edges=edges,
            minimum_group_samples=minimum,
            fallback_order=fallbacks,
        ),
        outputs=BaselineOutputs(
            metrics=Path(_string(output_values.get("metrics"), "outputs.metrics")),
            per_event_metrics=Path(
                _string(
                    output_values.get("per_event_metrics"), "outputs.per_event_metrics"
                )
            ),
            experiment_manifest=Path(
                _string(
                    output_values.get("experiment_manifest"),
                    "outputs.experiment_manifest",
                )
            ),
            model_report=Path(
                _string(output_values.get("model_report"), "outputs.model_report")
            ),
        ),
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
