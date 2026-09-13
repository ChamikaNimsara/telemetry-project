"""Configuration contracts for candidate selection and final evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class ModelConfigError(ValueError):
    """Raised when a model experiment configuration violates the frozen policy."""


EXPECTED_CANDIDATES = (
    "two_lap_mean",
    "pace_reversion",
    "pace_reversion_compound_tyre_age",
)


@dataclass(frozen=True, slots=True)
class SelectionOutputs:
    """Candidate selection artifacts."""

    candidate_metrics: Path
    candidate_per_event_metrics: Path
    selection_manifest: Path
    final_model_config: Path


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    """Frozen training/validation experiment configuration."""

    experiment_version: str
    source_dataset_manifest: Path
    baseline_metrics: Path
    baseline_per_event_metrics: Path
    fit_split: str
    evaluation_split: str
    target_column: str
    random_seed: int
    candidates: tuple[str, ...]
    two_lap_current_weight: float
    previous_delta_bin_edges: tuple[float, ...]
    tyre_age_bin_edges: tuple[int, ...]
    minimum_group_samples: int
    outputs: SelectionOutputs
    source_path: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class FinalOutputs:
    """Final held-out evaluation artifacts."""

    predictions: Path
    metrics: Path
    per_event_metrics: Path
    condition_metrics: Path
    experiment_manifest: Path
    model_report: Path
    figure_directory: Path


@dataclass(frozen=True, slots=True)
class FinalModelConfig:
    """Frozen selected method and held-out evaluation policy."""

    experiment_version: str
    selected_method: str
    previous_delta_bin_edges: tuple[float, ...]
    minimum_group_samples: int
    fit_splits: tuple[str, ...]
    evaluation_split: str
    random_seed: int
    source_dataset_manifest: Path
    source_selection_config: Path
    source_selection_config_sha256: str
    candidate_metrics: Path
    candidate_metrics_sha256: str
    baseline_config: Path
    baseline_config_sha256: str
    model_implementation: Path
    model_implementation_sha256: str
    outputs: FinalOutputs
    source_path: str
    source_sha256: str


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelConfigError(f"'{field}' must be a mapping with string keys.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelConfigError(f"'{field}' must be a non-empty string.")
    return value.strip()


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value:
        raise ModelConfigError(f"'{field}' must be a non-empty list.")
    return value


def _edges(value: object, field: str) -> tuple[float, ...]:
    values = _list(value, field)
    if len(values) < 3:
        raise ModelConfigError(f"'{field}' must contain at least 3 numbers.")
    numbers: list[float] = []
    for item in values:
        if not isinstance(item, (int, float)) or isinstance(item, bool):
            raise ModelConfigError(f"'{field}' must contain at least 3 numbers.")
        numbers.append(float(item))
    result = tuple(numbers)
    if tuple(sorted(set(result))) != result:
        raise ModelConfigError(f"'{field}' must be strictly increasing.")
    return result


def _load_yaml(path: Path) -> tuple[dict[str, object], bytes]:
    try:
        content = path.read_bytes()
        loaded: object = yaml.safe_load(content)
    except OSError as error:
        raise ModelConfigError(
            f"Unable to read model config '{path}': {error}"
        ) from error
    except yaml.YAMLError as error:
        raise ModelConfigError(
            f"Invalid YAML in model config '{path}': {error}"
        ) from error
    return _mapping(loaded, "root"), content


def _positive_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ModelConfigError(f"'{field}' must be a positive integer.")
    return value


def load_selection_config(path: Path) -> SelectionConfig:
    """Load the candidate policy and prohibit frozen-test access."""
    root, content = _load_yaml(path)
    if root.get("schema_version") != 1:
        raise ModelConfigError("Model selection schema version must be 1.")
    fit_split = _string(root.get("fit_split"), "fit_split")
    evaluation_split = _string(root.get("evaluation_split"), "evaluation_split")
    if (fit_split, evaluation_split) != ("train", "validation"):
        raise ModelConfigError(
            "Selection must fit on train and evaluate on validation."
        )
    target_column = _string(root.get("target_column"), "target_column")
    if target_column != "next_lap_time_seconds":
        raise ModelConfigError("Selection target must be 'next_lap_time_seconds'.")
    candidates = tuple(
        _string(value, "candidates")
        for value in _list(root.get("candidates"), "candidates")
    )
    if candidates != EXPECTED_CANDIDATES:
        raise ModelConfigError("Candidate names and order must match the frozen set.")
    weight = root.get("two_lap_current_weight")
    if (
        not isinstance(weight, (int, float))
        or isinstance(weight, bool)
        or not 0 < weight < 1
    ):
        raise ModelConfigError("'two_lap_current_weight' must be between 0 and 1.")
    age_edges_raw = _list(root.get("tyre_age_bin_edges"), "tyre_age_bin_edges")
    age_values: list[int] = []
    for value in age_edges_raw:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ModelConfigError("'tyre_age_bin_edges' must contain integers.")
        age_values.append(value)
    age_edges = tuple(age_values)
    if tuple(sorted(set(age_edges))) != age_edges:
        raise ModelConfigError("'tyre_age_bin_edges' must be strictly increasing.")
    outputs = _mapping(root.get("outputs"), "outputs")
    return SelectionConfig(
        experiment_version=_string(
            root.get("experiment_version"), "experiment_version"
        ),
        source_dataset_manifest=Path(
            _string(root.get("source_dataset_manifest"), "source_dataset_manifest")
        ),
        baseline_metrics=Path(
            _string(root.get("baseline_metrics"), "baseline_metrics")
        ),
        baseline_per_event_metrics=Path(
            _string(
                root.get("baseline_per_event_metrics"), "baseline_per_event_metrics"
            )
        ),
        fit_split=fit_split,
        evaluation_split=evaluation_split,
        target_column=target_column,
        random_seed=_positive_integer(root.get("random_seed"), "random_seed"),
        candidates=candidates,
        two_lap_current_weight=float(weight),
        previous_delta_bin_edges=_edges(
            root.get("previous_delta_bin_edges"), "previous_delta_bin_edges"
        ),
        tyre_age_bin_edges=age_edges,
        minimum_group_samples=_positive_integer(
            root.get("minimum_group_samples"), "minimum_group_samples"
        ),
        outputs=SelectionOutputs(
            candidate_metrics=Path(
                _string(outputs.get("candidate_metrics"), "outputs.candidate_metrics")
            ),
            candidate_per_event_metrics=Path(
                _string(
                    outputs.get("candidate_per_event_metrics"),
                    "outputs.candidate_per_event_metrics",
                )
            ),
            selection_manifest=Path(
                _string(outputs.get("selection_manifest"), "outputs.selection_manifest")
            ),
            final_model_config=Path(
                _string(outputs.get("final_model_config"), "outputs.final_model_config")
            ),
        ),
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )


def load_final_model_config(path: Path) -> FinalModelConfig:
    """Load the immutable selected method and require a test-only evaluation."""
    root, content = _load_yaml(path)
    if root.get("schema_version") != 1:
        raise ModelConfigError("Final model schema version must be 1.")
    selected = _string(root.get("selected_method"), "selected_method")
    if selected not in EXPECTED_CANDIDATES:
        raise ModelConfigError("Final model contains an unsupported method.")
    fit_splits = tuple(
        _string(value, "fit_splits")
        for value in _list(root.get("fit_splits"), "fit_splits")
    )
    if fit_splits != ("train", "validation") or root.get("evaluation_split") != "test":
        raise ModelConfigError(
            "Final evaluation must refit on train+validation and evaluate test."
        )
    outputs = _mapping(root.get("outputs"), "outputs")
    return FinalModelConfig(
        experiment_version=_string(
            root.get("experiment_version"), "experiment_version"
        ),
        selected_method=selected,
        previous_delta_bin_edges=_edges(
            root.get("previous_delta_bin_edges"), "previous_delta_bin_edges"
        ),
        minimum_group_samples=_positive_integer(
            root.get("minimum_group_samples"), "minimum_group_samples"
        ),
        fit_splits=fit_splits,
        evaluation_split="test",
        random_seed=_positive_integer(root.get("random_seed"), "random_seed"),
        source_dataset_manifest=Path(
            _string(root.get("source_dataset_manifest"), "source_dataset_manifest")
        ),
        source_selection_config=Path(
            _string(root.get("source_selection_config"), "source_selection_config")
        ),
        source_selection_config_sha256=_string(
            root.get("source_selection_config_sha256"),
            "source_selection_config_sha256",
        ),
        candidate_metrics=Path(
            _string(root.get("candidate_metrics"), "candidate_metrics")
        ),
        candidate_metrics_sha256=_string(
            root.get("candidate_metrics_sha256"), "candidate_metrics_sha256"
        ),
        baseline_config=Path(_string(root.get("baseline_config"), "baseline_config")),
        baseline_config_sha256=_string(
            root.get("baseline_config_sha256"), "baseline_config_sha256"
        ),
        model_implementation=Path(
            _string(root.get("model_implementation"), "model_implementation")
        ),
        model_implementation_sha256=_string(
            root.get("model_implementation_sha256"),
            "model_implementation_sha256",
        ),
        outputs=FinalOutputs(
            predictions=Path(
                _string(outputs.get("predictions"), "outputs.predictions")
            ),
            metrics=Path(_string(outputs.get("metrics"), "outputs.metrics")),
            per_event_metrics=Path(
                _string(outputs.get("per_event_metrics"), "outputs.per_event_metrics")
            ),
            condition_metrics=Path(
                _string(outputs.get("condition_metrics"), "outputs.condition_metrics")
            ),
            experiment_manifest=Path(
                _string(
                    outputs.get("experiment_manifest"),
                    "outputs.experiment_manifest",
                )
            ),
            model_report=Path(
                _string(outputs.get("model_report"), "outputs.model_report")
            ),
            figure_directory=Path(
                _string(outputs.get("figure_directory"), "outputs.figure_directory")
            ),
        ),
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
