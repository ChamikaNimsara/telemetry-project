# Analysis Dataset Contract and Feature Catalogue

**Dataset version:** 1.0.0
**Schema version:** 1
**Unit of observation:** Driver-event-stint-current-lap
**Prediction time:** End of the current completed eligible lap

The executable source of truth is `telemetry_project.data.schema`. Validation
requires the exact column set below, enforces types, nullability and numeric
ranges, and rejects duplicate keys. The composite key is `event_id`,
`driver_number`, `stint`, and `lap_number`; `sample_id` is its serialized form.

## Identifiers and Provenance

| Column | Type | Nullable | Unit | Definition |
|---|---|---:|---|---|
| `sample_id` | string | no | — | Stable serialized composite key |
| `event_id` | string | no | — | `{season}-{round}-{session}` source group |
| `season` | integer | no | year | Championship season |
| `round_number` | integer | no | round | Official event round |
| `event_name` | string | no | — | FastF1-resolved event name |
| `session_code` | string | no | — | `R` for the version 1 race domain |
| `split` | string | no | — | Frozen `train`, `validation`, or `test` group |
| `source_id` | string | no | — | FastF1 API path recorded by acquisition |
| `driver_number` | string | no | — | Racing number; identifier, not magnitude |
| `stint` | integer | no | stint | Reported tyre stint number, minimum 1 |
| `lap_number` | integer | no | lap | Current race lap number, minimum 1 |

## Features Available at Prediction Time

| Column | Type | Nullable | Unit/range | Availability and rationale |
|---|---|---:|---|---|
| `team` | string | no | — | Known entrant; controls car-performance context |
| `stint_lap_index` | integer | no | laps, ≥1 | Count observed through current lap only |
| `compound` | string | no | SOFT/MEDIUM/HARD | Reported current slick compound |
| `tyre_life_laps` | number | no | laps, ≥1 | Reported tyre life; can include earlier use |
| `fresh_tyre` | boolean | no | — | Reported tyre-set state at stint start |
| `position` | integer | no | position, ≥1 | Known at current-lap completion |
| `track_status` | string | no | code `1` | Current all-clear status |
| `air_temp_c` | number | no | −20–70 °C | Weather aligned to current lap |
| `track_temp_c` | number | no | −20–90 °C | Weather aligned to current lap |
| `humidity_percent` | number | no | 0–100% | Weather aligned to current lap |
| `pressure_mbar` | number | no | 700–1100 mbar | Weather aligned to current lap |
| `wind_speed_mps` | number | no | m/s, ≥0 | Weather aligned to current lap |
| `wind_direction_deg` | number | no | 0–360° | Weather aligned to current lap |
| `rainfall` | boolean | no | must be false | Confirms dry-running domain |
| `current_lap_time_seconds` | number | no | 30–300 s | Completed current-lap time |
| `sector1_seconds` | number | yes | 5–150 s | Completed sector; null if unavailable |
| `sector2_seconds` | number | yes | 5–150 s | Completed sector; null if unavailable |
| `sector3_seconds` | number | yes | 5–150 s | Completed sector; null if unavailable |
| `previous_lap_time_seconds` | number | yes | 30–300 s | Previous consecutive clean lap |
| `previous_lap_delta_seconds` | number | yes | −120–120 s | Current minus previous lap time |

Identifier and provenance columns are retained for grouping, traceability, and
reporting. They are not automatically model features. Any categorical encoding,
scaling, or missing-value imputation must be fitted on training events only.

## Targets — Never Model Inputs

| Column | Type | Nullable | Unit/range | Definition |
|---|---|---:|---|---|
| `next_lap_time_seconds` | number | no | 30–300 s | Immediate next eligible lap time |
| `next_lap_delta_seconds` | number | no | −120–120 s | Next minus current lap time |

The target is created with a forward shift only after chronological sorting and
eligibility evaluation. A row is discarded if the next physical lap is absent,
excluded, belongs to another stint, or belongs to another driver. The pipeline
never skips an intervening invalid lap to obtain a convenient later target.

## Cleaning and Missing-Value Policy

Raw FastF1 frames are copied before normalization. Durations are converted from
timedeltas to seconds; weather units retain FastF1's published units; identifier
strings are stripped and compounds uppercased. No source cache is modified.

Each raw lap receives the first applicable primary exclusion reason:

1. duplicate driver-stint-lap key;
2. missing identity or lap time, or implausible lap time;
3. missing tyre data or non-slick compound;
4. inaccurate or deleted lap;
5. pit-in or pit-out lap;
6. missing required weather or another required feature;
7. rainfall;
8. track status other than all clear.

Both current and target laps must pass. They must also belong to a run of at
least three consecutive eligible laps, producing at least two adjacent target
pairs. Nullable sector and previous-lap values are preserved rather than
silently imputed. Their later imputation policy must be learned on training
events only.

## Split and Leakage Contract

`event_id` is the grouping key. Six events are training data, two are
validation data, and Mexico City plus Abu Dhabi are frozen test data. Automated
checks fail if an event ID receives more than one split. The test split must not
influence cleaning rules, feature choice, preprocessing, model selection, or
tuning.

Features use only the current or earlier completed laps and contemporaneous
weather. Final stint length, future flags, future weather, future positions,
future telemetry, event-wide future-derived statistics, and both target columns
are forbidden inputs.
