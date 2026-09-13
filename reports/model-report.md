# Model Report

## US-06 — Baseline benchmark

Current-lap persistence predicts that the next clean lap will equal the lap just
completed. Training-median degradation adds the training median next-lap change
for the current compound and reported tyre-age band, falling back to compound
and then global training medians for sparse cells. Both operate at the same
prediction point and use the same eligible rows and metrics as candidates.

Persistence is vulnerable to an unrepresentative current lap. The median rule
is coarse and cannot adjust for circuit, driver, fuel, traffic, track evolution,
or interacting conditions. On validation, training-median degradation was the
stronger fixed baseline at 0.419979 s macro-event MAE; neither rule represents a
causal estimate of physical tyre wear.

## Final method and evaluation

The selected method is **pace reversion**: it places the latest observed
current-minus-previous lap change into one of ten predeclared bands and adds the
training median next-lap change for that band to the current lap. It is a robust,
interpretable conditional-median model. Missing history falls back to the global
development median. No future-lap value is an input.

Selection used six training events and two validation events only. Pace
reversion achieved 0.368813 s validation
macro-event MAE, passed the frozen 0.398980 s gate, and was frozen in
`configs/final-model.yaml` before test rows were loaded. The compound/tyre-age
variant was evaluated but not selected because the extra segmentation did not
improve validation MAE.

For the one-time final evaluation, the selected method and training-median
baseline were refitted on train plus validation, then compared on the two frozen
test races. The selected method achieved 0.3177
s macro-event MAE versus 0.3499 s for the
stronger final baseline (9.22% change).

### Held-out event variation

| Event | Samples | MAE (s) | RMSE (s) | Signed error (s) |
|---|---:|---:|---:|---:|
| Mexico City Grand Prix | 1,021 | 0.3574 | 0.6064 | -0.0389 |
| Abu Dhabi Grand Prix | 818 | 0.2780 | 0.4362 | -0.0289 |

### Error by compound

| Compound | Samples | MAE (s) |
|---|---:|---:|
| HARD | 1,192 | 0.3154 |
| MEDIUM | 622 | 0.3156 |
| SOFT | 25 | 0.7993 |

### Error analysis, robustness, and limitations

The per-event range is the most defensible uncertainty signal with only two
held-out races; it is not enough to estimate a stable population confidence
interval. Condition-level results in
`reports/tables/final-test-by-condition.csv` cover compound, tyre-age band, and
missing previous-lap context. The selected method produced 0
predictions outside the dataset's 30-300 s physical range.

The model mainly captures short-term pace reversion, not physical tyre wear.
Tyre age, compound, fuel load, traffic, circuit, and track evolution remain
associated and cannot be interpreted causally. Large disruptions are excluded
by the dataset policy, so accuracy does not establish performance during safety
cars, pit transitions, wet running, other seasons, or live operations. A poor
current or previous lap can still anchor a poor prediction.

### Reproduction

```shell
uv run python -m telemetry_project.cli select-model
uv run python -m telemetry_project.cli evaluate-final
```

The first command is development-only. The second verifies the frozen selection
hashes, writes row-level predictions to an ignored local artifact, and publishes
only aggregate metrics and figures. Do not rerun final evaluation to tune or
replace the selected method.
