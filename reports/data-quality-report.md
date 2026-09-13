# Data Quality Report

**Scope:** US-04 validated analysis dataset
**Dataset version:** 1.0.0
**Dataset schema:** 1
**Source manifest SHA-256:** `5cd4e003babe8515da519cb8e19b7cc7aaee8c97d465c028fe8486be845cf5db`

## Outcome

The audit examined 11,464 race laps across 10 events. After lap-level eligibility and strict consecutive-target checks, 9,682 modelling samples remain from 10,312 base-eligible laps.

Weather is aligned to each lap. 0 rows lack required weather values and 20 rows report rainfall; both are excluded under the version 1 dry-running policy.

## Event Coverage

| Split | Event | Raw laps | Missing required | Base eligible | Target pairs | Final samples | Weather missing | Wet | Pit laps | Disrupted |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| train | Bahrain Grand Prix | 1129 | 2 | 1006 | 931 | 929 | 0 | 0 | 86 | 42 |
| train | Japanese Grand Prix | 907 | 31 | 764 | 696 | 694 | 0 | 0 | 108 | 42 |
| train | Emilia Romagna Grand Prix | 1238 | 1 | 1164 | 1118 | 1117 | 0 | 0 | 55 | 0 |
| train | Hungarian Grand Prix | 1355 | 0 | 1233 | 1155 | 1155 | 0 | 0 | 82 | 21 |
| train | Belgian Grand Prix | 841 | 1 | 734 | 663 | 659 | 0 | 0 | 69 | 19 |
| train | Italian Grand Prix | 1008 | 0 | 927 | 877 | 877 | 0 | 0 | 61 | 0 |
| validation | Spanish Grand Prix | 1310 | 0 | 1186 | 1104 | 1104 | 0 | 20 | 85 | 0 |
| validation | Dutch Grand Prix | 1426 | 0 | 1354 | 1308 | 1308 | 0 | 0 | 53 | 0 |
| test | Mexico City Grand Prix | 1215 | 2 | 1061 | 1021 | 1021 | 0 | 0 | 44 | 110 |
| test | Abu Dhabi Grand Prix | 1035 | 2 | 883 | 821 | 818 | 0 | 0 | 56 | 102 |

## Exclusion Policy

Each raw lap receives at most one primary exclusion reason in the documented precedence order. Counts therefore do not double-count a lap. A modelling sample is retained only when both the current and immediately following chronological lap are eligible, belong to the same driver and stint, and belong to a run of at least 3 consecutive eligible laps.

| Primary reason | Excluded laps |
|---|---:|
| duplicate lap key | 0 |
| missing identity | 6 |
| missing lap time | 33 |
| implausible lap time | 0 |
| missing tyre data | 0 |
| non slick compound | 0 |
| inaccurate lap | 978 |
| deleted lap | 0 |
| pit in lap | 0 |
| pit out lap | 0 |
| missing feature | 0 |
| missing weather | 0 |
| wet weather | 20 |
| disrupted track status | 115 |

Independent diagnostics can overlap: 39 rows have a missing required value, 699 are pit-in or pit-out laps, 1017 are marked inaccurate, 336 have a disrupted track status, and 0 have non-monotonic driver timing.

The detailed mutually exclusive counts are in `reports/tables/data-quality-by-event.csv`. Duplicate lap keys, non-monotonic timing, missing weather, wet running, pit laps, deleted or inaccurate laps, non-slick compounds, implausible lap times, and disrupted track statuses are measured explicitly.

## Target and Leakage Review

The target is the lap time of the immediately next eligible consecutive lap. The pipeline never skips an excluded or missing intervening lap. Target columns are separated from the feature catalogue, while previous-lap features use only already-completed laps. Event groups are assigned from the frozen event configuration before processing, and automated validation requires train, validation, and test event IDs to be disjoint.

## Missing Values and Limitations

Rows missing required identity, target, tyre, current-lap, or weather features are excluded and counted. Sector times and previous-lap features remain nullable because valid FastF1 laps can lack a sector or can be the first eligible lap in a clean run; downstream preprocessing must learn any imputation from training events only.

FastF1 corrections and source warnings remain recorded in the acquisition manifest. This dataset describes observed lap-time performance and must not be interpreted as a direct or causal measurement of physical tyre wear.
