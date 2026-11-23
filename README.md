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

## Search and playback

- Search the archive in Keyword or Hybrid mode. Hybrid reports when DigUp did not use meaning search.
- The existing file-kind filters use DigUp's original search `kinds` parameter before the result limit. Filter counts describe the first unfiltered matches up to the selected limit, not whole-index totals. A result card's tooltip and accessible label expose its original DigUp ranking score.
- The UI offers limits of 20, 50 and 100 results; the API accepts 1–100. DigUp's SearchService does not expose a semantic-only search mode or configurable ranking weights.
- Archive operators and administrators can select Code search or use the `code:` prefix to search configured code roots in DigUp's separate code index. Adding a folder does not start indexing.
- Audio and video results can be played when the browser supports their format. Playback uses authenticated, session-bound result handles and supports byte ranges; unsupported formats can be downloaded.
- Result excerpts come from DigUp and can be expanded. Full segment text is not exposed: DigUp's `text` operation accepts a segment ID but does not identify its file, so an ID reused during indexing cannot be safely authorized against an existing result handle. DigUp's `summaries` operation describes indexing roots, not document summaries.
