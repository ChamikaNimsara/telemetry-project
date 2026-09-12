# Problem Definition

**Status:** Approved baseline — subject to the documented Gate 2 data audit  
**Related work:** US-01/T-01.3  
**Primary recommendation:** Tyre-performance degradation estimation

## Testable Problem Statement

Given only information available by the end of an eligible dry-race lap,
estimate the next eligible lap time and the implied lap-time performance change
as the current tyre stint ages, then validate the estimate on complete unseen
race events.

## Intended User and Decision

The intended user is a race-performance analyst performing post-event analysis
or building an input to later strategy simulation. The output helps the analyst
compare likely pace evolution across stint contexts and identify where observed
performance departs from the expected curve.

Version 1 does not recommend live pit decisions and is not a safety-critical
system.

## Prediction Contract

| Item | Definition |
|---|---|
| Prediction time | End of the current eligible completed lap |
| Unit | Driver-event-stint-lap |
| Target | Next eligible clean-lap time in seconds |
| Derived output | Predicted pace change over tyre age in seconds per lap |
| Primary evaluation unit | Complete held-out race event |
| Primary metric | Macro-event mean absolute error in seconds |
| Baseline 1 | Current-lap persistence |
| Baseline 2 | Training-median degradation for comparable stints |
| Version 1 domain | 2024 dry race laps on slick compounds in selected events |

“Next eligible” means the next chronologically consecutive lap that also passes
all quality rules. The pipeline must not skip an intervening ineligible lap and
pretend the later lap was an ordinary next-lap observation.

## Permitted Input Families

Only values known at prediction time are permitted:

- reported compound, tyre life, stint, and fresh/used indicator where valid;
- current and historical eligible lap/sector times within the same race;
- lap number, race progress, driver/team, and event identifiers;
- contemporaneous weather and track-status data;
- summaries derived from telemetry up to the current lap, if later justified.

All preprocessing statistics must be fitted using training data only.

## Forbidden Inputs

- next-lap or later lap/sector/telemetry values;
- final stint length or the future pit-lap number;
- future flags, weather, positions, gaps, or race outcome;
- statistics calculated across the full event when they include validation/test
  or future laps;
- manually corrected labels whose provenance is not recorded.

## Initial Eligibility Policy

Include only observations meeting all final audited rules. At minimum:

- race session and dry conditions;
- slick compound with valid compound, stint, tyre-life, and lap-time fields;
- accurate, non-deleted laps;
- no pit entry/exit on current or target lap;
- no safety-car, virtual-safety-car, yellow, red-flag, or incident effect;
- chronological current/target pair within the same driver and stint;
- minimum usable stint length selected before modelling.

The data-quality report must list counts removed by each rule. Rules may be
refined after inspecting data quality, but before candidate-model evaluation,
and the change must be recorded in `DECISIONS.md`.

## Evaluation Protocol

1. Freeze event membership before feature/model selection.
2. Fit transformations and models using training events only.
3. Use validation events for feature choices, tuning, and the final numeric
   success threshold.
4. Freeze the method and evaluate once on the two held-out test events.
5. Report MAE per event and the unweighted mean across events.
6. Also report RMSE, median absolute error, signed error, subgroup breakdowns,
   sample counts, and uncertainty where supported.
7. Compare every candidate under identical eligibility and split rules with both
   baselines.

The minimum release criterion is improvement over persistence on a majority of
held-out events and lower macro-event MAE than the stronger fixed baseline. A
numeric margin must be set after the data smoke test and before model selection.

## Required Outputs

- one prediction per eligible held-out row with event/stint identifiers;
- aggregate and per-event metric tables;
- baseline comparison;
- predicted-versus-observed and residual diagnostics;
- pace-change/degradation visualization with units and uncertainty;
- error breakdown by compound, tyre age band, driver/team, and event;
- data, split, configuration, environment, and experiment identifiers;
- explicit limitations and excluded-sample counts.

## Claims the Project May and May Not Make

The project may report predictive accuracy for the audited event population and
describe associations between observable context, tyre age, and lap time.

It must not claim to measure physical tyre wear, isolate a causal tyre effect,
generalize to arbitrary seasons/cars/circuits, or prove an optimal pit strategy.

## Controlled Revisit Items

- Freeze the numeric success margin after the acquisition smoke test (D-003).
- Reconfirm event eligibility and the grouped split after the data audit (D-002
  and D-004). Replace an event only under the approved replacement policy.
