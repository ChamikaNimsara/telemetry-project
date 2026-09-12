# Telemetry Project Feasibility Study

**Status:** Complete and recommendation approved  
**Date:** 13 September 2026  
**Decision outcome:** Tyre-performance degradation accepted for version 1

## Executive Recommendation

Select **tyre-performance degradation estimation** as the primary version 1
problem.

The project should estimate the change in representative dry-race lap-time
performance as a tyre stint ages. It must call this *performance degradation*,
not physical tyre wear: FastF1 exposes timing and reported tyre context but does
not provide tread depth, carcass condition, temperature distribution, pressure,
or direct wear measurements.

Lap-strategy optimization remains a valuable version 2 extension. Building it
credibly first would require a validated pace/degradation model plus pit-loss,
traffic, weather, safety-car, rules, and counterfactual race simulation. That is
too much primary scope for the 15 October to 30 November delivery window.

## Candidate Problems

### A — Tyre-Performance Degradation Estimation

Estimate how representative lap-time performance changes with tyre age during
dry race stints while accounting for observable context. The useful output is a
degradation estimate in seconds per lap or a predicted clean-lap pace curve,
with uncertainty and event-level validation.

This is not a claim that elapsed tyre life alone causes the measured change.
Fuel burn, traffic, driver pace, track evolution, temperature, compound,
circuit, and race state can all affect lap time.

### B — Lap-Strategy Optimization

Recommend pit timing and compound sequences that minimize expected race time or
maximize an explicitly defined finishing objective under constraints.

Historical data reveals the strategies teams actually used, not what would have
happened under every alternative. A credible optimizer therefore depends on
several separately validated models and assumptions, including tyre pace,
pit-lane loss, traffic after a stop, compound availability, safety-car timing,
weather transitions, and race regulations.

## Data Feasibility

FastF1's current analysis guide exposes session laps and results through a
`Session`, supports filtering accurate/quick laps and compounds, and demonstrates
stint and tyre-degradation analysis. It also provides per-lap telemetry access
for analysis.[^1]

Useful observed inputs include:

- lap and sector times;
- driver, team, lap number, stint, reported compound, and tyre life;
- pit-in and pit-out timing;
- track status and lap-accuracy indicators;
- speed traps and car telemetry such as speed, throttle, brake, gear, and DRS;
- session weather, subject to coverage and loading checks.

These fields make a degradation proxy feasible, but not automatically reliable.
FastF1 advises checking missing data, and historical project issues show that
tyre-life, stint, and compound fields have had missing or incorrect values in
some sessions. Missing tyre age must not be filled with an assumed value of one,
because a used set may carry age from an earlier session.[^2] A 2025 issue also
documented missing compound values in part of a 2024 practice session after a
library update, reinforcing the need to pin the library and audit each event.[^3]

Acquisition is feasible within the schedule if caching and a fixed event
manifest are used. FastF1's maintainer recommends caching and notes that loading
telemetry greatly increases cache size; offline mode can later make cached runs
network-independent.[^4]

## Weighted Comparison

Scores use a 1–5 scale, where 5 is most favorable for a version 1 project.

| Criterion | Weight | Degradation | Strategy | Reason |
|---|---:|---:|---:|---|
| Target/objective observability | 25% | 3 | 2 | Lap-time degradation is a proxy; optimal alternative strategies are unobserved counterfactuals. |
| FastF1 data coverage | 20% | 4 | 2 | Stint analysis has direct fields; full strategy needs traffic, rules, pit loss, uncertainty, and race-state models. |
| Evaluation credibility | 20% | 4 | 2 | Held-out lap/session errors are measurable; historical strategy replay cannot prove an unchosen strategy was optimal. |
| Delivery risk by 30 Nov | 15% | 4 | 2 | Degradation supports a focused pipeline; strategy combines several major submodels. |
| Motorsport decision value | 10% | 4 | 5 | Both matter; strategy is closer to a race decision if all dependencies are credible. |
| Portfolio clarity | 10% | 4 | 4 | Either can be compelling with honest boundaries and reproducible evidence. |
| **Weighted total** | **100%** | **75/100** | **50/100** | Degradation is the stronger version 1 foundation. |

## Proposed Minimum Viable Analysis

### Decision Context

A race-performance analyst wants an early, uncertainty-aware estimate of how
lap-time performance is likely to evolve across a dry tyre stint.

### Unit of Analysis

One eligible completed racing lap, grouped within driver-event-stint. The final
method may estimate a stint curve or the next eligible lap, but all inputs must
be available by the end of the current lap.

### Proposed Target

**Primary:** next eligible clean-lap time in seconds, evaluated as an error from
observed lap time.  
**Engineering output:** the corresponding predicted pace change over tyre age,
reported in seconds per lap with uncertainty.

The target definition is intentionally provisional. The data audit must verify
that enough consecutive clean laps remain after pit, flag, rainfall, and quality
filters. If not, D-003 must be revised before modelling.

### Candidate Inputs

- tyre age and reported relative compound;
- current and prior eligible lap/sector pace available at prediction time;
- driver/team and event context, handled carefully for unseen-event evaluation;
- track temperature and other weather measurements available at the time;
- lap number/race progress and track status;
- compact telemetry summaries only if their acquisition cost and incremental
  value justify inclusion.

Estimated remaining fuel mass, unobserved tyre state, future weather, future
flags, and future traffic must not be treated as measured inputs.

### Initial Eligibility Rules

- Race sessions only and dry slick-tyre running only for version 1.
- Exclude in-laps, out-laps, inaccurate/deleted laps, safety-car/VSC/yellow-
  affected laps, obvious pit/incident laps, and laps without a valid target.
- Require a minimum number of eligible consecutive laps per stint; choose the
  threshold from the pre-model data audit.
- Never silently repair compound, stint, or tyre-life values.
- Preserve counts and reasons for every exclusion.

## Baseline and Metrics

### Baselines

1. **Persistence:** predict that the next eligible lap equals the current
   eligible lap.
2. **Training-median degradation:** apply the median seconds-per-lap change from
   comparable training stints.

Both baselines must use only information available at prediction time.

### Primary Metric

Mean absolute error (MAE) in seconds for next-eligible-lap prediction, aggregated
first within each held-out event and then across events so large events do not
dominate the headline value.

### Secondary Diagnostics

- root mean squared error to expose large misses;
- median absolute error;
- signed mean error for systematic over/under-prediction;
- error by event, compound, tyre-age band, driver/team, and stint length;
- coverage and width if prediction intervals are produced;
- error in the derived stint degradation slope, reported as seconds per lap.

No numeric success threshold should be invented before the acquisition smoke
test establishes target scale and baseline variance. Version 1 must at minimum
beat persistence MAE on a majority of held-out events and improve macro-event
MAE over the stronger baseline. The final threshold will be frozen before model
selection.

## Initial Split and Event Proposal

Use 2024 race sessions for the first feasibility dataset because they sit within
one technical-regulation period and are old enough for stable reproducibility.
The proposed events intentionally cover different circuit and degradation
characteristics:

- Training: Bahrain, Japan, Emilia-Romagna, Hungary, Belgium, Italy
- Validation: Spain, Netherlands
- Final held-out test: Mexico City, Abu Dhabi

This is a proposed manifest, not a claim that all events are clean or complete.
The acquisition audit must confirm dry coverage, field quality, compound/stint
consistency, enough eligible stints, and correct FastF1 event names. Replacement
criteria are specified in `configs/events.yaml` so an event cannot be swapped
because its model result is inconvenient.

The final test events must remain unexamined for model and feature selection once
the manifest passes its audit.

## Major Risks and Controls

| Risk | Effect | Required control |
|---|---|---|
| No physical wear label | Misleading project claim | Name the output performance degradation and document the proxy. |
| Fuel burn and track evolution | Confounded tyre-age relationship | Include observable race progress/context, use within-event analysis, and avoid causal language. |
| Traffic and race-control periods | Large non-tyre lap-time variation | Apply predeclared filters and report exclusions. |
| Used-set or missing tyre age | Incorrect stint chronology | Audit rather than assume or silently impute. |
| Driver/team/circuit dependence | Weak unseen-event generalization | Use grouped event splits and per-event metrics. |
| Compound labels are event-relative | Misinterpreted cross-event physics | Treat SOFT/MEDIUM/HARD as event-relative selections and document this limitation. |
| Small eligible sample after filtering | Unstable estimates | Define minimum stint length and uncertainty; expand predeclared events if required. |
| Library/source changes | Irreproducible datasets | Pin versions, cache raw responses, and save manifests/schema versions. |

## Feasibility Conclusion

Tyre-performance degradation is feasible as a disciplined version 1 portfolio
project if its output is described as a timing-based proxy, evaluation is grouped
by event, and data-quality controls are treated as core implementation work.

Lap-strategy optimization should follow only after the degradation model and its
uncertainty are validated. That sequencing produces a useful building block for
strategy work without overstating what historical public data can prove.

## Sources

[^1]: [FastF1 — Data Analysis with FastF1](https://theoehrly-fast-f1.mintlify.app/guides/data-analysis), accessed 13 September 2026.
[^2]: [FastF1 discussion #197 — Missing TyreLife and wrong Stint](https://github.com/theOehrly/Fast-F1/discussions/197), including maintainer response, accessed 13 September 2026.
[^3]: [FastF1 issue #768 — Differences in Tyre Data after v3.6.0](https://github.com/theOehrly/Fast-F1/issues/768), accessed 13 September 2026.
[^4]: [FastF1 discussion #754 — caching, selective loading, and offline mode](https://github.com/theOehrly/Fast-F1/discussions/754), including maintainer response, accessed 13 September 2026.
