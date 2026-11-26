# DigUp atomic audit methodology and coverage

**INCOMPLETE — this is a working inventory, not the requested exhaustive audit.**
The counts in the [matrix](DIGUP_ATOMIC_PARITY_MATRIX.md) describe only the
identified rows, not either product's total feature count. Do not use the
absence of a row as evidence that a feature is absent.

## Revisions and worktree

- Original repository: <https://github.com/ARahim3/DigUp.git>; local checkout
  `backend/engine/DigUp/`, commit `dc2651ad8299160bbe91e972f857e1a1599a8419`.
  The Desktop worktree was clean when checked.
- Web: commit `c2a4b652336ae6d5956041d8dcc45380cf8c2ebf`, **plus a dirty
  worktree**. The revision alone does not reproduce this audit. Before creating
  these documents, modified files included the archive API, engine adapter,
  settings, archive components and tests; untracked files included the existing
  parity matrix, Compose, Dockerfile and a frontend test. These changes were
  already present and were not reverted.
- The historical [feature parity tracker](DIGUP_FEATURE_PARITY.md) is retained;
  its 49 broader rows are not comparable to the counts of atomic rows here.

## Evidence and status

Read implementation and call sites rather than treating names or comments as
proof. Follow UI → API → adapter → original engine where applicable. A route or
component alone is not proof of an end-to-end feature. Tests are identified by
file and test name; mocked/component tests do not establish native, browser,
model or complete workflow behavior.

The prior implementation batches reported 106 backend tests and 29 frontend
tests passing at their respective verification points. **No tests or manual
feature checks were run for this audit.** All manual-verification fields in
the current matrix therefore mean “not verified during this audit,” not “never
verified.” Historical results are not a fresh certification of this dirty
worktree.

`IMPLEMENTED AND VERIFIED` is used only for the narrow behavior supported by
the previously run focused tests, with the testing boundary stated. `IMPLEMENTED
— NOT VERIFIED` means implementation was inspected but the relevant behavior
has not been verified. `PARTIALLY IMPLEMENTED` identifies a material difference.
`MISSING IN WEB` requires affirmative Desktop evidence and a scoped Web
comparison. `BLOCKED BY PLATFORM` is reserved for an actual native operation,
not every feature that differs. `UNKNOWN / NEEDS INVESTIGATION` is used when
the available evidence cannot settle the comparison. A negative source search
is not proof of absence across uninspected code.

## Coverage checklist

“Partial” means at least some code was inspected, **not** that all files,
branches or platforms in the area were traced.

| Area | Coverage |
|---|---|
| Desktop startup and app lifecycle | Partial: `Sources/DigUpApp/App.swift`, portions of `Engine.swift` |
| Desktop UI, search, result interaction and previews | Partial: portions of `SearchWindow.swift`, `Results.swift`, `Previews.swift`, `Components.swift` |
| Desktop search engine and JSONL bridge | Partial: portions of `DigUpKit/Searcher.swift`, `Sources/digup/SearchService.swift` |
| Desktop crawl, index, rules, storage | Partial: portions of `Crawler.swift`, `Indexer.swift`, `Rules.swift`, `IndexStore.swift`, `Model.swift` |
| Desktop code and notebook extraction | Partial: portions of `CodeExtractor.swift` |
| Desktop media and native APIs | Partial: portions of `Platform/Apple/Extractors+Apple.swift` and `Media+Apple.swift`; portable implementations not traced |
| Desktop models and packaging | Partial: `ModelFiles.swift`, `LlamaModels.swift`, `Package.swift`; inference and build scripts not fully traced |
| Desktop shell, resources, scripts, tests and remaining source | **Not fully inspected**; discovery and targeted searches are not complete call-path reviews |
| Web archive UI, routes and adapter | Partial: portions of `archive-shell.tsx`, `results-grid.tsx`, `result-filters.tsx`, `preview-pane.tsx`, `archive-api.ts`, `archive.py`, `supervisor.py` |
| Web settings, identity, other routes and services | Partial: portions of `settings/service.py`, `auth/authorization.py`, `api/routes/local_auth.py`, `main.py` |
| Web tests | Test names inventoried; selected frontend test bodies inspected. Not all test bodies or fixtures traced |
| Web builds, deployment, configuration and scripts | Partial: `compose.yaml` and `frontend/Dockerfile`; other configuration and scripts not fully traced |

Consequently, the requested complete coverage of categories A–R, per-format
processing, native platforms, networking, security, and build/deployment is
**not established**. Continue source-by-source, tracing callers and tests,
before reporting whole-product counts or making absence claims.

## Safety and document map

No services were started, stopped or restarted; no indexing, migrations,
production-data access, model downloads, dependency installation or code changes
were performed for this audit. No test fixture was executed.

- [Desktop inventory](DIGUP_DESKTOP_ATOMIC_FEATURE_INVENTORY.md)
- [Web inventory](DIGUP_WEB_ATOMIC_FEATURE_INVENTORY.md)
- [Atomic comparison and scoped counts](DIGUP_ATOMIC_PARITY_MATRIX.md)
- [Commonly assumed capabilities](DIGUP_FEATURES_NOT_IN_DESKTOP.md)
