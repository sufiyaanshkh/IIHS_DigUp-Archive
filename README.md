# DigUp Web

A browser-based implementation of DigUp.

## Architecture

- frontend: Next.js, React and TypeScript
- backend: Python FastAPI
- engine: Original DigUp Swift engine
- AI: EmbeddingGemma 2 through llama.cpp
- database: SQLite and FTS5

## Development

See docs/architecture for system design.

Backend regression tests use disposable data: `cd backend && .venv/bin/python -m unittest discover -s tests -p 'test_*.py'`. The archive API integration test uses the original SearchService with a synthetic index for keyword search and image rendering; it mocks semantic inference and video-frame rendering. Those mocks do not verify the model or native video decoder.

## Search and playback

- Search the archive in Keyword or Hybrid mode. Hybrid reports when DigUp did not use meaning search.
- The existing file-kind filters use DigUp's original search `kinds` parameter before the result limit. Filter counts describe the first unfiltered matches up to the selected limit, not whole-index totals. A result card's tooltip and accessible label expose its original DigUp ranking score.
- The UI offers limits of 20, 50 and 100 results; the API accepts 1–100. DigUp's SearchService does not expose a semantic-only search mode or configurable ranking weights.
- Archive operators and administrators can select Code search or use the `code:` prefix to search configured code roots in DigUp's separate code index. Adding a folder does not start indexing.
- Audio and video results can be played when the browser supports their format. Playback uses authenticated, session-bound result handles and supports byte ranges; unsupported formats can be downloaded.
- PDF previews support page navigation. Video frames and audio/video playback support navigation to a time in seconds; previews use the original DigUp render operation and playback remains browser-format dependent.
- Result excerpts come from DigUp and can be expanded. Full segment text is not exposed: DigUp's `text` operation accepts a segment ID but does not identify its file, so an ID reused during indexing cannot be safely authorized against an existing result handle. DigUp's `summaries` operation describes indexing roots, not document summaries.
- Web-initiated indexing and automatic indexing are disabled. The sync API returns 409 and the control is disabled: DigUp's crawler can silently omit unreadable or disconnected subtrees, and its reconciliation can delete unseen records even without `--prune`. Its SQLite transaction does not validate crawl completeness. This restriction does not control or protect an independently running desktop app.
- This safeguard applies only after the updated backend and frontend are deployed; already-running older services are unchanged until restarted by their operator.
- Removing an archive or code root asks for confirmation. Search visibility changes immediately and orphaned exclusions are removed; the web adapter will not start indexing. External indexing may prune indexed records; source files are not deleted.
- Operators can request SearchService `prewarm` and `reload` from the engine controls. Prewarm reports the encoder state (including unavailable); reload is blocked while a web-owned indexing job is active and refreshes web search results. Coordinate external index owners separately: the web app cannot detect or control desktop indexing. Starting SearchService can create or migrate index files and recreate its preview cache.
- In the result grid, arrow keys move selection across and between visible rows. Escape clears a focused search field; composition and modified keystrokes are left to the browser. Native desktop shortcuts, Finder reveal, file copying and Quick Look are not available through the web adapter.

## Native integration and safety limitations

- On macOS, the original desktop [Engine](backend/engine/DigUp/Sources/DigUpApp/Engine.swift) owns [FolderWatcher](backend/engine/DigUp/Sources/DigUpApp/FolderWatcher.swift) (CoreServices FSEvents) and sends `sync` to its [IndexService](backend/engine/DigUp/Sources/digup/IndexService.swift). The Windows/Linux [shell](backend/engine/DigUp/shell/src-tauri/src/main.rs) owns its [native watcher](backend/engine/DigUp/shell/src-tauri/src/watcher.rs) and helper. IndexService accepts sync, stop and backfill commands on its owner's stdin; this is not an external desktop-watcher control interface. A safe integration needs an explicitly supported host-side ownership/control boundary, complete-crawl reporting and reconciliation safety, plus search reload coordination. The web app starts no replacement watcher.
- [SearchService](backend/engine/DigUp/Sources/digup/SearchService.swift) `text` returns text by segment ID alone. Segment IDs can be reused, so a session-bound result handle cannot safely establish that the text still belongs to the authorized file. SearchService `summaries` describes roots, not document summaries; neither unsupported operation is fabricated.
- macOS Vision, PDFKit, AVFoundation, Metal, Finder/Quick Look and native folder selection need host-native frameworks, permissions and lifecycle. Existing host-side rendering, playback and opt-in native picker are exposed only through their authenticated web routes; Finder reveal and Quick Look are not exposed. The native picker requires a verified local client and OS permission.

## Containers

The provided `frontend/Dockerfile` and `compose.yaml` package only Next.js; the current FastAPI backend must remain on the host with DigUp, models, index, FSEvents, native chooser and media frameworks. No host files are mounted into the container. The frontend port is bound to host loopback on 3017.

The host backend normally listens on loopback at port 8017. On macOS, container loopback is not host loopback: a secure, authenticated container-to-host transport to that existing service is required, but is not included or validated. Do not bind FastAPI publicly or send session cookies across an untrusted network. Native folder selection also requires the backend to verify a local client, which may not hold through a container proxy; it is unverified in this configuration.

Only after a secure transport has been established and verified, set `ARCHIVE_API_ORIGIN` to its container-reachable origin for both the Compose build and runtime; do not put credentials in the URL. Next.js rewrites embed this value at build time, so rebuild when it changes. `npm ci` in the image build downloads the lockfile's dependencies. Do not start the container while another service occupies port 3017. Docker and the host connection have not been tested or deployed.
