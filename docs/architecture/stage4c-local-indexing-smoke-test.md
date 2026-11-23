# Stage 4C — Local Indexing Readiness and End-to-End Smoke Test

**Date:** 2026-11-22  
**Project:** `digup-web`  
**Result:** Passed for the tested local text, image, and PDF workflow.

## Isolation and runtime

The test used the pinned original DigUp CLI at `backend/engine/DigUp/.build/release/digup`, the existing approved model files, and the original IndexService, SearchService, SQLite schema, and renderer. The submodule remained at `dc2651ad8299160bbe91e972f857e1a1599a8419` with a clean submodule working tree.

All smoke data is under the ignored `var/digup-smoke-test/` directory:

- Media root: `var/digup-smoke-test/media/`
- Index: `var/digup-smoke-test/index/index.sqlite`
- Separate temporary auth database: `var/digup-smoke-test/auth.sqlite`

The existing service on port 8000 was left alone because its status showed a separate five-file index. This test used FastAPI on `127.0.0.1:8001`; the Next.js same-origin proxy was run on `127.0.0.1:3000` with `ARCHIVE_API_ORIGIN=http://127.0.0.1:8001`.

## Fixture set

Six small synthetic files were indexed:

| Fixture | DigUp kind | Test content |
|---|---|---|
| `sample-notes.txt` | doc | `ORCHID-ARCHIVE-742` |
| `sample-project.md` | doc | `BLUE-FOREST-381` |
| `sample-webpage.html` | doc | `PROJECT-COPPER-916` |
| `sample-document.pdf` | pdf | `GLACIER-PAPER-205` |
| `sample-image.png` | image | Synthetic 320 × 240 image |
| `sample-photo.jpg` | image | Synthetic JPEG conversion |

After the initial indexing pass, a browser-triggered reindex was additionally verified by appending a synthetic marker to `sample-notes.txt`. No real archive media was used.

## Results

### Readiness and indexing

- `/api/health` reported `status=ok`, CLI available, and models available.
- The original IndexService scanned and indexed all six files: 2 images, 1 PDF, and 3 docs; 0 failed, 0 skipped, 0 unfinished.
- The index reported 6 vectors. Its SQLite `quick_check` returned `ok`, `user_version` was 5, and the original FTS tables were present.
- The original worker log reported successful full-model startup on llama.cpp `b11461`; indexing completed and SearchService reloaded the index.
- From the browser, **Index sources** started another sync. After one synthetic text fixture was changed, a second browser-started sync processed 1/1 changed files and completed with `search_reload=complete`.

### Search

Each exact marker returned its expected file in both original API modes (`keyword` and `hybrid`):

| Query | Expected and returned result |
|---|---|
| `ORCHID-ARCHIVE-742` | `sample-notes.txt` |
| `BLUE-FOREST-381` | `sample-project.md` |
| `PROJECT-COPPER-916` | `sample-webpage.html` |

The browser displayed the real keyword and hybrid results. It also displayed the updated `UI-INDEX-CHECK-661` text after the browser-triggered reindex.

### Preview, metadata, and download

- Image: the DigUp JPEG preview loaded in the browser at 320 × 240; metadata included the synthetic image dimensions; the original PNG download returned the PNG signature.
- PDF: the DigUp page preview loaded in the browser at 791 × 1024; metadata reported one page and source location `p. 1`; the original PDF download returned a valid `%PDF-` signature.
- The PDF preview and download both returned successfully through the Next.js same-origin `/api` proxy.
- Search, health, engine-status, and indexing-status response checks found no absolute project/media paths.

### Model runtime note

The original Metal-enabled build failed to create a Metal command queue when launched inside the restricted execution shell (`failed to create command queue` / `can't create a llama.cpp context`). The same unchanged CLI and model initialized and completed indexing when launched outside that shell. Setting DigUp's existing `DIGUP_DEVICE=cpu` did not bypass queue initialization in the restricted shell. This points to an execution-environment restriction; no engine or model files were changed. The smoke test confirms model-backed indexing worked, but it did not independently measure GPU utilization.

## Reproduction commands

Run from the project root, in a normal local Terminal session so the original Metal runtime can access the device:

```bash
cd backend
IIHS_AUTH_DB_PATH=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/digup-smoke-test/auth.sqlite \
IIHS_DIGUP_CLI=/Users/macbookair/Desktop/iihs_Projects/digup-web/backend/engine/DigUp/.build/release/digup \
IIHS_DIGUP_MODELS=/Users/macbookair/Desktop/iihs_Projects/digup-web/backend/engine/DigUp/Vendor/models \
IIHS_DIGUP_INDEX_DIR=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/digup-smoke-test/index \
IIHS_DIGUP_ROOTS=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/digup-smoke-test/media \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another terminal:

```bash
cd frontend
ARCHIVE_API_ORIGIN=http://127.0.0.1:8001 npm run dev -- --hostname 127.0.0.1 --port 3000
```

Open `http://127.0.0.1:3000/archive`. The backend health endpoint is `http://127.0.0.1:8001/api/health`.

## Changes and scope

Created this report and the disposable synthetic fixtures, auth database, and smoke index/artifacts in `var/digup-smoke-test/`. `sample-notes.txt` was updated with the synthetic browser reindex marker. No dependencies were installed. No application source, authentication implementation, frontend design, DigUp source, model, or existing project index was changed. Test data and services were left available for manual review.

## Limitations

Only synthetic text, HTML, Markdown, PDF, and image fixtures were exercised here. Audio, video, code indexing, large archives, concurrent indexing, and production deployment were not part of this local smoke test. The FastAPI test instance is loopback-only and is not a production authentication boundary.
