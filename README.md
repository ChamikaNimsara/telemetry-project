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

## Acquire Approved Events

Acquire and validate every event in `configs/events.yaml`, then write the
traceability manifest:

```shell
uv run python -m telemetry_project.cli acquire
```

For a small acquisition or cache check:

```shell
uv run python -m telemetry_project.cli acquire --only-event Bahrain
uv run python -m telemetry_project.cli acquire --only-event Bahrain --offline
```

The default output is `data/manifests/event-manifest.json`. Each requested event
receives a success or failure entry containing source identity, retrieval time,
FastF1 version, split, row count, returned columns, and validation errors. A
partial failure returns process status 1 after writing the complete manifest.

See [data sources, provenance, and use constraints](docs/data-sources.md) before
acquiring, sharing, or publishing data-derived outputs. Raw cache files remain
local and must not be committed.

## Build the Validated Dataset

Build the versioned analysis dataset, audit every exclusion, and create frozen
event-grouped train, validation, and test outputs:

```shell
uv run python -m telemetry_project.cli build-dataset
```

The first build downloads the comparatively small weather feed required to
confirm dry running. After that, the complete build can be verified without
network access:

```shell
uv run python -m telemetry_project.cli build-dataset --offline
```

Processed row-level CSV files are generated under `data/processed/v1/` and are
excluded from Git. Versioned manifests, aggregate audit tables, the
[data dictionary](docs/data-dictionary.md), and the
[data-quality report](reports/data-quality-report.md) provide the reproducible
public record. Never use the frozen test split for preprocessing, feature
selection, or tuning.

## Explore the Development Data

Generate the development-only motorsport analysis, aggregate evidence, and four
publication-quality figures:

```shell
uv run python -m telemetry_project.cli analyze-data
```

The command verifies the processed file hashes and reads only training and
validation splits. It does not load the frozen Mexico City or Abu Dhabi test
rows. See the generated
[exploratory analysis](reports/exploratory-analysis.md) for the engineering
questions, measured and engineered quantities, findings, confounders, and
modelling implications.

## Evaluate the Baselines

Fit the explainable training-median rule and evaluate it alongside current-lap
persistence on the validation events:

```shell
uv run python -m telemetry_project.cli evaluate-baselines
```

The command verifies the processed input hashes, fits target-derived statistics
using training races only, and evaluates the fixed metrics on the two validation
races. It never loads the frozen test files. Exact aggregate and per-event
results are recorded in
[the baseline metrics](reports/baseline-validation-metrics.json), the
[per-event table](reports/tables/baseline-validation-by-event.csv), and the
[model report](reports/model-report.md). Later candidate models must use the
same validation rows and metric definitions.

## Select and Evaluate the Final Method

Compare the three predeclared interpretable candidates using training and
validation events only:

```shell
uv run python -m telemetry_project.cli select-model
```

This command freezes the lowest-MAE candidate that passes both precommitted
validation gates in `configs/final-model.yaml`. The selected pace-reversion
model achieved `0.368813 s` validation macro-event MAE.

The final evaluation command verifies every frozen input and implementation
hash, refits on train plus validation, and evaluates the two test races:

```shell
uv run python -m telemetry_project.cli evaluate-final
```

The frozen model achieved `0.317689 s` test macro-event MAE, improving on the
stronger final baseline by `9.22%`, with improvement in both test events and no
out-of-range predictions. See the [model report](reports/model-report.md),
[final metrics](reports/final-test-metrics.json), and generated figures for the
full comparison and limitations. The row-level prediction audit is written
under ignored `artifacts/`; only aggregate evidence is committed. Test results
must not be used to retune or replace the frozen method.

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
configs/                    Versioned data, analysis, and modelling configuration
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
