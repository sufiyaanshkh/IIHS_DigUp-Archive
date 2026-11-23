# Stage 3A — Browser-facing DigUp adapter

## Implemented boundary

```text
Next.js browser (same-origin /api requests; live DigUp results and indexing)
                  │ HTTP
                  ▼
FastAPI archive routes (`backend/app/api/routes/archive.py`)
                  │
                  ├── SearchProcess: request-ID multiplexed JSON lines
                  │       └── one persistent `digup search-service`
                  └── IndexJob: one active job and a bounded event snapshot
                          └── short-lived `digup index-service`
                                  │ explicit --index and configured roots
                                  ▼
                         Original DigUpKit / LlamaRuntime
                         EmbeddingGemma 2 / llama.cpp
                         schema-5 `index.sqlite`
```

The adapter passes search, indexing, render, status, and reload work to the pinned DigUp CLI. It does not implement search, embeddings, media extraction, or an index schema of its own. Search and indexing processes receive an explicit index path and only the environment needed to locate the CLI runtime and model; Entra secrets are not inherited by those processes.

The default development index and empty media root are project-local:

```text
var/digup-stage3a/index/index.sqlite
var/digup-stage3a/media/
```

The model and executable default to the existing pinned build under `backend/engine/DigUp`. All paths can be set with the environment variables below. The adapter rejects DigUp's default macOS `Application Support/DigUp/index.noindex` path.

## HTTP API

All routes are under `/api`. Responses never contain absolute media or index paths. Search result IDs are random in-memory handles with a 30-minute default lifetime; restart or expiry invalidates them.

### `GET /api/health`

No request body. Returns adapter state without starting a helper:

```json
{
  "status": "ok",
  "digup_cli_available": true,
  "models_available": true,
  "search_service_running": false,
  "index_job_state": "idle"
}
```

`models_available` verifies the configured text GGUF and media projector exist. It does not claim the model has loaded or performed inference.

### `GET /api/engine/status`

Starts SearchService lazily, then maps its `status` JSON-lines response to `search_service`, `encoder`, `vectors`, `files`, `searchable`, `pending`, `unfinished`, model availability, and current indexing snapshot. It does not force model prewarm.

Errors: `503` helper unavailable; `504` helper response timeout.

### `POST /api/search`

Request:

```json
{
  "query": "rainfall records from the western district",
  "mode": "hybrid",
  "kinds": ["doc", "pdf", "image", "video"],
  "limit": 20
}
```

`query` is 1–500 nonblank characters. `mode` is `keyword` or `hybrid`; kinds are DigUp's existing values (`screenshot`, `image`, `pdf`, `doc`, `audio`, `video`), and limit is 1–100. Omit `kinds` to search all kinds.

The response carries `query`, `mode`, `meaning`, `strong`, `timings_ms`, optional `warning`, `total`, and `hits`. Each hit contains an opaque `id`, basename, root-relative folder, UI-friendly kind, original engine kind and segment, location, score, excerpt, DigUp metadata, MIME type, and preview/download URLs. It omits DigUp's `path`.

Mapping: sends SearchService `{"op":"search","q":...,"kinds":...,"limit":...,"meaning":false|true,"prefix_last":false,"id":...}`. `keyword` sets `meaning=false`; `hybrid` sets `meaning=true`, preserving DigUp's combined meaning + FTS ranker. DigUp has no semantic-only switch, so this API intentionally does not claim one. A hybrid result can still be supported by a meaning match without a keyword match.

Errors: `422` invalid query/engine rejection; `503` helper unavailable; `504` timeout.

### `GET /api/indexing/status`

No body. Returns current state (`idle`, `starting`, `scanning`, `indexing`, `waiting`, `completed`, `stopping`, `stopped`, or `failed`), job ID, timestamps, checked/done/total counters, up to 100 safe file summaries and up to 100 safe helper events, error, search reload status, and per-root counts (`files`, `indexed`, `pending`, `failed`, `skipped`, `unfinished`, kinds, missing/unreadable flags). Per-root paths are replaced with a configured root basename. Poll this endpoint; IndexService itself emits JSON-lines, not a browser event stream.

### `POST /api/indexing/sync`

No body. Starts one IndexService process for configured roots with an explicit `--index`, `--backfill`, and zero idle linger. IndexService performs its initial sync when it starts. Returns `202` with the job snapshot.

Errors: `409` another job is active; `422` no roots configured; `503` CLI unavailable.

### `POST /api/indexing/stop`

No body. Sends the original `stop` command to the active IndexService and returns the snapshot (`202`). If there is no active job, returns its current snapshot without starting a process.

After a successful sync, if SearchService is already running, the adapter sends its original `reload` operation so its in-memory vectors reflect the updated index.

### `GET /api/media/{handle}`

Returns metadata retained from the DigUp search hit: filename, kind, segment, source location, modification time, size, indexed metadata, and excerpt. This is not an independent filesystem scan; the handle must come from a recent search result.

Errors: `404` handle expired/unknown or source unavailable; `403` resolved media is outside configured roots.

### `GET /api/media/{handle}/preview?loc={number}&pixels={number}`

Returns JPEG bytes for image, PDF page, or video result previews. `loc` is a PDF page or video second; omitted values use the hit location. `pixels` is 64–2048 (default 1024).

Mapping: SearchService `render` request with server-resolved path and kind; returned preview must resolve inside `<index>/previews` before it is streamed. The client cannot supply a path.

Errors: `404` unknown handle; `403` out-of-root media; `415` unsupported preview kind; `422` invalid page/time; `503` helper error; `504` timeout.

### `GET /api/media/{handle}/frame?at={seconds}&pixels={number}`

Returns a video frame JPEG at the requested timestamp. Uses DigUp's existing `render` operation with `kind=video`; time must be within the indexed video duration.

Errors: `404` unknown/non-video handle; `403` out-of-root media; `422` invalid timestamp; `503` helper error; `504` timeout.

### `GET /api/media/{handle}/download`

Streams the original file as an attachment, after resolving the opaque handle and checking the current real path remains under a configured root. The server does not accept a filename or path from the request.

Errors: `404` unknown handle or unavailable source; `403` out-of-root media.

## Process and lifecycle behavior

- SearchService starts on the first status/search/render call. One async stdout reader correlates response IDs to pending futures; stdin writes are locked. Unsolicited `ready`/`encoder` events are consumed separately. Timed-out requests are removed. On helper exit, pending requests fail and a later request starts a fresh process.
- IndexService is single-owner per configured index in this FastAPI process. A second sync receives `409`. Its progress is translated to a bounded in-memory snapshot; raw stdout, absolute paths, roots, and helper arguments are not returned to clients.
- On application shutdown, the adapter sends SearchService `quit` and IndexService `stop`, waits briefly, then terminates/kills only if graceful exit fails.
- Each FastAPI worker would own independent helper processes and job state. Run one API process per index until cross-process locking/coordination is deliberately added.

## Configuration and development command

Run from `digup-web/backend` with the existing virtual environment:

```sh
IIHS_AUTH_DB_PATH=var/auth.sqlite \
IIHS_DIGUP_CLI=backend/engine/DigUp/.build/release/digup \
IIHS_DIGUP_MODELS=backend/engine/DigUp/Vendor/models \
IIHS_DIGUP_INDEX_DIR=var/digup-stage3a/index \
IIHS_DIGUP_ROOTS=var/digup-stage3a/media \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`IIHS_DIGUP_SEARCH_IDLE_SECONDS` defaults to 300, `IIHS_DIGUP_REQUEST_TIMEOUT_SECONDS` to 30, and `IIHS_DIGUP_HANDLE_TTL_SECONDS` to 1800. Paths may be absolute or project-relative. `IIHS_DIGUP_ROOTS` uses the platform path separator. Create/populate only an approved media root; the adapter does not create missing roots, preserving DigUp's missing-root behavior.

## Frontend integration and verification

The Next.js archive UI now reads live search results through the same-origin `/api` routes. It supports the actual DigUp keyword and hybrid modes, result-kind filtering, live metadata, image/PDF/video previews, original downloads, engine health, and indexing status/start/stop controls. The frontend does not accept filesystem paths or upload files. PDFs returned from filename-only matches request page 1 because those hits have no location; video frame preview uses DigUp's returned location or its supported timestamp parameter.

`frontend/next.config.ts` rewrites `/api/*` to `ARCHIVE_API_ORIGIN` (origin only, without `/api`), defaulting to `http://127.0.0.1:8000`. Run one API process per index. The UI uses existing `@tanstack/react-query` for polling and result state; no frontend dependency was added.

For local development, run FastAPI from `backend/` and Next.js from `frontend/` in separate terminals:

```sh
# backend/ — paths are resolved from the project root
IIHS_AUTH_DB_PATH=var/stage3b-smoke/auth.sqlite \
IIHS_DIGUP_INDEX_DIR=var/digup-stage3a/index \
IIHS_DIGUP_ROOTS=var/digup-stage3a/media \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend/
ARCHIVE_API_ORIGIN=http://127.0.0.1:8000 npm run dev
```

The Stage 3A backend integration test uses disposable project-local fixtures and verifies schema-5 indexing, keyword/hybrid search, image preview, video-frame rendering, metadata, downloads, concurrency, shutdown, and restart. Stage 3B was additionally exercised through the Next.js proxy with a disposable TXT, PNG, PDF, and MOV fixture: health, UI indexing and stop, keyword/hybrid search, image and PDF previews, video frame preview, metadata, and download links. `npm run lint` and `next build --webpack` pass.

The archive endpoints are **not yet guarded by authentication or RBAC**. Keep FastAPI bound to loopback in development. Do not expose this API through a public reverse proxy until authentication, authorization, CSRF protection for mutations, source-management policy, and per-user handle access are implemented. No archive-root management endpoint exists; roots are server configuration only.
