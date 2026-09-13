"""Load and validate the exploratory-analysis policy."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class AnalysisConfigError(ValueError):
    """Raised when exploratory-analysis configuration is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class AnalysisOutputs:
    """Repository-relative public analysis outputs."""

    report: Path
    figure_directory: Path
    event_summary: Path
    analysis_manifest: Path


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """Validated analysis configuration and content fingerprint."""

    schema_version: int
    analysis_version: str
    source_dataset_manifest: Path
    include_splits: tuple[str, ...]
    random_seed: int
    scatter_rows_per_event: int
    tyre_age_bin_edges: tuple[int, ...]
    outputs: AnalysisOutputs
    source_path: str
    source_sha256: str


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AnalysisConfigError(f"'{field}' must be a mapping with string keys.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisConfigError(f"'{field}' must be a non-empty string.")
    return value.strip()


def _positive_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise AnalysisConfigError(f"'{field}' must be a positive integer.")
    return value


def load_analysis_config(path: Path) -> AnalysisConfig:
    """Read the analysis YAML and enforce the frozen-test boundary."""
    try:
        content = path.read_bytes()
        loaded: object = yaml.safe_load(content)
    except OSError as error:
        raise AnalysisConfigError(
            f"Unable to read analysis config '{path}': {error}"
        ) from error
    except yaml.YAMLError as error:
        raise AnalysisConfigError(
            f"Invalid YAML in analysis config '{path}': {error}"
        ) from error

    root = _mapping(loaded, "root")
    if root.get("schema_version") != 1:
        raise AnalysisConfigError("Analysis configuration schema version must be 1.")
    split_values = root.get("include_splits")
    if not isinstance(split_values, list) or not split_values:
        raise AnalysisConfigError("'include_splits' must be a non-empty list.")
    splits = tuple(_string(value, "include_splits") for value in split_values)
    if len(set(splits)) != len(splits):
        raise AnalysisConfigError("'include_splits' must not contain duplicates.")
    if set(splits) - {"train", "validation"}:
        raise AnalysisConfigError(
            "Exploratory analysis may include only train and validation splits."
        )

    edge_values = root.get("tyre_age_bin_edges")
    if (
        not isinstance(edge_values, list)
        or len(edge_values) < 3
        or not all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in edge_values
        )
    ):
        raise AnalysisConfigError(
            "'tyre_age_bin_edges' must contain at least 3 integers."
        )
    edges = tuple(edge_values)
    if tuple(sorted(set(edges))) != edges:
        raise AnalysisConfigError("'tyre_age_bin_edges' must be strictly increasing.")

    output_values = _mapping(root.get("outputs"), "outputs")
    return AnalysisConfig(
        schema_version=1,
        analysis_version=_string(root.get("analysis_version"), "analysis_version"),
        source_dataset_manifest=Path(
            _string(root.get("source_dataset_manifest"), "source_dataset_manifest")
        ),
        include_splits=splits,
        random_seed=_positive_integer(root.get("random_seed"), "random_seed"),
        scatter_rows_per_event=_positive_integer(
            root.get("scatter_rows_per_event"), "scatter_rows_per_event"
        ),
        tyre_age_bin_edges=edges,
        outputs=AnalysisOutputs(
            report=Path(_string(output_values.get("report"), "outputs.report")),
            figure_directory=Path(
                _string(
                    output_values.get("figure_directory"),
                    "outputs.figure_directory",
                )
            ),
            event_summary=Path(
                _string(output_values.get("event_summary"), "outputs.event_summary")
            ),
            analysis_manifest=Path(
                _string(
                    output_values.get("analysis_manifest"),
                    "outputs.analysis_manifest",
                )
            ),
        ),
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
