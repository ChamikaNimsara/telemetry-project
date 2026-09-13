# Model Report

## US-06 — Validation Baselines

### Evaluation boundary

Both rules predict `next_lap_time_seconds` at the end of the current eligible
lap. Their metrics use the same 2,412 validation rows and complete
held-out events (2024-10-R, 2024-15-R) that later candidates must use during
selection. Only the 5,431 training rows are used to estimate the
second rule. The frozen test files are not loaded by this command.

The primary metric is unweighted macro-event mean absolute error (MAE), so each
race contributes equally even when sample counts differ. Secondary diagnostics
are event-macro RMSE, median absolute error, and signed error, plus pooled
versions for auditability. All errors are in seconds.

### Rules and results

| Baseline | Explanation | Macro-event MAE (s) | Macro-event RMSE (s) | Macro-event signed error (s) |
|---|---|---:|---:|---:|
| Current-lap persistence | Predict that the next clean lap equals the just-completed lap. | 0.4203 | 0.7451 | -0.0296 |
| Training-median degradation | Add the training median next-lap change for the current compound and reported tyre-age band. | 0.4200 | 0.7447 | -0.0120 |

The stronger fixed benchmark on validation is **training median degradation**.
Under D-008, a candidate must reduce validation macro-event MAE by at least 5%
relative to this rule: the maximum qualifying MAE is
**0.398980 s**. It also may not worsen either validation event
by more than 10% before it can be selected.

### What the training-median rule knows

The rule knows the current lap time, reported compound, and reported tyre life,
all available at prediction time. It learns only the median observed
`next_lap_delta_seconds` from training events. A compound/age cell is used only
when it has at least 30 training
samples. Otherwise the rule falls back first to the compound median and then to
the global training median. Validation fallback counts were:
compound=24, compound_tyre_age_band=2,388.

This rule is deliberately not a fitted physical tyre-wear model. Its age bands
are coarse, and its medians do not adjust for driver, circuit, fuel mass,
traffic, track evolution, temperature, setup, or interactions among them. It
can underperform when a validation event has conditions unlike training, when
reported tyre life is outside well-covered cells, or when the current lap is an
unrepresentative anchor. These are predictive associations, not causal tyre
effects.

### Reproduction and evidence

Run:

```shell
uv run python -m telemetry_project.cli evaluate-baselines
```

The command verifies input hashes, fits on `train`, evaluates only on
`validation`, and rewrites the aggregate metrics, per-event table, this report,
and experiment manifest deterministically. See
`reports/baseline-validation-metrics.json` and
`reports/tables/baseline-validation-by-event.csv` for exact values.
