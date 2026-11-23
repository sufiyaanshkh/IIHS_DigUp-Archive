# DigUp source integration and browser backend plan

## Scope and verification

The original repository is included at `backend/engine/DigUp` as a Git submodule pinned to `dc2651ad8299160bbe91e972f857e1a1599a8419` (`v0.7.0-beta.3-7-gdc2651a`). The submodule worktree is clean. Its source, history, database schema, helper protocols, algorithms, model files, and UI were not edited. No model weights were downloaded.

This is a source inspection, not a successful server build. The current machine is macOS arm64 with Swift 6.3.3; the upstream README specifies Swift 6.4 for Windows/Linux builds. The submodule has no `Vendor/` directory, and the Linux host libraries and CUDA/Vulkan runtime have not been checked. Therefore Linux runtime compatibility remains to be demonstrated on the intended host.

## Architecture map

```text
Browser (existing Next.js frontend)
       │ same-origin HTTPS requests (proposed)
       ▼
FastAPI service in backend/app (existing project service)
  ├─ auth database/session code already present in this checkout
  ├─ proposed archive API and authorization boundary
  ├─ proposed process supervisor / JSONL bridge
  └─ no direct browser access to helper pipes or filesystem paths
       │ private stdin/stdout pipes; one managed process per service role/index
       ├──────── digup search-service ──────┐
       └──────── digup index-service ───────┤
                                            ▼
                               DigUpKit + LlamaRuntime
                               llama.cpp + EmbeddingGemma 2
                                  │              │
                             index.sqlite   code.sqlite
                                  │
                    server-mounted original media roots
```

The first two boxes describe a proposed integration boundary, not new working archive API behavior. In this checkout, FastAPI currently wires the authentication routes and migrations; `backend/app/engine` and `backend/app/indexing` are empty package placeholders. This task added no API, process bridge, filesystem registry, or authentication behavior.

### Upstream layers and languages

| Layer | Source | Responsibilities |
|---|---|---|
| Core | `Sources/DigUpKit` (Swift) | Crawling, classification, extraction, chunking, preview rendering, SQLite index, FTS5, vector storage, ranking |
| Model runtime | `Sources/LlamaRuntime` (Swift/C interop) | EmbeddingGemma model loading, llama.cpp inference, text/image/audio embeddings |
| CLI and helpers | `Sources/digup` (Swift) | `index`, `search`, `search-service`, `index-service`, model worker and JSON output |
| Apple desktop UI | `Sources/DigUpApp` (SwiftUI; macOS only) | Menu bar app, native windows, settings, folder selection, OS actions |
| Windows/Linux desktop shell | `shell/src-tauri` (Rust/Tauri 2) | Window lifecycle, helper supervision, native dialogs, tray/hotkeys, OS integration |
| Desktop web UI | `shell/ui` (HTML/CSS/vanilla JavaScript) | Search panel, result window, setup and settings; calls Tauri commands/events |
| Reference worker | `worker` (Python) | Evaluation/reference path, not the shipping search/index implementation |

`Package.swift` defines the `DigUpKit` library, `LlamaRuntime`, `digup` executable, and macOS-only `DigUpApp`. It pins Sparkle 2.10.0 only for the macOS application. The Windows/Linux Rust shell uses Tauri 2.12.3, `tauri-build` 2.7.2, plugins for global shortcut 2.4.1, opener 2.7.1, single-instance 2.5.3, dialog 2.8.2, autostart 2.5.1 and updater 2.13.3; Serde/serde_json, Tokio, and notify support communication and file watching. Platform bindings include libc, windows-sys 0.61, and Linux GTK/GIO 0.18 plus zbus 5. `shell/ui` has no Node package manifest; Node is used by upstream build/test tooling, not as its UI runtime. The Python worker is an evaluation/reference path (Python 3.12, MLX 0.32.3, transformers 5.19.0 and a pinned mlx-vlm Git revision), not the shipping cross-platform search/index implementation.

Portable Swift builds need upstream-fetched SQLite with FTS5, stb, miniz, and PDFium under `Vendor/`; llama.cpp is built separately. macOS uses Apple frameworks and a Metal build. Linux/Windows use portable readers and shared llama.cpp libraries (CPU plus available supported accelerator backend). The checked-in upstream scripts, checksum manifest, and package scripts define those artifacts; none are vendored in this checkout.

## Desktop frontend reuse

Reusable directly as browser UI source: static markup, styling, and interaction logic in `shell/ui` (`index.html`, `window.html`, `setup.html`, `settings.html`, CSS, `results.js`, `panel.js`, `window.js`, `setup.js`, `settings.js`). The panel supports immediate FTS results while typing, pre-embeds the paused query, then displays semantic/hybrid results; it groups results, separates weaker matches, supports keyboard selection, previews and filters. The larger window adds a media grid and kind filters. Setup/settings cover roots, skips, code roots, scheduling and model/index state.

The UI is not standalone web code today: it assumes `window.__TAURI__`, invokes Rust commands, and listens to Tauri events. Its HTML/CSS/JS can inform or be reused in a browser bundle, but the Tauri bridge calls must be replaced by HTTP requests and a browser event mechanism. Native folder pickers, tray/menu controls, global shortcuts, open/reveal/copy/drag-to-OS, autostart, desktop updates, and window placement are host OS features, not browser-reusable components. Browser users cannot choose a path on the server or on their own machine through the existing UI; an authorized server-side source-management workflow is needed.

## Existing indexing pipeline

1. `Crawler` walks configured roots, reads file metadata (not full contents), applies hidden/package/cache/exclusion and file rules, and emits candidates with path, size, modification time, device, inode, and kind. Media kinds are screenshots, images, PDFs, documents, audio and video. Upstream documents support JPEG/PNG/HEIC/WebP and more; txt/md/typ/rtf/docx/odt/html (plus legacy `.doc` on Mac); xlsx/ods/pptx/odp; and audio/video formats supported by platform readers. Code is opted into separately and stored in `code.sqlite`.
2. `Indexer.sync` reconciles candidates with the SQLite index. Same path plus unchanged size/mtime/kind is unchanged; changed files are queued; same `(device,inode)` and matching size/mtime at a new path is repathed without re-embedding; removed/excluded rows are pruned. If a root disappears during a walk, it preserves its rows rather than interpreting the interruption as deletion.
3. Extraction prepares the next job while the current job is embedded. Images are batched up to eight. PDFs are page-based; documents are chunked; audio/video are sampled in time windows/keyframes; code uses a separate index and code-specific extraction. Images/PDF scans/video/audio can use multimodal embeddings. Screenshot OCR is via Apple Vision only; portable builds do not provide that OCR capability. Unsupported, protected, cloud-only/unavailable, tiny/short, or excluded items may be skipped with a recorded reason.
4. `LlamaRuntime` runs EmbeddingGemma 2 Q8_0 GGUF through llama.cpp tag `b11461`, commit `4d756bc72bf00a4aacf410ae15a2d315f3db400d`, with the repository's no-logits patch. The GGUF files are pinned at Hugging Face revision `bfcd298762cc34d0357ece5ebdd31791a3a374d8`: text model 309,855,456 bytes and media projector 554,821,024 bytes (about 865 MB combined). It stores normalized 768-dimensional vectors (float16 in SQLite) with the segments; text-only worker mode supports query embeddings, full mode includes image/audio projector.
5. New files are indexed before background backfill; long PDFs/documents are completed in a later pass. Indexing can pause/yield to sync/stop and resumes pending work. Model/runtime fingerprint changes trigger the upstream reset/requeue behavior.

Index schema version is 5. Main files live in `index.sqlite`; code is separately held in `code.sqlite`. `files` has absolute `path` (unique), `kind`, size/mtime/device/inode and state; `segments` references files and stores location, excerpt, modality and vector; FTS5 indexes searchable names/text. Foreign keys and writes are transactional. SQLite is configured with WAL, `synchronous=NORMAL`, foreign keys, busy timeout and mmap. Keep these DigUp databases separate from the authentication database; do not change the schema for account data.

## Existing search and result pipeline

The query is embedded by EmbeddingGemma; cosine scores against the in-memory vector matrix are normalized per query/modality into a z-like meaning score. A segment is a semantic candidate when it clears the upstream z gate (2.0 by default). FTS5 runs Porter/unicode tokenization over file names, normalized body and OCR/text; it includes prefix matching while typing and gives exact identifiers/lookup-shaped queries extra keyword weight. A file qualifies by semantic strength or at least 50% query-word coverage. Ranking combines semantic z and `coverage^1.5` (word weight 2.0 for normal files; 1.0 for code), plus a +1 soft file-kind hint. Exact lookups halve semantic weight and double word weight. Results point to the best segment/page/time and include a snippet, metadata, and path. This is the original hybrid ranker; no vector database or replacement algorithm is proposed.

The service can return segment text and render PDF page/video frame/image previews into `<index>/previews`. Those preview files are derived caches, cleaned at search-service startup. Opening the original file is currently delegated to the desktop shell/OS. A browser adapter should offer preview and download by an opaque result identifier, resolve it server-side, and stream only files under an allowlisted, currently mounted source root. Never accept a caller-supplied absolute path.

## JSON-lines helper contracts

The protocol is private process IPC. Browser code must not access stdin/stdout.

### `digup search-service`

One JSON object per stdin line, one response per stdout line, keyed by request `id`. Supported operations documented in `Sources/digup/SearchService.swift`:

| Operation | Input | Result |
|---|---|---|
| `search` | `q`, `code`, optional `kinds`, `limit`, `meaning`, `prefix_last` | `hits`, `strong`, `meaning`, elapsed `ms`; optional warning |
| `embed_ahead` | `q`, `code` | `{ok:true}` after embedding/caching query |
| `text` | `segment`, `code` | segment text |
| `render` | `path`, `kind` (`pdf\|video\|image`), `loc`, `pixels` | generated preview image path |
| `reload` | none | reload index and vector counts after indexing |
| `summaries` | `code` | root availability and file/index/pending/failed/skipped counts |
| `folders` | roots/skips/types/code roots/code skips | update search scope |
| `prewarm` | none | start encoder and load vectors |
| `status` | none | encoder state, vector/file/searchable/pending/unfinished counts |
| `quit` | none | acknowledge then exit |

Malformed JSON lines are ignored. Operation errors are represented as JSON error responses (with the request id where parseable); asynchronous rendering is limited to two concurrent render slots. A persistent search-service holds the index open, caches recent query vectors, and unloads encoder/vector memory after its idle threshold; it exits after twice the idle threshold. Keyword-only search remains usable while the model is unloaded.

### `digup index-service`

One plain-text command per stdin line; JSON event objects on stdout. Commands: `sync`, `sync code`, `stop`, `backfill on`, `backfill off`; EOF requests stop. Events include `missing`, `pruned`, `scanning`, `sync`, `file`, `rest`, `summary`, `waiting`, `idle`, `error`, `stopped`, `rescan`, and `exit`; code-index events include `code:true`. Event payloads carry applicable paths, counts, state/reason and progress.

The helper is short-lived per stretch of work, but remains warm for a configurable linger interval. It syncs roots, prioritizes newly queued files, optionally backfills, processes code index and later long-file segments, reports failure/stopped-file state, and closes the shared embedder on exit. It checks root existence before sync; a missing/unreadable external root is reported while indexed rows are retained. Search service can be told to reload after writes.

### `digup worker` (internal)

The worker starts with a `ready` JSON event, then accepts line-delimited `info`, `text`, `image`, `audio`, and `quit` requests with ids; embeddings return base64 float32 vectors and per-input errors. It is an internal process used by the Swift runtime; the browser adapter should use search/index service protocols and not expose model worker requests.

## External storage compatibility

**Existing capability:** roots that vanish are not immediately pruned; the indexed rows remain in SQLite. The crawler obtains filesystem identity as `(device,inode)` on POSIX, and Windows volume serial plus file index. A reconnected root at its prior path can be crawled and unchanged files recognized. A move can avoid re-embedding when identity, size and mtime match. Original media is read in place; DigUp creates the index and derived preview cache, not a permanent copy of all originals.

**Verified limitation:** this is a filesystem identity pair, not a persistent archive-volume identity abstraction. There is no registered volume UUID/serial mapping, administrator-managed mount alias, per-volume connection state, or browser-safe file identifier. Device IDs/inodes/Windows file indexes may differ by filesystem, reformat, remount, host, or copy. Stable identity across every reconnection cannot be promised solely by core behavior. Also, `SearchService` filters hits through `FileManager.fileExists`, so disconnected files remain indexed but are not returned in ordinary search results; preview and original download cannot work until the source is mounted. Index-service preservation is not equivalent to offline-search display.

**Smallest proposed extension:** a server-side archive-source registry maps a generated opaque `source_id` to an administrator-approved mount root and, where available, a platform volume UUID/serial. The adapter checks mount identity before operating, passes only resolved roots into the unchanged service, and maps returned engine paths back to `(source_id, relative_path)` handles. If offline metadata results are required, this needs an explicit adapter policy/change around the engine's current existence filter or an adapter-owned cached metadata result path; it is not currently provided. Never rewrite the engine index to substitute a different path format. A reconnect with changed mount path also needs adapter policy to register/validate the new mount root before service configuration is updated.

## Proposed in-project backend structure

Keep the existing FastAPI application and authentication foundation. Add only the missing archive integration modules when implementation is approved:

```text
backend/
  app/
    api/routes/          auth routes already exist; add archive/search/index/source routes
    core/                existing Settings; add engine/index/source config
    engine/              JSONL process supervisor and request/event multiplexing
    indexing/            authorized index job coordination and event state
    media/               opaque handle resolution, preview/download streaming
    schemas/             request/response models
    services/            archive policy and orchestration
    auth/                existing auth DB, OIDC and sessions
  engine/DigUp/          pinned upstream submodule; preserve source untouched
  data/
    auth.sqlite          separate authentication database (configured outside static/public paths)
    indexes/             DigUp index.sqlite, code.sqlite and generated previews
  tests/                 adapter contract, source allowlist, process lifecycle tests
```

This is proposed only. Do not place authentication tables in DigUp index SQLite. Production data paths should be configuration-driven, private to the service account, persistent, and excluded from source control/static serving. Keep one authorized index owner per source/index to avoid multiple competing index-service writers. Search helpers can be persistent per index and supervised/restarted; serialize index mutations and coordinate reload notifications.

## Browser integration and security boundary

Serve the existing Next.js frontend and FastAPI API under one HTTPS origin (reverse proxy routes such as `/api/*` to FastAPI), so the browser uses same-origin `fetch` and avoids permissive cross-origin cookies. Preserve the existing frontend; only later wire search, source state, preview and download actions to API contracts. FastAPI authenticates/authorizes each operation, validates inputs and translates to the helper protocol. The service account alone can access configured media roots and helper pipes.

Suggested boundary (route names are proposals, not existing APIs): search accepts query/filter and returns safe result DTOs with opaque handles; preview accepts handle plus a bounded page/time/size; download accepts handle and streams the original; indexing endpoints start/stop/status for an authorized source and expose progress through SSE or WebSocket. Validate request sizes, query limits, preview dimensions/time ranges, range requests, content disposition and MIME type. Do not expose helper stdout, helper startup arguments, absolute paths, environment secrets, or a raw arbitrary-path endpoint. Protect indexing as a mutation; enforce the existing RBAC policy on the backend when that milestone is authorized.

The central host changes the privacy boundary from local-only to centrally processed. Limit service account read access to approved mounts, prevent symlink/root escapes, isolate helper process permissions, and audit source/index mutations and original-media downloads. Back up authentication data separately from index/derived data; apply least-privilege access, TLS, request limits, CSRF protections for cookie-authenticated mutations, and controlled logs. The original helper protocols themselves have no user identity/authorization; enforcement belongs in FastAPI before requests are sent.

## Build and verification plan

1. On the intended Linux server, install the documented Swift 6.4 toolchain, Rust/Node only if building the desktop shell, and native prerequisites for DigUp's Linux CLI/helper build. The central web server does not need Tauri or the Tauri UI runtime.
2. Run the upstream vendor fetch and pinned llama.cpp build scripts in a reproducible build environment; validate checksums and preserve upstream commit/pins. Do not commit generated model weights or vendored build output unless the project explicitly chooses that artifact strategy.
3. Build/test upstream Swift package and CLI on the actual server architecture; validate PDFium/FFmpeg/stb/miniz, SQLite FTS5, CPU operation, then the chosen supported GPU backend if applicable. Confirm model startup and reference vectors with the upstream test suite.
4. Create a disposable test archive and exercise index sync, incremental unchanged/changed/moved files, service restart/reload, search-service JSONL contracts, render/text retrieval, missing-root preservation and reconnect behavior. Do not run indexing on production media during development.
5. Implement the FastAPI supervisor/API adapter only after approval; test malformed helper responses, process crash/restart, queue serialization, path traversal/symlink escape, cross-user source access, large downloads/ranges, offline media, concurrency and shutdown.
6. Add same-origin frontend integration later without redesigning the approved interface; verify search, filters, previews, downloads and indexing status against the backend.

## Current checkout changes and state

This integration step adds the submodule pointer and root `.gitmodules` entry, plus this architecture document. The requested gitlink and `.gitmodules` are staged by `git submodule add`; the pre-existing project files remain untracked as they were before this task. No frontend, authentication source, DigUp index DB, model, or upstream source file was changed. The current FastAPI authentication code in this checkout was inspected only to describe the actual integration point; it was not modified.
