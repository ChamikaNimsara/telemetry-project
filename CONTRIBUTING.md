# Contributing

Contributions that improve reproducibility, data validation, documentation, or
the defensibility of the analysis are welcome.

## Development workflow

1. Create a branch from `main`.
2. Install the pinned toolchain with `uv sync --locked --dev`.
3. Keep reusable logic in `src/telemetry_project/` and add tests for changed
   behaviour.
4. Run the checks listed below.
5. Open a focused pull request that explains the change, evidence, and limits.

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m telemetry_project.cli release-audit
```

Changes to data eligibility, split membership, targets, model selection, or
reported metrics must explain why the existing evidence is no longer adequate.
Never tune against the frozen test events or introduce future-lap information.

## Data and generated files

Do not commit raw FastF1 cache data, row-level processed data, predictions,
credentials, model binaries, or machine-specific paths. Contributors must
reacquire source data using the documented event identifiers. Read
[`docs/data-sources.md`](docs/data-sources.md) before sharing derived material.

## Reporting expectations

- Preserve source and configuration provenance.
- Use event-grouped validation and compare results with the fixed baselines.
- State assumptions, exclusions, failed experiments, and known limitations.
- Do not claim physical tyre wear, causality, official Formula 1 affiliation,
  or suitability for safety-critical/live race decisions.

By contributing code or documentation, you agree that your contribution is
provided under the repository's [MIT License](LICENSE). This license applies to
the project software and original documentation; it does not grant rights to
underlying Formula 1 or FastF1-retrieved data.
