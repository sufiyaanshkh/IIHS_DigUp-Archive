# Desktop atomic feature inventory — incomplete

This is a **partial inventory**, not a count of all Desktop features. The
[methodology](DIGUP_AUDIT_METHODOLOGY.md) identifies areas not fully traced.
Each ID links to its evidence and comparison in the
[atomic matrix](DIGUP_ATOMIC_PARITY_MATRIX.md). Descriptions below identify
the individual behavior; exact files and functions are in the linked rows.

| ID | Desktop behavior |
|---|---|
| SEARCH-001 | Request prefix keyword results while a query is being typed. |
| SEARCH-002 | Rank a query using available meaning and keyword signals. |
| SEARCH-003 | Calculate the strong prefix from the top score. |
| SEARCH-004 | Count kinds from the unfiltered strong prefix. |
| SEARCH-005 | Group PDFs and documents in one filter. |
| SEARCH-006 | Allow weaker matches to be expanded. |
| SEARCH-007 | Explain a result using meaning and keyword signals. |
| SEARCH-008 | Display matching-word markers as bold excerpt text. |
| SEARCH-009 | Supply clickable example queries. |
| SEARCH-010 | Request up to 120 results in the full search window. |
| PREVIEW-001 | Render a matched PDF page. |
| PREVIEW-002 | Mark search words on a rendered PDF page. |
| PREVIEW-003 | Fetch the selected document segment for passage preview. |
| PREVIEW-004 | Try Quick Look after matched-frame or page rendering fails. |
| PREVIEW-005 | Show a native file icon when a thumbnail is unavailable. |
| PREVIEW-006 | Request a new thumbnail when the result preview key changes. |
| MEDIA-001 | Decode an audio track to overlapping PCM windows. |
| MEDIA-002 | Sample timestamped, visually deduplicated video frames. |
| MEDIA-003 | Play a video from a matched moment. |
| MEDIA-004 | Show the audio segment location. |
| INDEX-001 | Start a helper for indexing and synchronization. |
| INDEX-002 | React to folder changes by requesting synchronization. |
| INDEX-003 | Reconcile missing indexed records after a crawl. |
| INDEX-004 | Resume processing long PDFs and documents in steps. |
| CODE-001 | Extract notebook cells rather than outputs. |
| CODE-002 | Divide source text into line-oriented stretches. |
| STORAGE-001 | Migrate index schema transactionally. |
| MODEL-001 | Locate the pinned EmbeddingGemma model files. |

This inventory excludes countless potentially relevant behaviors still awaiting
inspection. It does not assert that any unlisted Desktop feature is absent.
