"""Load and validate the race-performance comparison configuration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml


class PerformanceConfigError(ValueError):
    """Raised when race-performance configuration is invalid."""


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """One FastF1 session used for the comparison."""

    year: int
    event: str
    session: str


@dataclass(frozen=True, slots=True)
class DriverConfig:
    """Reference and comparison driver abbreviations."""

    reference: str
    reference_name: str
    comparison: str
    comparison_name: str


@dataclass(frozen=True, slots=True)
class Corner:
    """Configured corner apex location on the telemetry distance axis."""

    label: str
    distance_m: float


@dataclass(frozen=True, slots=True)
class PerformanceOutputs:
    """Repository-relative aggregate outputs."""

    report: Path
    engineering_brief: Path
    figure_directory: Path
    corner_table: Path
    mini_sector_table: Path
    manifest: Path


@dataclass(frozen=True, slots=True)
class PerformanceConfig:
    """Validated performance-analysis policy and content fingerprint."""

    schema_version: int
    analysis_version: str
    session: SessionConfig
    drivers: DriverConfig
    distance_step_m: float
    mini_sector_length_m: float
    corner_window_before_m: float
    corner_window_after_m: float
    brake_lookback_m: float
    throttle_lookahead_m: float
    throttle_pickup_percent: float
    sustained_samples: int
    corners: tuple[Corner, ...]
    outputs: PerformanceOutputs
    source_path: str
    source_sha256: str


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PerformanceConfigError(f"'{field}' must be a mapping with string keys.")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PerformanceConfigError(f"'{field}' must be a non-empty string.")
    return value.strip()


def _positive_number(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or float(value) <= 0
    ):
        raise PerformanceConfigError(f"'{field}' must be a positive number.")
    return float(value)


def _positive_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PerformanceConfigError(f"'{field}' must be a positive integer.")
    return value


def load_performance_config(path: Path) -> PerformanceConfig:
    """Read a race-performance YAML configuration and validate its contract."""
    try:
        content = path.read_bytes()
        loaded: object = yaml.safe_load(content)
    except OSError as error:
        raise PerformanceConfigError(
            f"Unable to read performance config '{path}': {error}"
        ) from error
    except yaml.YAMLError as error:
        raise PerformanceConfigError(
            f"Invalid YAML in performance config '{path}': {error}"
        ) from error

    root = _mapping(loaded, "root")
    if root.get("schema_version") != 1:
        raise PerformanceConfigError(
            "Performance configuration schema version must be 1."
        )
    session_values = _mapping(root.get("session"), "session")
    year = _positive_integer(session_values.get("year"), "session.year")
    session_code = _string(session_values.get("session"), "session.session").upper()
    if session_code not in {"Q", "R"}:
        raise PerformanceConfigError("'session.session' must be 'Q' or 'R'.")

    driver_values = _mapping(root.get("drivers"), "drivers")
    reference = _string(driver_values.get("reference"), "drivers.reference").upper()
    reference_name = _string(
        driver_values.get("reference_name"), "drivers.reference_name"
    )
    comparison = _string(driver_values.get("comparison"), "drivers.comparison").upper()
    comparison_name = _string(
        driver_values.get("comparison_name"), "drivers.comparison_name"
    )
    if reference == comparison:
        raise PerformanceConfigError("Reference and comparison drivers must differ.")

    sampling = _mapping(root.get("sampling"), "sampling")
    pickup = _positive_number(
        sampling.get("throttle_pickup_percent"),
        "sampling.throttle_pickup_percent",
    )
    if pickup > 100:
        raise PerformanceConfigError(
            "'sampling.throttle_pickup_percent' must not exceed 100."
        )

    corner_values = root.get("corners")
    if not isinstance(corner_values, list) or not corner_values:
        raise PerformanceConfigError("'corners' must be a non-empty list.")
    corners: list[Corner] = []
    for index, value in enumerate(corner_values):
        item = _mapping(value, f"corners[{index}]")
        corners.append(
            Corner(
                label=_string(item.get("label"), f"corners[{index}].label"),
                distance_m=_positive_number(
                    item.get("distance_m"), f"corners[{index}].distance_m"
                ),
            )
        )
    if len({corner.label for corner in corners}) != len(corners):
        raise PerformanceConfigError("Corner labels must be unique.")
    if tuple(sorted(corner.distance_m for corner in corners)) != tuple(
        corner.distance_m for corner in corners
    ):
        raise PerformanceConfigError("Corners must be ordered by distance.")

    output_values = _mapping(root.get("outputs"), "outputs")
    return PerformanceConfig(
        schema_version=1,
        analysis_version=_string(root.get("analysis_version"), "analysis_version"),
        session=SessionConfig(
            year=year,
            event=_string(session_values.get("event"), "session.event"),
            session=session_code,
        ),
        drivers=DriverConfig(
            reference=reference,
            reference_name=reference_name,
            comparison=comparison,
            comparison_name=comparison_name,
        ),
        distance_step_m=_positive_number(
            sampling.get("distance_step_m"), "sampling.distance_step_m"
        ),
        mini_sector_length_m=_positive_number(
            sampling.get("mini_sector_length_m"), "sampling.mini_sector_length_m"
        ),
        corner_window_before_m=_positive_number(
            sampling.get("corner_window_before_m"),
            "sampling.corner_window_before_m",
        ),
        corner_window_after_m=_positive_number(
            sampling.get("corner_window_after_m"),
            "sampling.corner_window_after_m",
        ),
        brake_lookback_m=_positive_number(
            sampling.get("brake_lookback_m"), "sampling.brake_lookback_m"
        ),
        throttle_lookahead_m=_positive_number(
            sampling.get("throttle_lookahead_m"),
            "sampling.throttle_lookahead_m",
        ),
        throttle_pickup_percent=pickup,
        sustained_samples=_positive_integer(
            sampling.get("sustained_samples"), "sampling.sustained_samples"
        ),
        corners=tuple(corners),
        outputs=PerformanceOutputs(
            report=Path(_string(output_values.get("report"), "outputs.report")),
            engineering_brief=Path(
                _string(
                    output_values.get("engineering_brief"),
                    "outputs.engineering_brief",
                )
            ),
            figure_directory=Path(
                _string(
                    output_values.get("figure_directory"),
                    "outputs.figure_directory",
                )
            ),
            corner_table=Path(
                _string(output_values.get("corner_table"), "outputs.corner_table")
            ),
            mini_sector_table=Path(
                _string(
                    output_values.get("mini_sector_table"),
                    "outputs.mini_sector_table",
                )
            ),
            manifest=Path(_string(output_values.get("manifest"), "outputs.manifest")),
        ),
        source_path=path.as_posix(),
        source_sha256=hashlib.sha256(content).hexdigest(),
    )
