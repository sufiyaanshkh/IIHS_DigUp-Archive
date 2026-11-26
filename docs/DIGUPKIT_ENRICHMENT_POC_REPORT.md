# DigUpKit enrichment proof of concept: stopped at API inspection

## Result and scope

**MISSING / NO GO:** The requested experiment was stopped during the required
public-API inspection. The inspected DigUpKit API exposes neither a dedicated
operation to replace one external enrichment while retaining a file's other
segments, nor an occurrence-search operation that returns every matching
location. These are required for the requested lifecycle and search
guarantees. The user explicitly required stopping if a required API is not
exposed. No experimental ingestion, build or search was attempted.

**CONFIRMED** below means observed in source, not demonstrated by execution;
**PARTIAL** means some relevant interface exists but does not meet the whole
requirement; **MISSING** means absent from the inspected public interfaces;
**UNKNOWN** means not established. Desktop was inspected at pinned commit
`dc2651ad8299160bbe91e972f857e1a1599a8419`. Its Git worktree was clean during
the initial check.

## Files created and commands

The only file created for this milestone is this report. The proposed
`experiments/digupkit-enrichment-poc/` directory was **not created** because
the stop condition was reached before construction. Consequently there are no
experiment artifacts to clean up. A future approved experiment must specify
its own isolated workspace and exact cleanup procedure.

Read-only checks included:

```text
git -C backend/engine/DigUp rev-parse HEAD
git -C backend/engine/DigUp status --short
swift --version
```

Swift reported version 6.3.3 on arm64 macOS. Source and existing local build
artifact listings were inspected. No build or test command was run, because
the API stop condition had already been met. Existing local artifacts do not
prove that a standalone build can link without downloading dependencies or
modifying the Desktop checkout.

## Public APIs and integration boundary

| API | Status and finding |
|---|---|
| [Package.swift](../backend/engine/DigUp/Package.swift#L79) | **CONFIRMED:** exports `DigUpKit` as a library product. **UNKNOWN:** a standalone package can actually resolve and link it offline without writing to the checkout; the macOS manifest also declares a Sparkle dependency. |
| [IndexStore.init](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L71) | **CONFIRMED:** accepts an index directory and optional file name and runs migration; it is not inherently restricted to disposable paths. No index was opened here. |
| [IndexStore.insert](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L254) and [Candidate](../backend/engine/DigUp/Sources/DigUpKit/Crawler.swift#L4) | **PARTIAL:** insert accepts a `Candidate`, but its memberwise initializer is not public. The public [Crawler.crawl](../backend/engine/DigUp/Sources/DigUpKit/Crawler.swift#L45) returns candidates and could be evaluated against a strictly synthetic folder if later approved. Existing [IndexStoreTests](../backend/engine/DigUp/Tests/DigUpKitTests/IndexStoreTests.swift#L5) use `@testable import`, so their candidate construction is not proof of an external initializer. |
| [IndexStore.addSegment](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L438) | **PARTIAL:** public API accepts file ID, kind, modality, `loc`, `locEnd`, text, excerpt and vector; it transactionally inserts a segment and FTS row. With no vector it records modality `none`. It does not expose an enrichment generation or idempotent replacement operation, and does not by itself establish file identity or ownership. |
| Replacement and [IndexStore.requeue](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L266) | **MISSING:** no dedicated public API was found to replace or delete only an external enrichment. `requeue` deletes **all** non-name segments and marks the file pending; it would also remove existing Desktop-generated image/audio/frame segments. The per-file [deleteSegments](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L465) helper is private. |
| [Searcher.init, reload and search](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L52) | **CONFIRMED:** public APIs exist for creating a searcher, reloading and running the original search. **UNKNOWN:** their runtime behavior on the requested fixtures; no model or index was run. |
| [SearchService.handle](../backend/engine/DigUp/Sources/digup/SearchService.swift#L124) | **CONFIRMED:** JSONL exposes `search`, `text` by segment ID and `reload`, among other operations. **MISSING:** an operation to import/replace extracted text or enumerate every matching occurrence. The raw `text` operation taking a segment ID is not a Web authorization contract. |
| [IndexService](../backend/engine/DigUp/Sources/digup/IndexService.swift#L14) | **CONFIRMED:** its documented commands are sync, stop and backfill controls, not enrichment import/replacement. |

`IndexStore.db` exposes a generic database wrapper, but public raw SQL is
not a demonstrated safe enrichment ownership or replacement contract.
This investigation did not use it to bypass the missing API or to create a
second index or search engine.

## Search and timestamp evidence

**UNKNOWN:** None of the following requested synthetic inputs was inserted or
searched, so there are no runtime hit paths, scores, segment IDs or
timestamps to report:

| Intended synthetic text | Intended location | Runtime result |
|---|---|---|
| `The Golden Gate Bridge` in `sample-image-001.jpg` | Image, no time | **UNKNOWN / not run** |
| `Emergency Exit` in `sample-video-001.mp4` | Frame at 42.5 s | **UNKNOWN / not run** |
| `The project will begin tomorrow` in `sample-video-002.mp4` | 18.2–21.7 s | **UNKNOWN / not run** |

**CONFIRMED in source:** [Searcher.search](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L115)
deduplicates keyword matches by file, selects at most one hit per file,
and can choose a semantic segment instead of the segment that matched words
([selection](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L190)).
Terms normally use OR and per-file coverage; this is not an exact-phrase
guarantee. Multiple segments can be inserted in principle, but the inspected
search interface does not return all matching occurrences. A single successful
keyword lookup, even if later observed at the expected time, would not prove
the same association for hybrid search or all occurrences.

Existing ranking code was not modified; whether behavior is unchanged after
enrichment is **UNKNOWN**, because changing indexed content can itself change
search results and no regression tests were run. The existing JSONL `text`
operation does not provide authorized occurrence enumeration; Web would need
to continue binding access to a validated session and file.

## Lifecycle, isolation and Desktop compatibility

| Requested test | Result |
|---|---|
| Repeated ingestion and replacement | **UNKNOWN / not run.** `addSegment` inserts; source shows no enrichment-specific idempotence or selective replacement API. |
| Requeue and deletion | **PARTIAL / source only.** `requeue` removes all non-name segments; [delete](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L298) removes a file and its FTS rows. No disposable test was run. |
| Reload and search during reload | **UNKNOWN / not run.** A reload API exists; concurrent safety and visibility were not tested. No concurrent writers were started. |
| Cleanup after failure | **UNKNOWN / not run.** `addSegment` uses a transaction, but interrupted lifecycle and ownership behavior were not exercised. |
| Schema version | **CONFIRMED / source only:** [IndexStore](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L25) declares version 5 and [migrate](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L88) rejects a newer version. Compatibility of any enriched index remains **UNKNOWN**. |
| Unchanged Desktop opening enriched index | **UNKNOWN / not run.** Linking the same library or retaining a version number would not alone prove full Desktop behavior or safe shared ownership. |

No production path was resolved or opened by this investigation. No
production media, SQLite database, index, application service, Web code,
Desktop source, model or configuration was changed. No dependencies or models
were downloaded or installed.

## Success criteria

| Criterion | Result |
|---|---|
| Link existing DigUpKit without Desktop changes | **UNKNOWN:** library product exists, but an isolated offline build was not attempted. |
| Store synthetic timestamped text safely | **UNKNOWN:** an insertion API exists; no insertion or safe-owner proof was performed. |
| Original search retrieves synthetic text | **UNKNOWN:** no synthetic search was performed. |
| Returned locations demonstrably match searched words | **MISSING as a general guarantee:** source selects one semantic or keyword segment per file, not all matched occurrences. No particular fixture was tested. |
| Replacement, deletion and reload work correctly | **MISSING selective replacement API; UNKNOWN runtime behavior:** no lifecycle tests were run. |
| No second search engine or duplicate ranking | **CONFIRMED for this inspection:** none was created; a working integration was not built. |
| Original Desktop compatibility with enriched index | **UNKNOWN:** no enriched index was created or opened. |

The milestone as defined has **not succeeded**. A safe single-engine
architecture is **UNKNOWN**, not disproved in every possible design; the
unchanged public interfaces inspected do not establish the required
enrichment replacement and occurrence guarantees.

## Authorization, ownership and next milestone

**PROPOSED, not implemented:** Any future integration must bind extraction to
an authorized canonical file and a checked source version, revalidate before
commit and access, reject stale or deleted sources, and bind transcript
requests to the existing session-scoped media handles. A single designated
index owner must coordinate ingestion, selective replacement, reprocessing,
deletion and search reload. Raw segment IDs must not grant access. See
[Web hit registration and media validation](../backend/app/engine/supervisor.py#L484).

**Recommended next milestone:** review these blockers and decide whether to
approve a separately maintained DigUp-based engine extension with explicit
selective enrichment lifecycle and matched-occurrence semantics. That would
require its own compatibility and safety design and a disposable proof; it is
not authorized by this report. Do not start OCR, transcription, translation,
Docker integration, or Web changes.
