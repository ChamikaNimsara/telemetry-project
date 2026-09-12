# Data Sources, Provenance, and Use Constraints

**Applies to:** US-03 acquisition and all downstream datasets
**Reviewed:** 13 September 2026

## Source Overview

This project uses FastF1 3.8.3 to acquire Formula 1 session metadata and lap
timing. FastF1 describes itself as an unofficial Python package for results,
schedules, timing, and telemetry. Its maintainer explains that FastF1 combines
multiple sources, primarily the F1 live-timing API plus historical information,
and may correct, calculate, align, or augment some values.[^1]

Consequently, a FastF1 table is not a verbatim single-source record. Published
analysis must identify the FastF1 version, configured event, resolved source
path, retrieval time, and relevant generated/corrected-data indicators.

## Feeds Acquired in US-03

The initial acquisition command calls `Session.load` with:

```text
laps=True, telemetry=False, weather=False, messages=False
```

This loads the timing and metadata required to validate the approved event
scope without downloading the much larger car-telemetry feed. Weather,
race-control messages, and telemetry will be enabled deliberately in later data
work only when their fields and quality checks are specified.

The raw FastF1 request cache is stored under `data/raw/fastf1-cache/` by default.
It is excluded from Git and must not be redistributed through this repository.

## Acquisition Manifest

`data/manifests/event-manifest.json` is the versioned audit record. It contains:

- manifest schema and FastF1 versions;
- acquisition timestamp and online/offline cache mode;
- event-configuration path and SHA-256 fingerprint;
- requested and resolved event/session identifiers;
- FastF1 source path, round, country, location, and event date;
- split assignment, row count, returned columns, and required columns;
- FastF1 warnings emitted while resolving or loading each event;
- success or failure status with an actionable error type and message;
- aggregate request, success, failure, and lap counts.

A failed event remains in the manifest. The batch continues so one unavailable
session cannot hide the status of all other requested sessions.

## Reproducing Acquisition

Install the locked environment, then acquire all approved events:

```shell
uv sync --locked --dev
uv run python -m telemetry_project.cli acquire
```

Acquire one configured event for a small validation run:

```shell
uv run python -m telemetry_project.cli acquire --only-event Bahrain
```

After a successful online acquisition, prove the raw inputs are cached by
running without network access:

```shell
uv run python -m telemetry_project.cli acquire --only-event Bahrain --offline
```

The command exits with status 0 when all requested events pass, 1 when the
manifest is written with one or more event failures, and 2 for invalid command
configuration or an unwritable manifest.

Re-running online acquisition uses FastF1's cache where valid. The manifest
timestamp changes because it describes the new verification run; source IDs,
row counts, columns, and the configuration fingerprint provide the comparison
points.

## Data Integrity Limitations

- Source fields and availability can vary by event and FastF1 version.
- FastF1 can correct or augment timing values; `FastF1Generated` and related
  quality fields must be retained and audited.
- Reported tyre age can include earlier use of the same set and must not be
  reconstructed by assuming every stint begins at tyre life one.
- Relative compound labels do not identify the underlying C1–C5 construction.
- Successful acquisition confirms identity, required columns, and non-empty
  data; it does not certify analytical fitness. US-04 performs the detailed
  missingness, range, consistency, and exclusion audit.

## Rights and Publication Controls

FastF1's source code is distributed under the MIT license, but that software
license does not grant a license to the underlying timing or race data. FastF1
also states that it is unofficial and not associated with the Formula 1
companies.[^2]

Formula 1's current legal notices state that site material, including live
timing and historical race data, is protected and generally supplied for
personal, non-commercial use. The education guidance permits limited personal
study and research uses but restricts reproduction and commercial or
promotional use.[^3] Formula 1's separate brand guidelines restrict logos and
explain the conditions for editorial use of permitted word marks.[^4]

Project controls are therefore:

- use acquired data locally for private, educational analysis only unless
  broader rights are confirmed;
- do not commit or publish raw FastF1/F1 cache responses or bulk reconstructed
  datasets;
- publish only the minimum derived statistics and original visualizations
  needed to explain the work, subject to a pre-release rights review;
- attribute FastF1 and Formula1.com where applicable;
- do not use F1 logos or imply endorsement, affiliation, or official status;
- re-check the current source terms before any public release, commercial use,
  dataset sharing, or model-artifact publication;
- obtain permission or qualified advice if the intended release exceeds the
  clearly documented personal educational scope.

This document records conservative project controls and is not legal advice.
If the rights review does not support the planned public ML portfolio, the
project must switch to a suitably licensed source or change what is published.

## Sources

[^1]: [FastF1 discussion — source composition and data corrections](https://github.com/theOehrly/Fast-F1/discussions/634), maintainer response, accessed 13 September 2026.
[^2]: [FastF1 repository and notice](https://github.com/theOehrly/Fast-F1), accessed 13 September 2026.
[^3]: [Formula 1 Legal Notices](https://www.formula1.com/en/information/legal-notices.7egvZU48hzrypubGBNcQKt), accessed 13 September 2026.
[^4]: [Formula 1 trademark and intellectual-property guidelines](https://www.formula1.com/en/information/guidelines.4EOKE9RRqevL4niTK9kWyt), accessed 13 September 2026.
