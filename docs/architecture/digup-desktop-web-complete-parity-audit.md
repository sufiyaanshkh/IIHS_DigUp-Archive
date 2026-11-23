# DigUp Desktop → IIHS Media Archive web parity audit

**Audit date:** 2026-11-22  
**Source audited:** `backend/engine/DigUp` at `dc2651ad8299160bbe91e972f857e1a1599a8419`  
**Web code audited:** `frontend/src` and `backend/app`  
**Scope:** source and current implementation comparison only. No application code, upstream source, data, index or cache was changed.

## Executive summary

The reusable product core is already separated from DigUp's native desktop shell. `DigUpKit`, `LlamaRuntime`, and the `digup` executable contain crawling, extraction, indexing, embedding, SQLite/FTS5 storage, ranking and JSON-lines helper protocols. The macOS `DigUpApp` and the Tauri shell wrap those capabilities with platform-specific windows, menus, shortcuts, file pickers, file-opening actions, settings, update UI and lifecycle management.

The web adapter is already calling the pinned original `digup search-service` and `index-service`. It preserves the original index schema and model/search implementation. The Next.js screen supports live backend health/status, keyword and hybrid search, kind filters, result selection, a details pane, image/PDF/video-frame preview, download, and manual start/stop indexing for server-configured roots. It does not yet provide full desktop parity: settings and root administration, code search, richer preview playback/navigation, desktop actions, first-run onboarding, live watcher behavior, complete per-folder progress and several native lifecycle policies are absent or only represented partially.

“Reuse directly” below means reuse the existing DigUp executable/service protocol without changing core code. The web server is not importing Swift modules into Python; the boundary is the original JSON-lines process protocol.

## 1. Architecture and source map

### Original application

```text
Mac SwiftUI/AppKit shell                     Windows/Linux Tauri WebView shell
SearchPanel / SearchWindow / Settings         HTML + CSS + vanilla JS + Tauri commands
                  \                            /
                   CLI helpers (`digup`)
                  ├─ search-service (persistent JSONL)
                  ├─ index-service (JSONL events + stdin commands)
                  ├─ worker / model / download / status commands
                  └─ DigUpKit + LlamaRuntime
                       ├─ Crawler / Rules / Indexer / extractors
                       ├─ Searcher / FTS5 / Float16 vectors
                       └─ EmbeddingGemma 2 via llama.cpp
```

The audited `Package.swift` defines `DigUpKit`, `LlamaRuntime`, the `digup` executable and tests for the portable/core targets. The macOS-only `DigUpApp` product depends on Sparkle 2.10.0; its SwiftUI/AppKit implementation is not a browser frontend. The current web app communicates with the executable through FastAPI and the original helper protocols.

### Core source map

| Concern | Original source | What it does |
|---|---|---|
| CLI and command dispatch | `backend/engine/DigUp/Sources/digup/main.swift` | `digup` commands and arguments; builds services around the original indexer/searcher. |
| Search service | `.../Sources/digup/SearchService.swift` | Persistent JSON-lines search, text, rendering, summaries, reload and status operations. |
| Index service | `.../Sources/digup/IndexService.swift` | Crawl/sync/index lifecycle, stdin control commands and progress events. |
| Background worker | `.../Sources/digup/WorkerService.swift`, `.../Sources/DigUpKit/Worker.swift` | Isolated model/embedding work and worker lifecycle. |
| File selection and crawl | `.../Sources/DigUpKit/Rules.swift`, `Crawler.swift`, `FolderSelection.swift` | Supported types, project/cache/secret exclusions, roots and metadata-only traversal. |
| Extraction | `.../Sources/DigUpKit/Extractors.swift`, `MediaExtractors.swift`, `OfficeText.swift`, `CodeExtractor.swift`, `Platform/` | Text, image, OCR, PDF, audio, video, office and code extraction. |
| Index/reconciliation | `.../Sources/DigUpKit/Indexer.swift` | Syncs roots, prioritizes new files, stores outcomes, finishes large PDFs/docs in later steps. |
| Index storage | `.../Sources/DigUpKit/IndexStore.swift`, `Database.swift`, `Model.swift`, `Vectors.swift` | Schema v5, FTS5, file/segment records and normalized Float16 vectors. |
| Search/ranking | `.../Sources/DigUpKit/Searcher.swift`, `SearchText.swift` | Exact keyword + vector ranking, modality normalization, query kind hints, excerpts and locations. |
| Model and embedding | `.../Sources/LlamaRuntime/LlamaEmbedder.swift`, `LlamaModels.swift`, `.../Sources/DigUpKit/ModelFiles.swift` | Pinned EmbeddingGemma 2 files, text/image/audio embedding and model loading through llama.cpp. |
| Preview rendering | `.../Sources/DigUpKit/PreviewImages.swift`, `SearchService.swift` | JPEG render of image/PDF page/video frame to index preview cache. |

### Desktop shell source map

| Concern | Source |
|---|---|
| macOS app startup, app/window lifecycle | `Sources/DigUpApp/App.swift`, `AppController.swift`, `Engine.swift` |
| Shared UI state and status text | `AppModel.swift`, `Engine.swift`, `Estimates.swift` |
| Main floating search and larger results window | `SearchPanel.swift`, `SearchPanelView.swift`, `SearchWindow.swift`, `SearchWindowController.swift`, `Results.swift`, `ResultGroupKind.swift`, `SearchPhase.swift` |
| Preview/player/Quick Look and thumbnails | `Previews.swift`, `QuickLookMoment.swift`, `Thumbnails.swift`, `Moments.swift` |
| General/Folders/Code/Storage preferences | `SettingsWindow.swift`, `AppSettings.swift`, `SettingsTab.swift`, `CodeFolders.swift`, `CodeEditors.swift` |
| Onboarding and folder selection | `Onboarding.swift`, `OnboardingController.swift`, `AddFolders.swift`, `AddFoldersController.swift`, `FolderChoices.swift` |
| Background indexing policy | `FolderWatcher.swift`, `PowerPolicy.swift`, `IndexSchedule.swift`, `StatusMenu.swift` |
| Global keyboard shortcut | `Hotkey.swift` |
| Model acquisition and updates | `ModelDownload.swift`, `Updates.swift` |
| Diagnostics/snapshots | `DebugHooks.swift`, `Snapshot.swift`, `AppLog.swift` |

Windows/Linux shell modules include `shell/ui/{panel,window,results,setup,settings,shortcut}.{html,js,css}` and `shell/src-tauri/src/{main,helper,settings,status,watcher,hotkey,options,code,editors,moments,hours,launch,clipboard,updates,tray_icon,wayland}.rs`. `window.js` includes home/example queries, counts, filters, result grid and preview state; `panel.js` implements the compact keyboard-navigable panel with immediate prefix keyword results and meaning results after 120 ms. `setup.js` implements source folder/subfolder selection, estimates and first-run model/setup progress. Tauri settings use a JSON file in the platform config directory (`Settings::load/save`), unlike macOS `UserDefaults`.

The Windows/Linux shell is present at `backend/engine/DigUp/shell/ui/` and `shell/src-tauri/`. It is HTML/CSS/vanilla JavaScript in a Tauri WebView, with Rust commands in `src-tauri/src/main.rs` bridging to the helper processes. The Mac has a separate SwiftUI/AppKit shell. The UI files are not copied into Next.js, but the browser-facing Tauri pages provide the closest interaction reference for a web replacement.

Tauri UI entry points are `shell/ui/panel.html` (search panel), `window.html` (larger results/home window), `setup.html` (first-run folder choice/estimate/model setup) and `settings.html`. `panel.js`, `window.js`, `results.js`, `setup.js`, `settings.js` and `shortcut.js` own page state and interactions using DOM/event handlers; Tauri's `window.__TAURI__.core.invoke` and events bridge UI commands. `src-tauri/src/main.rs` defines the command boundary and owns helper processes, persistent settings, tray/window management and watchers. There is no React-style frontend state framework in this shell.

## 2. Desktop feature inventory and current parity

Legend: **Implemented** means present in current web code; **Partial** means a useful subset; **Missing** means no equivalent found in the audited web code. “Core reused” describes the engine operation, not reuse of a desktop view.

| Desktop capability | Original implementation/core reuse | Current web status | Browser adaptation / gap |
|---|---|---|---|
| Search panel and larger results window | SwiftUI/AppKit views call `SearchService`; core search reusable | **Partial** — one responsive archive shell at `/archive`; no separate compact search panel/full-window transition | Keep the approved archive shell. If a compact mode is wanted for parity, make it a responsive web view state, not a native-window clone. |
| Search-as-you-type, fast keyword and meaning follow-up | SearchService supports keyword/meaning options; Searcher implements original ranking | **Partial** — 350 ms debounce and one request per selected Keyword/Hybrid mode | Original macOS UI can show rapid keyword results followed by hybrid meaning. Current web calls the mode selected; reproducing two-phase updates needs an adapter/UI sequencing change while keeping engine search unchanged. |
| Search modes | SearchService supports `meaning` boolean; original UI uses words then meaning/hybrid behavior | **Partial** — Keyword and Hybrid only; backend deliberately does not expose semantic-only mode | Keep Keyword/Hybrid. Do not add semantic-only unless an original supported request path is verified and deliberately exposed. |
| Natural-language multimodal search | Searcher + EmbeddingGemma vectors in original SQLite | **Implemented** for supported configured roots via original search-service | Existing server-dependent limitation: the model availability endpoint checks files, not successful model initialization. |
| Exact words, multilingual search, query kind hints | DigUp FTS5 normalization and Searcher query logic | **Implemented through original engine**, but UI does not expose ranking explanations in full | Display existing `reason`, excerpt, and locations; do not duplicate ranking in frontend. |
| Result kind filters/counts | Original kinds/grouping and root summaries | **Implemented** — All, screenshots, images, documents, video, audio filters/counts are computed from returned hits | Counts currently describe returned hits (limited search response), not guaranteed whole-index totals. |
| Result selection and keyboard navigation | Up/down, Enter, Space and platform actions in `SearchPanel`/`SearchWindow` | **Partial** — click selection and preview pane; no verified arrow/Enter/Space parity | Add accessible keyboard selection only after checking all interactions with search field/filter and browser shortcuts. |
| Match grouping/strong vs weaker groups | `Searcher` returns `strong`; desktop result views group hits | **Partial** — backend response carries `strong`, web shell does not use it to separate groups | UI can render the engine-provided distinction; preserve engine ranking and never infer new score cutoffs in browser. |
| Result-card preview | Original thumbnails and previews | **Partial** — image preview image; PDF/image/video use returned render endpoint, but grid itself uses general cards/icon presentation | Current actual preview pane supports a still preview; richer thumbnails/grid treatment remains. |
| Image preview and metadata | Original image renderer and indexed pixel/date metadata | **Partial** — selected image preview/metadata and download; not the full desktop zoom/open interactions | Add fit/zoom only if supported by reference and needed; no filesystem paths to browser. |
| PDF page preview and text passage | `SearchService render` for a PDF page plus `text` for segment excerpt | **Partial** — PDF page image via render; excerpts and metadata shown; no PDF document viewer/page navigation or complete passage fetch UI | Current API picks page 1 for filename-only matches; location match is represented. Could expose original `text` operation to render exact matching passage where hit segment permits. |
| Audio listening preview/timeline | Original extraction stores segment times; Windows/Linux Tauri uses an HTML `<audio>` player sourced from its local-file URL and a seekable moment bar; macOS shell provides audio preview controls | **Missing** — audio icon/metadata and original download only; no player or seek endpoint | DigUp does not expose audio bytes through `render`; a browser-server implementation needs authorized, range-capable streaming over an opaque handle. |
| Video preview and moment | SearchService video-frame render; Tauri embeds HTML `<video>` using the local-file URL with the hit timestamp; macOS shell has location-aware preview/open behavior | **Partial** — selected still frame via `/frame?at=...`; location text; no video playback or scrubbing | A dedicated range-capable source stream endpoint is needed for HTML video, protected by opaque handle/root validation; frame API alone is not video playback. |
| Document preview | Text chunk/page excerpts from Searcher; native Quick Look/open | **Partial** — excerpt/metadata and download; no document-specific formatted preview, passage context panel or viewer | Expose only original content/render operations that exist. For browser display, add a safe server response over an opaque hit handle; do not make the browser supply paths. |
| Code search and code index | Separate `code.sqlite`, `CodeExtractor`, `code:` query mode, line/cell locations | **Missing** — API kind enum and SearchRequest exclude `code`; current web has no code index control/search UI | Extend adapter to map explicit code search to original code-root/search-service behavior; keep separate code index and original `code:`/prompt semantics. UI must identify code results and line/cell location. |
| Open result in native app / at PDF page, video moment or code line | App-specific openers and editor integrations in desktop shell | **Missing** — server cannot invoke a user's client app; web offers download | Browser equivalent is preview/download. Do not promise direct client-app opening. Browser file handlers are user-controlled and not a reliable parity API. |
| Show in Finder/Explorer/file manager | Native shell action | **Missing by design** for a central server | No meaningful remote browser equivalent; use a safe source label/path-relative breadcrumb only. Never expose absolute server paths. |
| Quick Look / Space preview | Native platform service in desktop shell | **Missing** | Browser preview panel is the closest existing equivalent. Keep download as explicit action. |
| Copy/drag original file | Desktop clipboard/drag of filesystem item | **Missing** | Browser cannot emit a server file path as a local file. Optional user-initiated download is the safe equivalent. |
| Folder chooser/onboarding and time estimates | Desktop native folder picker, subfolder selection, estimates and onboarding | **Missing** in current archive flow | For centrally hosted service, browser cannot pick server folders. Replace only with admin/operator-managed source registration against server-approved mounts. Estimate API exists in CLI; no browser endpoint currently exposes it. |
| Search roots add/remove/selected subfolders | `FolderSelection`, settings and helper `folders` operation | **Missing** in HTTP API; roots come from `IIHS_DIGUP_ROOTS` | Add server-side source configuration UI/API with strict allowlisted mount IDs, authorization and server path resolution. Never accept arbitrary client paths. |
| Excluded folders and extensions | `AppSettings` + Crawler/Rules/IndexOptions | **Partial** — current backend has configured roots only; browser cannot configure exclusions | Preserve DigUp settings semantics and drive `folders`/index helper options where supported; avoid index/schema changes. |
| Per-root progress/status and skipped reasons | SearchService `summaries`; desktop folder rows/reason popovers | **Partial** — backend maps counts and safe root basenames; toolbar shows aggregate counts/recent events; no folder details/reason explanations in UI | Add root list and reason mapping using existing summary fields without leaking absolute paths. Current backend event retention is bounded. |
| Start indexing | Original `IndexService` | **Implemented** — POST `/api/indexing/sync`, one configured-root job | Trigger is server-wide; currently no permission gate (auth is not in scope of this audit but must precede production exposure). |
| Stop / pause / resume indexing | IndexService supports stop and backfill controls; desktop exposes pause/resume via tray/settings | **Partial** — web exposes stop only. No pause/resume endpoint/UI | Adapter can send original service controls if its process lifecycle permits; be precise that HTTP process currently ends at completion with `--linger 0`, unlike desktop's long-lived watcher. |
| New-file prioritization and backfill | IndexService; new files prioritized, later backfill | **Partial** — manual sync runs `--backfill`; `IndexJob` maps progress. No distinct user-controlled backfill toggle or ongoing new-file job | Keep engine order. A persistent server-side scheduler/watch mechanism would be new adapter lifecycle, not a new indexer. |
| Live filesystem updates | macOS FSEvents watcher; Tauri/platform watcher in desktop integration | **Missing** — web starts explicit one-shot sync; no watcher process registered in FastAPI | A server filesystem watcher/scheduled sync is needed for “new file searchable shortly” parity. Must monitor only approved roots and avoid duplicate jobs. |
| Search/index process supervision and restart | Desktop `Engine` controls helper lifecycle; original helper processes | **Implemented partially** — FastAPI persistent SearchService ID-multiplexer and one IndexJob; startup is lazy, status and graceful shutdown/restart behavior are described/tested in Stage 3 docs | In-memory handles/job state and one-process-per-index assumptions do not survive API restart or multi-worker deployment. Preserve singleton ownership or add explicit shared coordination before scaling. |
| Model download, verify, choose files, progress | Original `ModelDownload`, `FileFetcher`, pinned hashes | **Missing** in web UI/API | For centrally managed host, model acquisition/verification is deployment/operations concern. Do not expose model upload to normal browser users. Health “available” only checks file existence. |
| Model load/prewarm/idle status | SearchService `prewarm`, encoder events and idle timer | **Partial** — health/status tells running/encoder; no explicit prewarm UI/control or detailed idle progress | Could expose existing `prewarm` operation as an operator action only if product need is established; not necessary for current feature parity first pass. |
| General settings: shortcut/login item/updates | native app mechanisms | **Missing / not applicable** to a browser session | Browser cannot register OS-wide shortcut, OS login item, or updater. A site-level shortcut/help action and normal web deployment update mechanism are replacements, not exact equivalents. |
| Storage settings and local privacy wording | native paths, index size, model info, privacy summary | **Partial** — backend reports engine counts/model file presence; no settings screen for locations/sizes | Central host requires operator-facing storage health and capacity/retention status. Server storage paths remain private; UI can show labels and sizes, not arbitrary filesystem paths. |
| Auto updates | Sparkle/macOS and platform packaging update mechanisms | **Missing / deployment concern** | Replace with standard controlled application deployment/rollout; no in-app updater for a centrally deployed browser app. |
| Pause constraints: battery, thermal state, Low Power Mode | macOS IOKit/process state via `PowerPolicy` | **Missing / not portable** | Server policies need server CPU/GPU/load/maintenance controls. Do not carry laptop battery/thermal settings into centralized web settings. |
| Index hours schedule | `IndexSchedule` and `IndexHours`, event-driven local-time boundaries | **Missing** in web adapter/UI | A server scheduler can preserve configurable hours if needed; define service timezone and DST behavior before implementing. Original treats same start/end as all day and handles overnight. |
| Folder size/time estimate and indexing costs | `Estimator`, `MeasuredCosts`, onboarding/setup | **Missing** in HTTP API/UI | Could surface existing estimator via CLI/API after confirming command contract; avoid fabricating estimates. |
| Error, skipped, failed and long-file reporting | index file state/detail + `summaries`; desktop popovers | **Partial** — web receives latest 100 sanitized events and per-root counts; recent file list only displays six; limited direct reason display | UI can expose safe original notes/statuses and summary reasons. Do not reveal raw helper stderr or absolute paths. |
| Private/local-only behavior | original desktop keeps files/index locally and no user accounts | **Changed by deployment model** | Central hosting necessarily moves processing to IIHS infrastructure. Communicate that media stays within authorized host boundary; verify retention, access, backups, network access and model download policy. |

## 3. Search, indexing, extraction and storage details

### Search and ranking

`Searcher` retrieves keyword candidates from SQLite FTS5 and compares available vectors in a 768-dimensional Float16 representation. It normalizes scores across text/image/audio modalities, combines meaning and word evidence, uses a default meaning separation gate (`zGate` 2.0) and a complete-query-word bonus (default 2.0; code uses its own weighting), applies soft kind hints, and returns a best segment/location plus excerpt. It handles separate code queries/indexes and language normalization. Query kinds such as “in a video” are hints/boosts, not hard filters. The current HTTP API passes `meaning=false` for Keyword and `true` for Hybrid; it sends kind filters/limit to the actual SearchService.

### Index pipeline

`Crawler` traverses configured roots and records file metadata/classification without reading every file during the walk. `Rules` rejects unsupported types and protected/secret files, excludes hidden/cache/developer locations, distinguishes project content from code mode, and prevents indexing cloud-only placeholders where the platform can identify them. `Indexer.sync` reconciles path/size/mtime/inode/device against the index, queues new/changed/moved files, and prunes files outside current roots when configured. The processing pipeline reads and embeds jobs in batches, overlaps preparation with model work, commits transactionally, reports per-file states and later completes long PDF/document work in steps. `IndexService` gives newly found files priority before backfill and supports stop/backfill controls.

### Supported categories verified in source

The core kinds are screenshot, image, PDF, document, audio, video, plus code in its separate index. Desktop README states image and audio formats broadly (“and more” / “any length”) rather than listing every accepted codec. `Rules.swift` has the exact document extension set and code rules; actual image/media decode acceptance is delegated to the platform decoder and installed ffmpeg libraries/tools, so extension alone cannot establish a successful decode.

| Category | Source-confirmed extraction and indexing | Platform differences / limitations |
|---|---|---|
| Image/screenshot | Image downscale and dimensions; EXIF `DateTimeOriginal`; image embedding. Screenshot detection by macOS xattr/name, screenshot folder/name heuristics elsewhere. Screenshot OCR text enters keyword search only. | macOS ImageIO/AppKit supports HEIC, RAW, WebP and more; macOS SVG uses AppKit drawing. Portable Linux/Windows uses stb, then ffmpeg for formats stb cannot decode; portable source explicitly says RAW is not supported and SVG is not drawn. Portable OCR is currently unavailable. Image-size threshold is 256px minimum side. |
| PDF | PDF page text or rendered-page image when text is sparse/scanned/slides; page location; OCR/garbled-text recovery on macOS; page count and PDF metadata where extractable. Long PDFs first read 30 pages and later continue in 30-page steps; max 5,000 pages. | macOS PDFKit + Vision; portable PDFium. No claim of identical OCR behavior off macOS; the source explicitly limits screenshot OCR to Apple Vision and portable OCR implementation returns no OCR. |
| Documents | `txt`, `text`, `md`, `markdown`, `typ`, `rtf`, `docx`, `doc`, `odt`, `html`, `htm`, `xlsx`, `pptx`, `ods`, `odp`; text chunking around 1,800 chars with 200-char overlap, ~40 chunks per first/later step, max 5,000 chunks. Text-heavy prose embeds; non-prose can remain keyword-only. | `.doc` legacy Word relies on Cocoa text system on macOS; portable doc support is not equivalent (portable reader source handles docx/odt/rtf). DOCX/ODT and office spreadsheets/presentations use XML/ZIP-based readers; office text extraction is original DigUp code. |
| Audio | Audio windows are 30 seconds with 25-second hop, converted to 16 kHz mono WAV for EmbeddingGemma audio encoding; stores segment location/time. Video soundtrack passes through the same path. | macOS AVFoundation; portable ffmpeg/ffprobe executables. Portable media extraction will fail when those tools are absent. |
| Video | Samples frames about every 3 seconds and removes near-duplicate frames / groups by shot; indexes frames with timestamps and, when present, audio windows; video hit location is in seconds. | macOS AVFoundation; portable ffmpeg/ffprobe. The core render operation produces a JPEG frame, not a browser playable stream. |
| Code | Separate `code.sqlite`; source, project docs/settings and notebooks; code/query prompt; stores line ranges or notebook-cell ranges and excerpt/focus. Code search uses `code:` and does not mix into ordinary archive search. | Enabled only for explicit roots. Git ignored, generated/vendor/build directories, submodules/worktrees, datasets/data, minified bundles, license files, secrets/keys excluded by rules. Web SearchRequest excludes code today. |

### Metadata and source location

Index `files.info` stores JSON including dimensions, pages, duration, taken date, and long-read progress where available. Search hits carry `kind`, `segment`, `segment_id`, `loc`, `loc_end`, excerpt, modified time, size, and indexed `info`. A PDF `loc` is a page number; audio/video `loc` is start seconds; code uses start/end line or notebook-cell coordinates. SearchService's `text` operation can return the stored text for a segment; `render` supports image, PDF-page and video-frame JPEG output. These existing locations are sufficient for still previews/source references; they are not by themselves a PDF navigation API, an audio playback API, or a video streaming API.

### SQLite and vectors

Original `IndexStore` creates schema version 5. Main index is `index.sqlite`; optional code index is `code.sqlite`. Tables include `meta`, `files`, `segments`, and FTS5 virtual table `fts`. Segments reference files with `ON DELETE CASCADE`; FTS5 uses a Porter/Unicode tokenizer configured to preserve marks and exact source text. Each vector is an L2-normalized 768 × float16 blob stored beside the segment metadata. Search loads the vector corpus for brute-force comparison; source comments cite about 20k vectors / 30 MB and millisecond-scale search, not a separate vector database. Migration increments `PRAGMA user_version` in transactions. The web adapter correctly uses explicit project-local index path and does not define another search/index schema.

## 4. Original settings inventory

The first section covers settings visible to desktop users. Values are from source defaults and UI; `Not established in source` means this audit did not find a fixed default and will not guess it.

| Setting / state | Default and available values | Validation / persistence | Effect and web equivalent |
|---|---|---|---|
| **Folders to search (`roots`)** | Empty on fresh install; user adds one or more folders | Stored as paths in `UserDefaults` domain `com.abdurrahim.DigUp`; launch args may override unsaved. Folder selection normalizes/expands `~`, resolves symlinks, removes duplicates; selecting subfolders is supported. | Determines crawl/search scope; removing a root removes its rows from index. Web should store approved **server source IDs/mounts**, resolved to server paths; never accept arbitrary browser path strings. |
| **Skip these folders (`excludedFolders`)** | Empty | UserDefaults path list; the same folder selection rules apply. `Crawler` skips the folder and descendants. | Prevents reading folder trees. Equivalent should be per archive source and enforced server-side. |
| **Skip these file types (`excludedTypes`)** | Empty | UserDefaults list; `IndexOptions.extensions` splits comma/whitespace and strips leading `*`/`.` then lowercases. | Prevents selected extensions from normal indexing. Web may expose typed comma-separated extensions only if using the original normalization/IndexService support. |
| **Search shortcut (`hotkey`)** | `cmd+shift+space` on macOS; docs note `Ctrl+Shift+Space` on Windows/Linux | UserDefaults. Parses modifier/key tokens; system-reserved/taken shortcut rejected and previous shortcut retained. | Opens global search UI. No equivalent in a normal website; possible browser-page shortcut is limited to focused/active site and should be separately designed. |
| **Open DigUp when you log in** | Current OS Login Item state (not a DigUp boolean default) | macOS `SMAppService.mainApp` state; OS controls permission/failure. | Starts desktop resident process so shortcut/watcher works. Not a normal browser feature. A server service manager is deployment configuration, not user preference. |
| **Check for updates automatically** | macOS: Sparkle default (source does not set the exact boolean). Tauri Windows/Linux: on by default (`update_checks_off` defaults false). | Updater preference; daily check and “Check Now” action. Tauri also reports install/download status and may use a release-page install path depending on platform. | Updates desktop app. Web deployment updates are operator rollout; no per-browser updater. |
| **Folders indexing progress / pause** | Running automatically after setup; no user-set pause default exposed in settings inventory | In-memory engine state and helper control. UI provides Pause/Resume while roots exist. | Pauses/restarts background work. Current web only has one-shot Start/Stop; pause/resume and persistence are missing. |
| **Index on battery power (`indexOnBattery`)** | `true` | UserDefaults; Boolean. If false, backfill waits for AC. New-file small pass is still allowed. | Laptop power policy only. Not applicable to centrally hosted server; replace only if server resource policy is approved. |
| **Index only at set hours (`indexHoursOn`)** | `false` | UserDefaults Boolean; times retained when disabled. | Holds all indexing outside schedule; search remains available. Web/server scheduler would need configured timezone and DST semantics. |
| **From / To (`indexHoursFrom`, `indexHoursTo`)** | 01:00 / 07:00 (`IndexHours.night`) | Stored integer minutes after midnight; normalized modulo 1440. Start inclusive/end exclusive; overnight ranges supported; equal values mean all day. Local Calendar/clock/time-zone changes reevaluate the schedule. | Defines schedule above. Current web has no scheduler. |
| **Code search folders (`codeRoots`)** | Empty, hence code search off | UserDefaults; selected roots in separate list and separate `code.sqlite`; code folder exclusions tracked separately. | Starts separate indexing and makes `code:` searches available. Missing in current API/UI. |
| **Code skip folders (`codeExcludedFolders`)** | Empty | UserDefaults; same include/skip selection semantics. DigUp also always skips gitignored/vendor/generated/submodule paths. | Limits code roots; use original code classifier and skip rules. |
| **Open code in (`codeEditor`)** | Nil: choose first installed editor, preferring a running app; otherwise default file app | Persisted selected bundle ID. Choices are installed known editors/default app; opener has editor-specific line/cell methods. | Opens at matching line/cell. Browser cannot control local editors; web should offer preview/location/download only. |
| **Run the model on the processor (`processor_only`)** | Tauri: `false` by derived settings default; Mac Settings has no equivalent toggle | Persisted in Tauri JSON settings; when enabled helpers get `DIGUP_DEVICE=cpu`, overriding measured GPU choice. | GPU compatibility/privacy override. Central server can use deployment-level `DIGUP_DEVICE=cpu`; do not expose as employee preference without operational need. |
| **Center the search panel (`center_panel`)** | Tauri/Linux Wayland: `false`; hidden on platforms where unavailable | Persisted Tauri JSON setting; on Wayland it uses a transparent full-screen host to position the panel, with memory/CPU cost described in settings. | Desktop window-placement workaround; no browser equivalent. |
| **Clicking DigUp's tray icon (`tray_click`)** | Tauri Windows: default is anything other than `"panel"`, therefore opens the larger window; user can choose Window or Panel | Persisted JSON string; setting is shown only where tray click behavior is configurable. | No browser equivalent. |
| **Window placement (`window`)** | No explicit dimensions until first saved close/resize; then last width/height/position/maximized state | Tauri JSON persisted `WindowPlace`, updated from native window events. | Browser owns tab/window size; no app preference needed. |
| **Update check timestamp (`update_checked`)** | `0` until checked | Tauri JSON state; internal update throttling/status rather than a user-facing option. | Deployment monitoring concern. |
| **EmbeddingGemma 2 model files** | Fixed upstream pair, total 864,676,480 bytes (desktop rounds to 865 MB) | Fixed repo/revision, names, file sizes and SHA-256 in `DigUpKit/ModelFiles.swift`; `FileFetcher` resume/download, caller checks size/hash before final use. “Use Files…” validates same pair. | Enables semantic and multimodal embedding. Central host model install/update should be operator-managed, verified, and reflected by status; do not let general users pick server files. |
| **Model location (`modelsDir`)** | Platform app support `Models` directory | UserDefaults `modelsDir`/launch override; UI shows path, “Use Files…” chooses required files. No model folder relocation control found in UI. | Runtime input location. Server config/environment and managed volume are appropriate; current FastAPI uses `IIHS_DIGUP_MODELS`. |
| **Index location (`indexDir`)** | macOS `~/Library/Application Support/DigUp/index.noindex`; Linux `~/.local/share/digup/index`; Windows `%LOCALAPPDATA%\DigUp\index` | Platform code path; launch argument/setting override; settings UI reveals path and database size, does not offer a relocate control. | Stores schema-v5 DB/previews and code DB. Web must configure a persistent server volume, separate auth DB, and never expose host path. Current dev config uses `var/digup-stage3a/index`. |
| **Index size / code index size** | Read from actual DB/WAL file size | Computed status, not a saved setting. | Informational capacity indicator. Missing in current settings UI/API response. |
| **Encoder idle timeout (`encoderIdleSeconds`)** | 600 seconds (10 minutes) | UserDefaults; values clamped to minimum 1 second; internal setting/CLI argument rather than visible settings control. | Stops idle query encoder to release memory. FastAPI's `IIHS_DIGUP_SEARCH_IDLE_SECONDS` currently defaults to 300 seconds, so behavior differs from desktop's source default. |
| **Code quiet timeout (`codeQuietSeconds`)** | 60 seconds | UserDefaults; minimum 1 second. Internal/developer config; code index catches up when watched folders are quiet. | Delays code sync until edits settle. Current web has no code root/watch workflow. |
| **Onboarding completion (`onboarded`)** | `false` | UserDefaults Boolean; set after user completes or closes onboarding after choosing folders. | Controls first-run onboarding. Web has no equivalent configuration wizard; auth routes exist, but archive source setup remains external config. |

### CLI/index tuning values (not user-facing Settings controls)

These are actual command-line options/defaults or `IndexOptions`, not a claim that desktop exposes them as settings. They should not be surfaced as web preferences without product approval.

| Value | Source default / behavior | Notes |
|---|---|---|
| Search `--zgate` | 2.0 | Meaning match separation threshold. |
| Search `--word-weight` | 2.0; code path has separate weighting | Bonus for containing all query words. |
| `--shot-tokens` | 280 screenshot tokens | Indexing vector-affecting option. |
| `--code-stretch` | 1,800 characters (whole-line stretches) | Code fingerprint includes stretch value. |
| `--new-limit` | 50 new files per quick pass | IndexService prioritizes recently found files. |
| `--linger` | 60 seconds default in CLI; Stage 3A explicitly uses 0 | Persistent helper idle lifetime. |
| `--memory-limit`, `--time-limit` | Watchdog defaults | Runtime safety controls; exact defaults are defined in `Watchdog.swift`, not end-user preferences. |
| `--include-code`, `--include-datasets` | Off by default | CLI-only overrides; code is normally separate; datasets remain skipped. |
| `--exclude`, `--exclude-ext`, `--code-root`, `--code-exclude` | Repeatable arguments | Root and exclusion transport/configuration. |
| `--reindex` | Off by default | Clears/rebuilds vectors when configuration/model fingerprints require it; destructive index action and must not be exposed without safeguards. |
| Photo/PDF/frame/audio options | `IndexOptions`: min image side 256; page threshold 200 chars; PDF first/later step 30; document step 40 chunks; max pages/chunks 5,000; photo/screenshot/page/frame token budgets 140/280/280/70; frame interval 3 sec; audio window/hop 30/25 sec | Internal engine configuration and fingerprints; changing vector-producing values may require reindex. |

## 5. Existing web implementation

### Frontend

`frontend/src/app/page.tsx` renders the authentication entry at `/`; the protected archive is `frontend/src/app/(protected)/archive/page.tsx`. `ArchiveShell` owns Query state/polling and composes `ArchiveToolbar`, `ResultFilters`, `ResultsGrid`, `PreviewPane`, and `StatusBar`. `archive-api.ts` centralizes same-origin requests; `archive-types.ts` defines the client contract. Zustand persists query mode only in memory (no auth token storage); TanStack Query handles health/status/search/metadata and indexing mutation state.

The current interface preserves the approved archive visual shell and IIHS palette. The toolbar has search, Hybrid/Keyword selector, preview toggle, and an engine/indexing popover. Search response hits feed the existing filter/grid/detail UI. Metadata is fetched by opaque hit handle. Preview uses the backend image/PDF/video still URL; original download uses the opaque handle URL. Expired handles are reported as a request-to-search-again state.

### FastAPI adapter

| Existing route | Current purpose / original mapping |
|---|---|
| `GET /api/health` | Executable/model-file presence and process state without starting helper. |
| `GET /api/engine/status` | Original SearchService `status`; lazy process start. |
| `POST /api/search` | Original SearchService `search`, with keyword (`meaning=false`) or hybrid (`meaning=true`); result handles are server-side and expiring. |
| `GET /api/indexing/status` | IndexJob snapshot + original SearchService `summaries`. |
| `POST /api/indexing/sync` | Starts one original IndexService with configured roots, `--backfill`, `--linger 0`. |
| `POST /api/indexing/stop` | Sends original `stop` stdin command. |
| `GET /api/media/{handle}` | Metadata carried on a recent search hit. |
| `GET /api/media/{handle}/preview` | Original SearchService `render` for image/PDF/video still. |
| `GET /api/media/{handle}/frame` | Original SearchService `render` video frame at time. |
| `GET /api/media/{handle}/download` | Streams original file after server-side handle/root containment validation. |

`SearchProcess` multiplexes concurrent request IDs over one persistent child process with a write lock, response reader, timeouts and shutdown. `IndexJob` permits one active job within one FastAPI process, retains bounded/sanitized event snapshots, and reloads search vectors after successful sync. Handles are in-memory and expire (30-minute configured default). `EngineSettings` reads project-local development paths and environment variables; it explicitly rejects the desktop Application Support index. `next.config.ts` proxies same-origin `/api/*` to `ARCHIVE_API_ORIGIN` (default loopback port 8000).

### Missing/partial in web contract

- SearchRequest `DigUpKind` excludes `code`; no `code:` switch/root configuration or code status route.
- No HTTP route for original `text` operation, prewarm, summaries-by-code, roots/folders reconfiguration, estimate, model download or version update.
- Preview route returns a JPEG only; no audio/video source streaming, audio waveform/playback, PDF document viewer, or explicit segment-text route.
- Source management is environment-configured only; no safe administration API.
- Start/stop is a one-off global indexing action; no pause/resume, always-on watcher, schedule, battery/thermal policy, or progress event stream. UI polls status and shows a small recent-event subset.
- The UI does not use SearchService `strong`, all search metadata, document text body, precise code locations, or full folder summary/reason data.
- Server restart invalidates handles and in-memory job snapshots. Multiple FastAPI workers would own separate helpers/jobs and potentially race on the same index; deployment docs therefore recommend one API process per index.
- Archive routes are not all authentication/RBAC protected as of these audited files. The docs explicitly say not to publicly expose until auth, authorization, CSRF for mutations, source policy, and per-user handle access are implemented.

## 6. Reuse strategy

### Reuse directly through the current process boundary

- `DigUpKit` crawling, type classification, extraction, code parsing, vector handling, `IndexStore` schema/migrations, FTS5, search ranking, previews and metadata.
- `LlamaRuntime` model configuration/embedding and llama.cpp backend. Model pair/revision/hash remain pinned in source.
- Original `digup search-service` and `index-service` JSON-lines protocols, including status, search, render, text, summaries, folders, reload, pause/backfill/stop and events where their exact current semantics permit.
- Existing `SearchProcess`, `IndexJob`, `DigUpAdapter`, FastAPI routes and Next proxy for currently supported requests. Keep opaque handle/root boundary and path sanitization.
- Existing frontend components and API client; add capability-backed panels/screens without redesigning the approved archive shell.

### Minor adapter work likely required

- Add explicit support for code search and code status by mapping to original code index/root semantics. Ensure no cross-contamination with ordinary search.
- Expand status/summaries mapping to provide safe per-root skipped/failed/unfinished reasons and code root summaries.
- Add only existing service operations (segment text, prewarm, roots/folders configuration) after mapping their exact protocol validation and authorization needs.
- Support long-lived/scheduled filesystem change detection in the **adapter** if required for parity. It must trigger the existing IndexService, not replace its crawler/indexer.
- Add safe media streaming over opaque handles for HTML `<audio>`/`<video>` if browser playback is required; this is an HTTP transport addition, not a DigUp processing change. Validate path is still inside a configured allowed root, support byte ranges, avoid path fields in URLs, and authorize each request.
- Keep model installation, index directory and model directory as operator-managed server configuration; show readiness/size/status without revealing filesystem paths.

### Desktop-only modules that need browser/server equivalents

The view and controller code in `DigUpApp` is not reusable in Next.js. Reproduce workflows, not SwiftUI/AppKit. Replace macOS file dialogs with administrator-approved server-mounted sources; global hotkey with an optional browser-local shortcut; native Quick Look/open/drag with web previews and downloads; menu bar/tray and login item with backend service health/operator status; Sparkle updater with controlled web deployment; macOS battery/thermal policy with separately approved server workload policy. These are adaptations and should be labeled where exact parity is impossible.

### Do not duplicate/consolidate into a replacement engine

Do not add Python extraction, a second vector store, custom ranking, SQL schema, or JS embeddings. Keep FastAPI as transport/process manager and preserve the original Swift engine as source of truth. Consolidate only adapter-side duplicate response/path transformations if later code review finds duplicated logic; do not merge DigUp's distinct main and code indexes.

## 7. Proposed web architecture

```text
Browser (Next.js, approved visual shell)
  └─ same-origin typed HTTP client and opaque media handles
       └─ FastAPI boundary (authentication/RBAC before external deployment)
            ├─ source registry: approved IDs → server-resolved mounted roots
            ├─ SearchProcess: one owner per index, original JSONL SearchService
            ├─ IndexJob/scheduler: serialized original IndexService lifecycle
            ├─ safe preview/text/media streaming and bounded job/status API
            └─ pinned `digup` executable
                 └─ unchanged DigUpKit + LlamaRuntime + llama.cpp + model
                      └─ original schema-v5 index.sqlite and optional code.sqlite
```

Keep the FastAPI process count at one per index until a cross-process lease/lock and durable job coordination mechanism is deliberately implemented. For central hosting, put archive media on server-controlled read-only or least-privilege mounts, keep index/model/auth DB in separate persistent locations, restrict API ingress to the authenticated same-origin deployment, use TLS, and prevent browser parameters/logs/errors from revealing absolute paths. Any root-management API must accept registered source IDs, not arbitrary paths. Enforce authorization for search, each preview/frame/text/download request, and indexing mutations; handle possession is not authorization.

## 8. Main parity gaps and risks

1. **Feature gap:** code search and code index are not represented in the web contract.
2. **Preview gap:** image/PDF/video stills exist, but audio playback, video playback and PDF/page text navigation do not.
3. **Lifecycle gap:** desktop watching, pause/resume, schedule and detailed per-folder status are absent; a manual sync is not continuous indexing.
4. **Configuration gap:** no browser-safe roots/exclusions/code settings, estimates, model setup, or storage/status settings screen.
5. **Environment mismatch:** desktop settings defaults and server config differ; notably search encoder idle is 600 seconds in original app preferences but 300 seconds in current FastAPI configuration.
6. **Platform mismatch:** original source has macOS native OCR/legacy formats and portable limitations. Central host OS/runtime/tool availability determines extraction capabilities. “Build succeeds” alone does not guarantee ffmpeg/ffprobe runtime availability or codec coverage.
7. **Persistence/concurrency:** search handles, index job state and process ownership are memory-local. Restart clears handles/status; multiple API workers can create multiple helper processes against the same SQLite index.
8. **Security:** current archive routes must remain private until backend authentication/RBAC is enforced for every operation, including download and any newly added streaming endpoints. Opaque IDs do not replace access checks.
9. **Data boundary:** the original desktop privacy claim (“files never leave this computer”) does not apply unchanged to central hosting. IIHS must approve server region, access, logging, retention, backups, file permissions and network egress.
10. **Desktop-only equivalence:** Finder, native editor opening, OS shortcuts/login items, menu/tray, and native updater cannot be reproduced exactly in a browser.
11. **Settings safety:** exclusions/folder removal/reindex can alter index contents or discard/recompute data. UI should reflect DigUp semantics, confirm destructive actions and never map arbitrary paths directly from a browser request.

## 9. Prioritised implementation roadmap

This is a recommendation, not authorization to implement.

1. **Parity baseline and API gap tests:** freeze current approved UI; map each desktop operation to a verified JSONL operation and create API-level acceptance tests for mapping/omission. Record platform/runtime prerequisites.
2. **Protect the service before adding administration:** complete authentication/RBAC/CSRF/session enforcement for existing search, metadata, preview, frame, download and indexing routes; scope opaque handles to user/archive permissions. This is a release gate, not optional UI work.
3. **Server source management:** define administrator-approved source registry/mount IDs and safe include/skip/type settings; serialize configuration updates and invoke original SearchService `folders`/IndexService reconciliation. Never accept raw filesystem paths from browser users.
4. **Complete search parity:** expose code search/status against original separate `code.sqlite`; use engine's `strong`, `focus`, `loc_end`, excerpt/text and query behavior. Add keyboard accessibility and preserve current result layout.
5. **Complete result previews:** add original segment-text retrieval and PDF page navigation; add authorized range streaming for original audio/video files if playback is required; retain existing DigUp frame endpoint and locations.
6. **Indexing lifecycle:** add pause/resume/backfill controls where original process supports them; persist job state/serialize one index owner; implement watched/scheduled sync only as a trigger around original IndexService. Provide safe reasons/progress per source.
7. **Operator/system settings:** model/index size and readiness; source estimates; supported extraction/runtime capability report; server schedule/resource policy only after operations requirements are known.
8. **Feature parity verification and rollout:** run format, ranking, location, permissions, concurrency, restart and browser accessibility regression matrix; deploy privately first, then expose only after security and data-governance approval.

## 10. Feature-by-feature testing checklist

### Engine compatibility and core preservation

- [ ] Confirm engine submodule remains pinned and clean before/after tests.
- [ ] Confirm CLI and helper build/run from exact configured path.
- [ ] Confirm model file revision/name/size/hash and successful text + media model initialization.
- [ ] Confirm database remains schema 5; FTS5 and vector blobs are created/read by original `IndexStore` only.
- [ ] Confirm main and code databases remain distinct and no migration/reindex occurs on ordinary web startup.

### Search parity

- [ ] Keyword match for exact filename, path term, document text, OCR (platform-supported), code token and multilingual normalized text.
- [ ] Hybrid ranking for image, PDF page, document chunk, audio window and video frame; verify expected result above unrelated fixture.
- [ ] Kind filters work as backend filters; natural-language kind hints stay soft hints.
- [ ] `strong`/weaker match presentation matches Searcher response, not frontend-computed scores.
- [ ] Correct PDF page, audio/video second, code line range/notebook cell appears and is passed through preview/action path.
- [ ] Timeout, empty results, model unavailable, helper exit, malformed query and expired handles show safe user-facing states.

### Indexing and configuration parity

- [ ] Add/remove registered server source; no arbitrary path can be passed by a client.
- [ ] Include selected subfolders and skip configured folder trees; test duplicate roots/symlinks at server policy boundary.
- [ ] Apply excluded extensions and verify existing index reconciliation behavior.
- [ ] New/changed/moved/deleted files reconcile; long PDFs/documents finish over multiple steps.
- [ ] Stop, pause, resume, backfill, scheduled and file-change-triggered runs serialize to one owner.
- [ ] Per-source counts/reasons for missing, inaccessible, pending, unfinished, skipped, failed and left-out files do not expose host paths.
- [ ] Restart during index/search is recoverable; no duplicate simultaneous writers; search reload reflects completed sync.

### Media and preview parity

- [ ] Images: supported formats, screenshot detection, EXIF/date/dimensions, preview, download.
- [ ] PDFs: text PDF, scan PDF, sparse-text/slides, password-protected failure, page render/location, segment excerpt.
- [ ] Documents: every exact `Rules.docExtensions` type available on deployment platform; XLSX/ODS and PPTX/ODP sheets/slides/notes.
- [ ] Audio: 30s/25s windows, metadata/duration, semantic location, range playback and expired-handle behavior.
- [ ] Video: keyframe selection/timestamps/audio soundtrack, frame preview at location, range playback at matched time.
- [ ] Code: source/docs/notebook, gitignore/vendor/generated exclusions, line/cell focus, code-only search, separate DB.
- [ ] Original download preserves safe filename/content disposition and does not permit path substitution or cross-source access.

### Browser interaction / operational safety

- [ ] Maintain approved archive visual structure at desktop and narrow widths.
- [ ] Search keyboard focus, accessible result selection, filters, preview toggle and download.
- [ ] Loading/empty/error/expired-handle states; no misleading “authenticated/indexed” claims.
- [ ] Cross-user handle access checks, role enforcement, CSRF on state-changing calls, rate limits and audit records.
- [ ] API startup/shutdown/restart, one-process-per-index behavior, multiple requests and concurrent indexing conflict.
- [ ] Logs and all API responses hide absolute paths, environment secrets, tokens and raw helper stderr.
- [ ] Confirm central-host privacy/retention/backup policy is reflected in product copy and IIHS deployment controls.

## 11. Evidence files

- Original README: `backend/engine/DigUp/README.md`
- Original package: `backend/engine/DigUp/Package.swift`
- Search/index protocol: `backend/engine/DigUp/Sources/digup/SearchService.swift`, `IndexService.swift`, `main.swift`
- Search/store/settings: `backend/engine/DigUp/Sources/DigUpKit/Searcher.swift`, `IndexStore.swift`, `Model.swift`, `Rules.swift`, `Indexer.swift`, `ModelFiles.swift`; `backend/engine/DigUp/Sources/DigUpApp/AppSettings.swift`, `SettingsWindow.swift`
- Current API contract: `docs/architecture/stage3a-browser-api.md`
- Current web implementation: `backend/app/api/routes/archive.py`, `backend/app/engine/supervisor.py`, `backend/app/schemas/archive.py`, `backend/app/core/engine_config.py`, `frontend/src/components/archive/`, `frontend/src/lib/archive-api.ts`, `frontend/next.config.ts`

