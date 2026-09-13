# Version 1 Retrospective

## Outcome

Version 1 delivered a reproducible, leakage-resistant FastF1 workflow from
event acquisition through held-out evaluation. The selected pace-reversion
method improved macro-event MAE by 9.22% over the stronger final baseline on
both held-out races while remaining simple enough to explain directly.

The more important result is methodological: the project preserves event-level
splits, prediction-time feature availability, frozen selection criteria,
traceable manifests, and honest limits. It demonstrates a defensible analytical
workflow without presenting public lap timing as direct physical tyre wear.

## What worked

- Selecting one narrow prediction target kept the work measurable and prevented
  an under-validated strategy optimizer from entering version 1.
- Whole-event grouping made leakage boundaries easy to explain and test.
- Immutable configuration and hash-checked manifests provided a clear chain
  from source identifiers to every published aggregate result.
- Starting with persistence and training medians exposed how much value a more
  complex method actually added.
- The conditional-median candidate was both the strongest validation method and
  operationally interpretable.
- Moving all final behavior into typed source modules and CLI commands made
  notebooks unnecessary for reproduction.

## What did not work or added limited value

- Adding compound and tyre-age segmentation to pace reversion did not improve
  validation MAE; it added sparse cells and complexity, so it was rejected.
- Public data cannot identify physical tyre condition or isolate fuel, traffic,
  track evolution, driver behavior, and tyre effects. The original “tyre wear”
  language had to be narrowed to observable tyre-performance change.
- Two final events are enough for a protected holdout but not enough for a
  stable population uncertainty interval.
- Soft-compound test coverage was only 25 samples and produced worse error than
  persistence. This subgroup cannot support a broad performance claim.
- Keeping row-level data out of Git protects licensing and repository hygiene,
  but means a new reviewer must reacquire the source sessions before rebuilding
  every result.

## Highest-value next iteration

Add forward validation on a later regulation-compatible season and reserve more
whole events for testing. The objective is to measure dataset shift and report
an event-level uncertainty interval before adding model complexity.

Only after that evidence should version 2 evaluate richer time-valid context,
such as nearby-traffic indicators and track-evolution features. Any strategy
optimizer remains a separate project gate requiring independently validated
degradation, pit-loss, traffic, race-state, and counterfactual components.

## Practices to retain

- Freeze targets, splits, metrics, and selection gates before model comparison.
- Keep final test events unavailable until selection is fixed.
- Compare every candidate with simple, identically evaluated baselines.
- Publish aggregate evidence and original figures, not row-level source data.
- Treat a release as a reviewed evidence package: code, configuration, tests,
  manifests, results, limitations, licensing, and a reproducibility record.
