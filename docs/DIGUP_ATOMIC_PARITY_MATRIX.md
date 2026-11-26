# Atomic parity matrix — incomplete

This is a **partial, source-based working matrix**, not the requested exhaustive
inventory. The [coverage checklist](DIGUP_AUDIT_METHODOLOGY.md) identifies
uninspected areas. Counts of these rows are not product-wide feature counts.
See the [Desktop inventory](DIGUP_DESKTOP_ATOMIC_FEATURE_INVENTORY.md),
[Web inventory](DIGUP_WEB_ATOMIC_FEATURE_INVENTORY.md), and
[assumed capabilities](DIGUP_FEATURES_NOT_IN_DESKTOP.md).

Desktop status for every row below is **implemented in the cited source**, not
a claim of execution during this audit. Manual verification for every row is
**not verified during this audit**. UI/backend/engine columns refer to the Web
path, respectively: Y = exposed/connected in inspected source, P = partial,
N = not exposed or connected in inspected path, — = not applicable. A `Y`
does not independently establish a working end-to-end workflow.

Statuses: **V** = IMPLEMENTED AND VERIFIED within the explicitly identified
synthetic/component-test boundary; **U** = IMPLEMENTED — NOT VERIFIED;
**P** = PARTIALLY IMPLEMENTED; **M** = MISSING IN WEB; **B** = BLOCKED BY
PLATFORM; **?** = UNKNOWN / NEEDS INVESTIGATION. Historical tests were
executed in earlier implementation batches, not in this audit. `—` in the
test column means no relevant test was identified here, not that none exists.

## Source keys

- **SW** [SearchWindow.swift](../backend/engine/DigUp/Sources/DigUpApp/SearchWindow.swift);
  **SP** [SearchPanel.swift](../backend/engine/DigUp/Sources/DigUpApp/SearchPanel.swift);
  **R** [Results.swift](../backend/engine/DigUp/Sources/DigUpApp/Results.swift);
  **PV** [Previews.swift](../backend/engine/DigUp/Sources/DigUpApp/Previews.swift);
  **C** [Components.swift](../backend/engine/DigUp/Sources/DigUpApp/Components.swift);
  **E** [Engine.swift](../backend/engine/DigUp/Sources/DigUpApp/Engine.swift);
  **MO** [Moments.swift](../backend/engine/DigUp/Sources/DigUpApp/Moments.swift).
- **S** [Searcher.swift](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift);
  **SS** [SearchService.swift](../backend/engine/DigUp/Sources/digup/SearchService.swift);
  **IX** [Indexer.swift](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift);
  **CR** [Crawler.swift](../backend/engine/DigUp/Sources/DigUpKit/Crawler.swift);
  **CE** [CodeExtractor.swift](../backend/engine/DigUp/Sources/DigUpKit/CodeExtractor.swift);
  **IS** [IndexStore.swift](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift);
  **AM** [Media+Apple.swift](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift);
  **LM** [LlamaModels.swift](../backend/engine/DigUp/Sources/LlamaRuntime/LlamaModels.swift).
- **UI** [archive-shell.tsx](../frontend/src/components/archive/archive-shell.tsx);
  **GRID** [results-grid.tsx](../frontend/src/components/archive/results-grid.tsx);
  **FILTER** [result-filters.tsx](../frontend/src/components/archive/result-filters.tsx);
  **PRE** [preview-pane.tsx](../frontend/src/components/archive/preview-pane.tsx);
  **CLIENT** [archive-api.ts](../frontend/src/lib/archive-api.ts);
  **API** [archive.py](../backend/app/api/routes/archive.py);
  **AD** [supervisor.py](../backend/app/engine/supervisor.py).

## Test keys

The test names below are references, not claims that a full workflow or real
model was tested. The previous frontend batch reported 29 passing tests; the
earlier backend reason batch reported 106. No tests were run in this audit.

- **T1** [search-controls.test.mjs](../frontend/tests/search-controls.test.mjs):
  `live prefix starts immediately, final search waits 120 ms and empty queries do not search`;
  `rapid changes cancel old requests and late replies cannot replace current results`.
- **T2** [test_archive_contract.py](../backend/tests/test_archive_contract.py):
  `test_web_search_modes_map_to_original_jsonl_search_operation`,
  `test_prefix_search_uses_original_protocol_without_changing_other_options`,
  `test_real_engine_prefix_and_hybrid_fallback_use_disposable_index`.
- **T3** [search-controls.test.mjs](../frontend/tests/search-controls.test.mjs):
  `filter counts use the unfiltered strong prefix and preserve filtered result order`,
  `filter counts respect empty, weak-only and full strong boundaries`,
  `unavailable unfiltered responses do not display stale filter counts`,
  `filter counts and tooltip use the selected result limit`.
- **T4** [test_archive_contract.py](../backend/tests/test_archive_contract.py):
  `test_strong_boundary_tracks_only_retained_original_strong_hits`,
  `test_kind_filter_is_applied_by_original_engine_before_limit`.
- **T5** [test_archive_contract.py](../backend/tests/test_archive_contract.py):
  `test_match_reasons_follow_desktop_signals_and_segments`.
- **T6** [preview-pane.test.mjs](../frontend/tests/preview-pane.test.mjs):
  `match explanations are visible for every preview kind`,
  `excerpt markers render as bold text with Desktop delimiter behavior`,
  `excerpt content is escaped as text rather than interpreted as HTML`,
  `Desktop-supported media show existing excerpts and retain expansion controls`.
- **T7** [search-controls.test.mjs](../frontend/tests/search-controls.test.mjs):
  `desktop example searches populate the query and use the existing search flow`,
  `thumbnail failures stay local, recover on URL changes, and preserve result interactions`,
  `the result-limit control reports the selected limit`.
- **T8** [preview-pane.test.mjs](../frontend/tests/preview-pane.test.mjs):
  `PDF controls render requested pages and respect page boundaries`,
  `video timestamps request the chosen frame and reject out-of-range values`.
- **T9** [test_archive_contract.py](../backend/tests/test_archive_contract.py):
  `test_media_stream_supports_ranges_and_is_session_bound`,
  `test_pdf_pages_and_video_frames_use_original_render_operation`.
- **T10** [test_settings.py](../backend/tests/test_settings.py):
  `test_indexing_refuses_every_root_before_starting_process`,
  `test_sync_api_preserves_existing_synthetic_index`.
- **T11** [search-controls.test.mjs](../frontend/tests/search-controls.test.mjs):
  `final engine order replaces prefix results, preserves strong boundary and surfaces fallback`.

## Counts for the rows below only

| Rows | V | U | P | M | B | Not present in Desktop | ? |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 28 | 8 | 2 | 13 | 3 | 1 | 0 | 1 |

These are not total Desktop or Web feature counts. The nine assumed
capabilities in the separate investigation document are not included in this
table and are not classified as absent.

## Traced rows

The source/function cell names the implementation, and the final cell gives the
gap and platform constraint. `UI/API/engine` provides three distinct fields in
that order. The source keys above provide exact paths.

| ID | Category; atomic feature | Desktop source and behavior | Web status; source/function | UI/API/engine | Tests | Gap and platform constraint |
|---|---|---|---|---|---|---|
| SEARCH-001 | Search; prefix while typing | SP `queryChanged`; S `search` uses `prefixLast` | P; UI `ArchiveShell`, CLIENT `archiveApi.search`, API `search`, AD `DigUpAdapter.search` | Y/Y/Y | T1, T2 | Web lacks Desktop's speculative embed-ahead; model path remains unverified. |
| SEARCH-002 | Search; combined ranking | S `search` combines semantic z and word coverage | P; UI `ArchiveShell`, API `search`, AD `DigUpAdapter.search`, SS `handle` | Y/Y/Y | T2 | Real-model inference and ranking not established by fallback/contract tests. |
| SEARCH-003 | Search; strong boundary | S `strongCount`: score ≥ half top, or all if top ≤ 0 | V; AD `DigUpAdapter.search` retains original strong hits after authorization | Y/Y/Y | T4 | Verified adjustment only; assumes original engine boundary/order. |
| SEARCH-004 | Search; strong kind counts | SW `SearchModel.run` counts unfiltered strong prefix | V; UI `ArchiveShell`, FILTER `ResultFilters` | Y/Y/Y | T3, T4 | Limited to accessible hits and Web's selected limit; not a native browser test. |
| SEARCH-005 | Search; PDF/document grouping | R `ResultGroupKind.init` groups `.pdf` and `.doc` | V; AD `DigUpAdapter._register_hit`, UI `ArchiveShell` | Y/Y/Y | T3 | Synthetic mapping/count test boundary. |
| SEARCH-006 | Search; weaker fold | SW `SearchModel.run`, `WeakerToggle`; S `strongCount` | V; UI `ArchiveShell` | Y/Y/Y | T4, T11 | Uses received ordered hits; browser interaction not manually verified here. |
| SEARCH-007 | Results; match reason | R `ResultRow.init` and `reason`: z ≥ 2, else keyword or name | V; AD `_reason`, PRE `PreviewPane` | Y/Y/Y | T5, T6 | Synthetic signals and component rendering; real semantic model not verified. |
| SEARCH-008 | Results; bold marked excerpt | PV `WhyItMatched.body`, C `highlighted` | V; PRE `highlightedExcerpt`, `PreviewPane` | Y/Y/Y | T6 | Code placement differs: Desktop uses its code-lines preview. No full passage implied. |
| SEARCH-009 | Search; archive example chips | SW `SearchHome`, `ExampleChip` | V; GRID `ResultsGrid`, UI `ArchiveShell` | Y/—/— | T7 | Six archive examples verified as components; Desktop's conditional code example is separate and absent. |
| SEARCH-010 | Search; result limit | SW `SearchModel.run` requests 120 | P; UI `ArchiveShell`, CLIENT `archiveApi.search` | Y/Y/Y | T7 | Web maximum is 100; it is an intentional constraint. |
| PREVIEW-001 | Preview; PDF page render | PV `Previews.load`, `page` | P; PRE `PreviewPane`, API `media_preview`, AD `DigUpAdapter.render`, SS `handle` | Y/Y/Y | T8, T9 | Controls and protocol tested with fixtures; complete browser/native rendering not verified here. |
| PREVIEW-002 | Preview; mark PDF page words | PV `Previews.page` receives found/query words | M; PRE `PreviewPane`, API `media_preview`, AD `DigUpAdapter.render` request page without terms | N/Y/Y | T8, T9 | Web render contract does not send terms for page highlights. Desktop implementation uses PDFKit on macOS. |
| PREVIEW-003 | Preview; retrieve document segment text | PV `Passage.body`, E `text(ofSegment:code:)`, SS `handle` text operation | M; PRE `PreviewPane`, API archive routes show excerpt only | N/N/N | — | No Web segment-text route established; authorization and stale segment identity are unresolved. |
| PREVIEW-004 | Preview; Quick Look fallback | PV `Previews.load` calls `thumbnail` after frame/page failure | B; GRID `ResultThumbnail` uses kind icon on failure | N/N/N | T7 | Quick Look is native macOS; Web icon is not Quick Look. Server-side native substitution not assessed. |
| PREVIEW-005 | Preview; icon on failed thumbnail | SW `MomentThumbnail.body` shows `NSWorkspace` file icon | P; GRID `ResultThumbnail` | Y/—/— | T7 | Web uses generic kind icon, not the native file icon; component failure path tested. |
| PREVIEW-006 | Preview; reset on changed image identity | SW `MomentThumbnail.body` task keyed by `row.previewKey` | V; GRID `ResultsGrid`, `ResultThumbnail` keyed by URL | Y/—/— | T7 | URL-based identity differs from native preview key; no browser test this audit. |
| MEDIA-001 | Audio; decoding into windows | AM `AudioExtractor.windows`: 16 kHz mono, silence skipped; defaults in `IndexOptions` | P; AD `IndexJob.start` rejects indexing | P/N/N | T10 | Existing indexes may be searched; Web cannot start extraction. Apple path only; portable implementation not reviewed. |
| MEDIA-002 | Video; deduplicated frame sampling | AM `VideoExtractor.keyframes` samples and hashes frames with start/end | P; AD `IndexJob.start` rejects indexing | P/N/N | T10 | Web cannot start indexing; macOS path inspected, portable path not reviewed. |
| MEDIA-003 | Video; playback at matching moment | MO `PreviewPlayback.play`, PV `PlayButton.body` | P; PRE `PreviewPane`, API `media_stream` | Y/Y/— | T8, T9 | Browser/codec and actual playback not verified; test covers selected frame request and stream contract. |
| MEDIA-004 | Audio; segment location | PV `AudioMoment`, R `ResultRow.place` | P; AD `_location`, PRE `PreviewPane` | Y/Y/Y | T9 | Streaming/seek UI exists; real audio playback was not verified during audit. |
| INDEX-001 | Index; start synchronization helper | E `requestSync`, `startHelper`; IX `sync`, `run` | M; API `indexing_sync`, AD `IndexJob.start` | P/Y/N | T10 | Web returns conflict deliberately; incomplete enumeration may cause deletions. |
| INDEX-002 | Index; react to file changes | E `startWatching`, `foldersChanged`, `requestSync` | ?; Web watcher call path not fully inspected | ?/?/? | — | No Web watcher established; requires complete inspection and safe ownership. |
| INDEX-003 | Index; reconcile missing records | IX `sync`; CR `crawl` may skip unreadable subtrees | P; AD `IndexJob.start` refuses to invoke job | N/Y/N | T10 | Existing engine behavior cannot safely be initiated in Web; incomplete crawl can delete unseen records. |
| INDEX-004 | Index; finish long files incrementally | IX `finishLongFiles` processes saved page/chunk steps | P; API `indexing_backfill`, AD `IndexJob.start` | P/Y/N | — | Backfill control is not a usable new indexing workflow while starts are disabled. |
| CODE-001 | Code; extract notebook cells | CE `read`, `notebookCells` read cells and exclude outputs | P; AD `IndexJob.start` prevents Web-owned indexing | P/N/N | T10 | Existing code indexes can be searched; extraction cannot be started from Web. |
| CODE-002 | Code; split into line stretches | CE `read`, `lines` | P; AD `IndexJob.start` prevents Web-owned indexing | P/N/N | T10 | Existing code indexes can be searched; extraction cannot be started from Web. |
| STORAGE-001 | Storage; transactional index migration | IS `migrate` uses a transaction and schema version | U; SS `init` opens `IndexStore`; AD starts original service | N/Y/Y | — | Runtime migration was not executed; opening a real index may mutate it. |
| MODEL-001 | Models; locate original model files | LM `LlamaModels.locate` resolves text and optional media files | U; SS `handle` requests original encoder through service; AD `DigUpAdapter.search` | P/Y/Y | T2 | Disposable fallback tests do not prove model loading or real inference. |

## Significant observed gaps, not implementation proposals

1. Web-owned indexing is disabled because incomplete crawling can remove
   unseen rows (INDEX-001, INDEX-003).
2. Web does not retrieve the full matched document passage (PREVIEW-003).
3. Web does not mark matched words on the rendered PDF page (PREVIEW-002).
4. Native Quick Look fallback is not provided in the browser (PREVIEW-004).
5. Web requests at most 100 results rather than the Desktop window's 120
   (SEARCH-010); this is an intentional current limit.

These are supported within the inspected paths, not a ranking of all possible
gaps; uninspected areas may contain more significant differences.
