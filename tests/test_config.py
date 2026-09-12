"""Tests for runtime configuration."""

from pathlib import Path

from telemetry_project.config import DEFAULT_CACHE_DIR, resolve_cache_dir


def test_explicit_cache_dir_takes_priority() -> None:
    explicit = Path("custom/cache")

    assert resolve_cache_dir(explicit, {"TELEMETRY_CACHE_DIR": "ignored"}) == explicit


def test_cache_dir_uses_environment() -> None:
    assert resolve_cache_dir(
        environ={"TELEMETRY_CACHE_DIR": "configured/cache"}
    ) == Path("configured/cache")


def test_blank_environment_value_uses_default() -> None:
    assert resolve_cache_dir(environ={"TELEMETRY_CACHE_DIR": "  "}) == DEFAULT_CACHE_DIR
