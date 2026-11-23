# Stage 4B — parity baseline and contract coverage

**Scope:** contract verification only; no route, schema, frontend, authentication, or DigUp engine implementation changes.  
**Engine pin:** `dc2651ad8299160bbe91e972f857e1a1599a8419`.  
**Feature-gap source:** [`digup-desktop-web-complete-parity-audit.md`](digup-desktop-web-complete-parity-audit.md).

## Baseline

The web adapter currently exposes the following subset of the original engine/service operations:

| DigUp operation/capability | HTTP exposure | Frontend use | Verification status |
|---|---|---|---|
| `status` | `GET /api/engine/status` | Engine health/status popover | Route and contract covered; real helper startup is covered by the existing integration test, subject to runtime availability. |
| `search` with `meaning=false` | `POST /api/search`, mode `keyword` | Search mode selector | Adapter mapping covered; full indexing/search integration currently blocked by llama context initialization (details below). |
| `search` with `meaning=true` | `POST /api/search`, mode `hybrid` | Search mode selector | Adapter mapping covered; no semantic-only mode is exposed. |
| `summaries` (`code=false`) | `GET /api/indexing/status` | Indexing status/toolbar summary | Route and shape covered; code summaries are not exposed. |
| IndexService start (`--backfill --linger 0`) | `POST /api/indexing/sync` | “Index sources” | Existing integration starts and scans, but did not reach file processing in this run. |
| IndexService stdin `stop` | `POST /api/indexing/stop` | Stop active job | Route exists; the real integration currently fails before reaching its later assertions. |
| `render` image/PDF/video frame | Preview and frame routes | Image/PDF/video still preview | Existing integration contains image/video preview checks after indexing; blocked before those checks in this run. |
| Search-hit metadata | `GET /api/media/{handle}` | Selected result details | Existing integration contains metadata assertion; blocked before it in this run. |
| Original media download | `GET /api/media/{handle}/download` | Download original | Existing integration contains download assertion; blocked before it in this run. |
| SearchService `text`, `prewarm`, `folders` mutation, `summaries(code=true)`, estimate/model download | No HTTP exposure | None | Not exposed by current adapter/frontend. These remain audit-identified gaps, not failed HTTP tests. |
| Code search / separate `code.sqlite` | No HTTP exposure | None | Not exposed; current request schema explicitly excludes code. |
| Audio/video source playback and range streaming | No HTTP exposure | None | Not exposed; render provides still images only. |
| Watcher, schedule, pause/resume | No equivalent HTTP lifecycle | None / manual sync only | Not exposed by current web adapter. |

The HTTP contract is **not** the complete desktop feature set. It is a deliberately narrower mapping to already connected operations. Keyword and hybrid map to the original SearchService `search` operation with `meaning=false` and `meaning=true` respectively. The browser does not provide a semantic-only mode, code query flag, path argument, or upload path.

## Automated coverage added

`backend/tests/test_archive_contract.py` adds dependency-free `unittest` contract checks using the already-installed FastAPI/Pydantic stack. It verifies:

- The archive route/method inventory in generated OpenAPI against the Stage 3A API contract.
- Frontend API client endpoint references exist in backend OpenAPI.
- Search modes and kinds stay within currently supported API values; code and semantic-only are not accepted.
- Search hit fields in OpenAPI agree with the frontend `SearchHit` type, and frontend search mode values agree with the backend.
- Search response and metadata response fields agree with the frontend types (the metadata response is currently assembled inline by the route rather than declared as a Pydantic schema).
- The adapter maps hybrid and keyword requests to the original JSON-lines `search` operation with the expected `meaning`, `kinds`, `limit`, and `prefix_last` fields.
- Search results returned to the browser contain opaque IDs and omit source absolute paths.

The existing `backend/tests/test_archive_api.py` remains the real engine integration test. It covers a disposable text/image/video dataset; actual indexing; keyword/hybrid results; image and video frame preview; metadata; download; invalid requests/handles; concurrent search requests; and SearchService shutdown/restart. It is not replaced by mocks. Auth database and OIDC tests are also run by the complete backend suite but are outside this parity scope.

Run focused contract tests from `backend/`:

```sh
PYTHONPATH=. .venv/bin/python -m unittest tests.test_archive_contract -v
```

Run the complete backend suite from `backend/`:

```sh
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

The full archive integration requires the pinned release CLI, the approved model files, and a host where llama.cpp can allocate its configured context. The test uses a temporary directory under `backend/tests` and does not use a real archive index or media.

## Results in this run

- Focused contract suite: **7 tests passed**.
- Full backend suite: **35 tests run; 34 passed, 1 failed** (the 7 new contract tests and all authentication tests passed).
- Failure: `ArchiveApiIntegrationTests.test_index_search_preview_metadata_download_concurrency_and_restart` started IndexService and scanned five disposable entries. The original service emitted a fatal error before processing: `worker error: can't create a llama.cpp context`. No HTTP-result assertions after indexing (real search, preview, metadata, download, concurrency, restart) completed in this run.
- Authentication database and authentication tests in that same suite passed. They were not modified by this milestone.

This is a runtime/environment failure, not evidence that indexing/search passed. The failing integration currently prevents a fresh end-to-end claim for this run. The suite does not alter the pinned engine or attempt to change model/runtime settings to work around it.

## Non-goals and open capability gaps

No missing feature was implemented. In particular, this milestone did not add code search, root/source administration, folder/type exclusions, estimates, model controls, segment text retrieval, PDF navigation, audio/video streaming, persistent jobs, a watcher, pause/resume, schedules, or browser equivalents for native open/Finder/Quick Look/drag actions. Refer to the audit’s prioritized roadmap before authorizing any of those.

