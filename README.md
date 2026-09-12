# Motorsport Telemetry Project

A reproducible Formula 1 telemetry project for estimating tyre-performance
degradation from public timing and telemetry data. Version 1 predicts the next
eligible clean-lap time and derives the expected pace change as a tyre stint
ages. It does not claim to measure physical tyre wear.

The project is currently establishing its data and modelling pipeline. See the
[problem definition](docs/problem-definition.md) and
[feasibility study](reports/feasibility-study.md) for the approved scope.

## Requirements

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Git

Python 3.12 is pinned in `.python-version`. `uv` can install it automatically if
it is not already available.

## Setup

From the repository root:

```shell
uv python install 3.12
uv sync --locked --dev
uv run python -m telemetry_project.cli --help
```

`uv sync --locked` creates or updates the local `.venv` from the committed
cross-platform `uv.lock`. The environment and lockfile must agree; update the
lock intentionally with `uv lock` after changing dependencies.

No API key is required for FastF1. The optional environment variable below
changes the local FastF1 cache directory:

```shell
TELEMETRY_CACHE_DIR=data/raw/fastf1-cache
```

Copy `.env.example` only if your shell or tooling loads environment files.
Python does not read it automatically. Raw FastF1 cache data is intentionally
excluded from Git.

## FastF1 Smoke Test

Confirm that FastF1 can load lap timing for a small historical race session:

```shell
uv run python -m telemetry_project.cli smoke-fastf1 \
  --year 2024 \
  --event Bahrain \
  --session R
```

PowerShell accepts the command on one line:

```powershell
uv run python -m telemetry_project.cli smoke-fastf1 --year 2024 --event Bahrain --session R
```

The first run requires network access and populates
`data/raw/fastf1-cache/`. Telemetry and weather loading are disabled for this
smoke test to limit download size. A successful run prints a JSON summary with
the resolved event name, session code, lap count, and available lap columns.

Use `--cache-dir PATH` to override `TELEMETRY_CACHE_DIR` for one invocation.

## Quality Checks

Run the same checks enforced by continuous integration:

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
```

To apply formatting locally:

```shell
uv run ruff format .
```

Tests replace the external FastF1 service with local fakes. CI therefore
validates project behavior without depending on network data availability.

## Repository Layout

```text
configs/                    Versioned event and analysis configuration
docs/                       Public technical documentation
reports/                    Reproducible findings and selected figures
src/telemetry_project/      Maintained Python package
tests/                      Automated tests
```

Generated environments, caches, raw/interim data, model binaries, and generated
reports are excluded from version control.

## Reproducibility Rules

- Keep `pyproject.toml` and `uv.lock` synchronized.
- Record the FastF1 version and event identifiers with acquired data.
- Never commit raw FastF1 cache data, secrets, or machine-specific paths.
- Fit preprocessing and models on training events only.
- Keep validation and final test events disjoint from training.
- Run the quality checks before requesting review.

## Data Source

The project uses [FastF1](https://github.com/theOehrly/Fast-F1), which provides
access to Formula 1 timing, lap, session, weather, and telemetry data. Source
availability and field quality can vary by event, so later pipeline stages will
produce an auditable event manifest and data-quality report.
