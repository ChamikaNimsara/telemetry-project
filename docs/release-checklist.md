# Version 1 Release Checklist

**Candidate prepared:** 13 September 2026

**Candidate version:** 1.0.0

**Repository:** [github.com/ChamikaNimsara/telemetry-project](https://github.com/ChamikaNimsara/telemetry-project)

**State:** Ready for project-owner review; commit, tag, and push are intentionally pending

This is the public release record for US-08. A checked item has repeatable
evidence in the repository or a validation result recorded below. The final
release actions remain unchecked until the project owner reviews this candidate
and explicitly authorizes each repository-history change.

## Scope and evidence

- [x] One primary problem, user, and decision context are explicit.
- [x] Target, baselines, metrics, and success threshold are recorded.
- [x] Assumptions, exclusions, and limitations are visible.
- [x] Headline claims link to machine-readable metrics, tables, or reports.

Evidence: [`docs/problem-definition.md`](problem-definition.md),
[`reports/model-report.md`](../reports/model-report.md), and the README evidence
map.

## Reproducibility and data integrity

- [x] Python 3.12, uv 0.12.13, installation, and commands are documented.
- [x] Direct and transitive dependencies are locked.
- [x] Source identifiers, event membership, retrieval method, and schema are
  recorded.
- [x] Raw inputs remain immutable and ignored; derived datasets are rebuildable.
- [x] Train, validation, and test events are disjoint and checked automatically.
- [x] Feature availability and leakage controls are documented and tested.
- [x] No private local path is required.

Evidence: `uv.lock`, [`configs/events.yaml`](../configs/events.yaml),
[`data/manifests/event-manifest.json`](../data/manifests/event-manifest.json),
[`data/manifests/split-manifest.json`](../data/manifests/split-manifest.json), and
[`docs/data-dictionary.md`](data-dictionary.md).

## Model and reporting

- [x] Explainable baselines and the selected method use the same eligible rows
  and metrics.
- [x] Candidate selection used training and validation only.
- [x] Final evaluation used the frozen held-out events once.
- [x] Aggregate, event, condition, robustness, and physical-range results are
  reported.
- [x] Claims do not overstate causality, physical tyre wear, or generalization.
- [x] Figures include titles, units, scope, captions, and accessible styling.

Evidence: [`configs/final-model.yaml`](../configs/final-model.yaml),
[`reports/final-test-metrics.json`](../reports/final-test-metrics.json), and
[`reports/model-report.md`](../reports/model-report.md).

## Software and publication hygiene

- [x] Maintained workflow logic is under `src/` and exposed through one CLI.
- [x] Formatting, linting, strict typing, tests, and coverage gate pass.
- [x] A small FastF1 smoke workflow is documented and tested with local fakes.
- [x] Required public files, local Markdown links, version consistency, secret
  patterns, private paths, notebook output, and file sizes are audited.
- [x] Raw cache data, processed rows, predictions, secrets, models, and private
  planning files are excluded from the candidate.
- [x] MIT code license, data-use boundary, contribution guide, citation
  metadata, and source attribution are present.
- [x] A clean candidate checkout installs and passes the offline quality suite.

Evidence: [`reports/release-audit.json`](../reports/release-audit.json),
[`LICENSE`](../LICENSE), [`CONTRIBUTING.md`](../CONTRIBUTING.md), and
[`docs/data-sources.md`](data-sources.md).

## Release authorization

- [ ] Project owner has reviewed and accepted the complete working-tree diff.
- [ ] The reviewed release commit has been created with explicit approval.
- [ ] Version `1.0.0` has been tagged and pushed with explicit approval.
- [ ] The public URL and GitHub-rendered documentation have been checked after
  publication.

These are process gates, not missing implementation. They cannot be completed
before the review handoff required by the repository policy.

## Validation record

The release candidate passed the following checks on Windows with Python
3.12.14 and uv 0.12.13:

| Check | Result |
|---|---|
| `uv lock --check` | 55 packages resolved; lock valid |
| `ruff format --check .` | 57 files already formatted |
| `ruff check .` | Passed |
| `mypy src tests` | Passed for 46 source files |
| `pytest` | 103 passed; 91.05% branch-aware coverage |
| `release-audit` | 8/8 checks passed across 95 candidate files |
| Isolated candidate setup | Installed 55 locked packages; version 1.0.0 |
| Isolated candidate suite | Same lint, type, 103-test, coverage, and audit results |
| Isolated cached acquisition | 10/10 events; 11,464 raw laps; no failures |
| Isolated dataset build | 9,682 samples; SHA-256 `08705dff…b6d6834` |
| Isolated development analysis | 7,843 rows; correlation 0.991850; persistence MAE 0.424463 s |
| Isolated baseline evaluation | Training-median validation macro-event MAE 0.419979 s |
| Isolated model selection | Pace reversion selected at 0.368813 s validation MAE |
| Isolated final evaluation | 0.317689 s test MAE; 9.215114% over stronger baseline |
| Package build | Version 1.0.0 sdist and wheel built; private/data paths absent |
| Public remote reachability | `origin/main` resolved successfully before publication |

Commands executed:

```shell
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python -m telemetry_project.cli release-audit
```

The clean-checkout test repeated installation, the offline quality suite, cached
acquisition, dataset construction, analysis, baseline evaluation, selection,
and final evaluation from a new directory containing only the public release
candidate. Previously acquired FastF1 responses were supplied as an external
read-only cache; a new contributor can populate the same cache with the
documented online acquisition command. Online reacquisition is not repeated as
part of every audit because it depends on an external service and overwrites
time-stamped manifests.

## Known release limitations

- External FastF1 availability cannot be guaranteed by this repository.
- Underlying Formula 1 timing data is not redistributed or licensed by the MIT
  software license; contributors reacquire it for permitted use.
- The empirical claim is limited to ten 2024 races, with only two final test
  events and sparse soft-compound coverage.
- Version 1 is offline analytical support, not a real-time or safety-critical
  system.
