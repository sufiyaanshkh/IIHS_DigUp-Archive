# Web atomic feature inventory — incomplete

The [atomic matrix](DIGUP_ATOMIC_PARITY_MATRIX.md) is the authoritative detail
for each row: it records the corresponding Web source, UI exposure, backend and
engine integration, relevant tests, manual verification and limitations.
The [methodology](DIGUP_AUDIT_METHODOLOGY.md) records uninspected areas.

| ID | Observed Web behavior or unresolved comparison |
|---|---|
| SEARCH-001 | Prefix request while typing. |
| SEARCH-002 | Hybrid request to the original search service. |
| SEARCH-003 | Receives and adjusts the original strong boundary. |
| SEARCH-004 | Counts the accessible unfiltered strong prefix. |
| SEARCH-005 | Maps both PDF and document hits to Documents. |
| SEARCH-006 | Expands the weaker results returned by the engine. |
| SEARCH-007 | Computes and displays an explanation. |
| SEARCH-008 | Displays excerpt markers as bold text. |
| SEARCH-009 | Displays archive search examples. |
| SEARCH-010 | Offers a selected limit of at most 100. |
| PREVIEW-001 | Requests an original-engine PDF page render. |
| PREVIEW-002 | Does not request Desktop-style page word marks. |
| PREVIEW-003 | Does not expose the original segment-text operation. |
| PREVIEW-004 | Does not supply a native Quick Look fallback. |
| PREVIEW-005 | Shows an existing kind icon after image-load failure. |
| PREVIEW-006 | Resets thumbnail failure state on URL change. |
| MEDIA-001 | Audio extraction exists in the engine, but Web start is disabled. |
| MEDIA-002 | Frame extraction exists in the engine, but Web start is disabled. |
| MEDIA-003 | Offers browser playback from a result location. |
| MEDIA-004 | Shows a segment location and supports browser audio playback. |
| INDEX-001 | Rejects starting an indexing job for safety. |
| INDEX-002 | No Web watcher was established by this inspection. |
| INDEX-003 | Reconciliation is present in the engine but Web start is disabled. |
| INDEX-004 | Backfill machinery exists; Web cannot start a new job. |
| CODE-001 | Original code extraction is available but Web indexing is disabled. |
| CODE-002 | Original code extraction is available but Web indexing is disabled. |
| STORAGE-001 | Original engine owns the index schema; runtime migration not tested. |
| MODEL-001 | Web uses the original search-service path; runtime model loading not verified. |

This is **not** a complete Web-only feature inventory. In particular,
authentication, administration, metadata, deployment and operational
capabilities have not been exhaustively audited.
