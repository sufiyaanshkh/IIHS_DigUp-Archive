# DigUp Web: visual OCR and video speech audit

## Scope and conclusions

Source inspection only, 2026-11-24. Desktop checkout:
`dc2651ad8299160bbe91e972f857e1a1599a8419`; Web HEAD:
`c2a4b652336ae6d5956041d8dcc45380cf8c2ebf` plus pre-existing uncommitted
changes. No service, indexing job, model, fixture, or test was run for this
audit. Therefore **confirmed** below means confirmed in source, not verified
by execution; actual recognition accuracy and deployed behavior are unknown.

| Capability | Desktop source finding | Web source finding |
|---|---|---|
| Screenshot OCR and keyword search | **CONFIRMED**, on macOS, for files classified as screenshots; not all images. | **PARTIAL**: can search existing accessible OCR index entries; starting Web indexing is disabled. No end-to-end OCR test in this audit. |
| Ordinary image OCR | **MISSING** in the inspected image indexing branch: ordinary images are embedded, not OCR'd. | **MISSING** as an added Web workflow; no OCR producer found. |
| Video-frame OCR and text-to-time search | **MISSING** in the inspected video indexing path. Frames have image vectors and time ranges, not OCR text. | **MISSING**; frame preview and timestamp seeking exist but do not produce or search frame text. |
| Video audio extraction | **CONFIRMED** in source; decoded into audio windows for embeddings. | **PARTIAL**: existing indexed audio results and playback are exposed, but Web cannot start indexing. |
| Speech recognition/transcription | **MISSING** in the traced video/audio indexing and embedding pipeline; no recognizer or transcript producer found in the scoped source search. | **MISSING** in the inspected archive API and UI. |
| Word/sentence timestamps and spoken-phrase search | **MISSING** in the traced pipeline. Existing audio window times are not word or sentence timestamps. | **MISSING**; existing seek controls are not transcript search. |
| Translation to a selected language | **MISSING** in the traced pipeline and API; no translation implementation found in the scoped search. | **MISSING** in the inspected archive API and UI; this would be a new capability, not Desktop parity. |
| Actual OCR/STT accuracy and timestamp precision | **UNKNOWN**: no media was processed. | **UNKNOWN**: no browser or service was exercised. |

These are scoped source findings, not proof about arbitrary uninspected
extensions. In particular, do not infer transcription from audio embeddings
or translation from multilingual keyword normalization.

## Desktop: screenshot-to-search flow

1. [Crawler.crawl](../backend/engine/DigUp/Sources/DigUpKit/Crawler.swift#L43)
   walks configured roots, applies exclusions and classifies candidates.
   [Rules.classify](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Files+Apple.swift#L10)
   assigns `.screenshot` or `.image`, using
   [Rules.isScreenshot](../backend/engine/DigUp/Sources/DigUpKit/Rules.swift#L127):
   macOS screenshot metadata, recognized name prefixes, or a `Screenshots`
   parent folder. Portable classification uses extensions and naming rather
   than the macOS marker
   ([Files+Portable.swift](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Files+Portable.swift#L26)).
2. [Indexer.sync](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L90)
   queues new or changed files; `run`, `process`, and
   [prepare](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L401)
   decode image batches. `prepare` calls `OCR.text(ofImageAt:)` **only** when
   `screenshot` is true; a normal `.image` receives an empty OCR string.
   Small images may be skipped by the configured minimum size.
3. macOS [OCR.text(ofImageAt:)](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Extractors+Apple.swift#L107)
   reads the original at full resolution and passes it to
   [OCR.text(in:)](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Extractors+Apple.swift#L90).
   Apple's Vision `VNRecognizeTextRequest` uses accurate recognition, language
   correction, and automatic language detection; top candidates are joined
   into lines. This returns plain text, not bounding boxes or timestamps.
   The `try?` recognition call and empty-result fallback mean empty output
   does not distinguish all recognition errors from no recognized text.
4. [Indexer.images](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L540)
   embeds the image and, when OCR is nonempty and the image embedding
   succeeded, writes a separate `.ocr` segment with excerpt and full text,
   **without an OCR text vector**. The image vector supplies meaning search;
   OCR words supply keyword search. If the image embedding fails, this branch
   does not persist that image's OCR.
5. [IndexStore.addSegment](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L438)
   atomically stores a segment and, for nonempty text, an FTS5 row. Text is
   normalized with the original retained when different. The
   [schema](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L110)
   stores file ID, kind, `loc`, `loc_end`, excerpt, vector, and FTS text.
6. [Searcher.search](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L115)
   queries FTS, scores keyword and optional meaning signals and returns at
   most one chosen hit per file. Screenshot OCR can supply a marked snippet;
   the semantic image segment can borrow the OCR snippet when it has no
   location or excerpt. This is not a guarantee of exact phrase matching:
   terms are OR'd, qualification uses coverage, and a stronger semantic
   segment can be selected over the keyword segment.

Related but distinct: macOS
[PDFExtractor.pages](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Extractors+Apple.swift#L118)
also OCRs eligible rendered scans and some garbled text layers. PDF OCR is
not evidence of OCR for ordinary photos or video frames.

## Desktop: video frames and audio

[Indexer.prepare](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L453)
calls `VideoExtractor.keyframes`, then `AudioExtractor.windows` if an audio
track exists. It does **not** call `OCR.text` on those frames. On macOS,
[VideoExtractor.keyframes](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift#L64)
samples at a default three-second interval, enlarged as needed for a
1,200-frame limit; similar frames are discarded using an 8×8 average hash.
Each retained frame has a start and an end at the next retained frame or the
video duration. These bounds describe sampled visual segments, not the
precise interval that text appeared. Hash deduplication and sampling can miss
short-lived or visually similar text changes. Portable extraction uses
[FFmpeg and ffprobe](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Media+Portable.swift#L125).

For audio, macOS
[AudioExtractor.windows](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift#L12)
uses AVFoundation to decode the first audio track to 16 kHz, mono, 16-bit PCM
temporary WAV windows. Defaults are 30 seconds with a 25-second hop, i.e.
five seconds overlap; silent windows and insufficient tails are skipped.
The portable equivalent uses ffmpeg
([AudioExtractor.windows](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Media+Portable.swift#L78)).
These files are temporary: the indexing process removes scratch batches
([Indexer.process](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L221)).

[Indexer.video](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L706)
calls `embedImages` for frames and `embedAudio` for soundtrack windows, then
stores `.frame` and `.audio` segments with `loc`, `loc_end`, and vectors; it
does not pass recognized text. [Indexer.audio](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L690)
does the same for audio files. There is no transcript, language, word,
sentence, speaker, or translation record in these branches. An audio
`loc`/`loc_end` denotes an overlapping **window**, not the time of a word.

The [Embedder protocol](../backend/engine/DigUp/Sources/DigUpKit/Worker.swift#L24)
offers text, image, and audio **embedding** methods, not speech recognition or
translation. [LlamaEmbedder.embedAudio](../backend/engine/DigUp/Sources/LlamaRuntime/LlamaEmbedder.swift#L153)
returns vectors. The optional
[Python reference worker](../backend/engine/DigUp/worker/digup_worker.py)
also returns embeddings; its processor's chat template is not an implemented
chat, transcript, or translation workflow.

Scoped searches for transcription, speech-recognition, diarization and
translation terms across Desktop `Sources`, `shell`, and `worker`, together
with the actual media-to-store and worker paths above, found no such pipeline.
The graphics `translateBy` occurrence is a coordinate transform. An
uninspected external integration cannot be ruled out universally, but none
is exposed by the inspected Desktop processing/worker interfaces.

## Web: current path and limitations

1. [ArchiveShell](../frontend/src/components/archive/archive-shell.tsx#L15)
   calls [archiveApi.search](../frontend/src/lib/archive-api.ts), which posts
   to [archive.search](../backend/app/api/routes/archive.py#L103). Its
   [SearchRequest/SearchHit schema](../backend/app/schemas/archive.py#L12)
   has query, mode, kind, location and excerpt, but no transcript, language,
   translation, word or sentence fields.
2. [DigUpAdapter.search](../backend/app/engine/supervisor.py#L465) sends the
   original JSONL `search` operation to
   [SearchService.handle](../backend/engine/DigUp/Sources/digup/SearchService.swift#L124).
   [hitFields](../backend/engine/DigUp/Sources/digup/SearchService.swift#L360)
   includes segment kind, excerpt and optional `loc`/`loc_end`.
   [DigUpAdapter._register_hit](../backend/app/engine/supervisor.py#L484)
   revalidates the file against configured roots and exclusions, generates a
   session-bound handle, and maps those fields into the Web response. Thus
   already-indexed screenshot OCR can reach the existing search and excerpt
   UI, subject to those checks; no new extraction happens on search.
3. [PreviewPane](../frontend/src/components/archive/preview-pane.tsx#L41)
   displays excerpts as React text, uses a result's location for the initial
   media position and can seek via `navigateTime`. The
   [video_frame](../backend/app/api/routes/archive.py#L334) route asks
   [DigUpAdapter.render](../backend/app/engine/supervisor.py#L573) for a
   frame; [media_stream](../backend/app/api/routes/archive.py#L377) serves
   authenticated audio/video. This is existing generic frame/segment
   playback, not evidence that spoken or visual words were recognized.
4. [indexing_sync](../backend/app/api/routes/archive.py#L133) calls
   [IndexJob.start](../backend/app/engine/supervisor.py#L229), which
   deliberately raises a conflict. The UI also disables Index sources when
   `sync_available` is false
   ([ArchiveToolbar](../frontend/src/components/archive/archive-toolbar.tsx#L176)).
   The `_run` helper exists but is not reachable through `start`. There is no
   browser upload, OCR, transcription or translation operation in the
   inspected archive routes.

The original service has a `text` operation for a stored segment
([SearchService.handle](../backend/engine/DigUp/Sources/digup/SearchService.swift#L170);
[Searcher.text](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L363)),
but the Web archive API does not expose it. The Web adapter intentionally
uses opaque session-bound handles; a raw segment ID alone is insufficient to
establish that a current segment still belongs to the authorized file.

## Dependencies and reuse boundaries

| Component | Existing role | Limitation |
|---|---|---|
| Apple Vision, ImageIO | Screenshot and selected PDF OCR; image decoding on macOS. | [Portable OCR](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Images+Portable.swift#L73) reports unavailable and returns empty text. Vision's supported languages and quality depend on OS/runtime. |
| AVFoundation; ffmpeg/ffprobe | Decode video frames and audio windows, and obtain coarse media times. | AVFoundation is macOS-specific; portable paths require working ffmpeg/ffprobe and supported codecs. |
| `google/embeddinggemma-2`, llama.cpp, pinned GGUF files | 768-dimensional text/image/audio embeddings; identifiers and files are in [ModelFiles](../backend/engine/DigUp/Sources/DigUpKit/ModelFiles.swift#L7), runtime in [LlamaEmbedder](../backend/engine/DigUp/Sources/LlamaRuntime/LlamaEmbedder.swift#L1). | An embedding model is not a speech-to-text or translation service. No suitable transcription or translation model/service was identified. |
| SQLite FTS5, `IndexStore`, `Searcher` | Store/search text attached to existing segments, retrieve locations and excerpts. | No exposed service operation inserts new frame OCR or transcript segments; current search returns one selected segment per file and can prefer semantic over keyword location. |
| `SearchService`, Web adapter, authenticated media routes | Existing search, hit mapping, frame rendering, playback and seeking. | No service operation for frame OCR, transcription, translation or safe transcript ingestion. New text/time data must remain bound to an authorized, current file. |

Extending OCR to ordinary photos or video frames, and adding transcription or
translation, are **new behavior**, not a configuration switch in the inspected
original engine. The current Desktop source must remain unchanged, and the
user prohibits a second indexing/search engine. No supported ingestion
interface satisfying both constraints was found. Do not write directly to
the production SQLite database, bypass the disabled safety gate, pretend
the `text` read operation inserts text, or infer that a Web wrapper can call
internal Swift OCR/indexer methods. A compatible, authorized single-engine
extension/integration boundary must be established before feasibility can be
claimed; how to do so without changing Desktop remains **UNKNOWN**.

## Indexing and timestamp requirements

- Existing files need to be processed again, or otherwise safely enriched
  through an approved compatible interface, before newly extracted text
  could be searched. A code/UI change cannot retroactively populate OCR or
  transcripts. Ownership, concurrent engine access, transaction and
  lifecycle behavior, versioning, reprocessing, and deletion must be
  resolved first; do not assume direct database insertion is safe.
- [Crawler.crawl](../backend/engine/DigUp/Sources/DigUpKit/Crawler.swift#L43)
  continues past enumeration errors, while
  [Indexer.sync](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L90)
  removes unseen records except for roots that vanished. The existing Web
  block explicitly prevents a potentially destructive incomplete crawl; it
  must not be lifted without a verified safety/ownership solution.
- Frame OCR would need each recognized text occurrence bound to the correct
  source file and sampled frame time. Sampling and deduplication limit
  coverage; `loc_end` is a frame-segment boundary, not a verified text end.
  The current one-hit-per-file/hybrid selection cannot guarantee that the
  returned time corresponds to the requested words. Multiple occurrences
  and exact phrase semantics need explicit requirements and compatible
  engine support.
- Spoken retrieval would require an actual recognition component and
  persisted text-to-original-video time mapping. Word or sentence timestamps
  are **not supported by the inspected original engine**. Neither their
  availability nor accuracy can be promised; overlap, offsets, silence,
  timestamp precision and segment boundaries need evaluation with the
  chosen, explicitly approved technology.
- Translation would require a separately approved translation capability,
  language selection, source/translated-text association and error handling.
  It is new scope and is not supplied by the existing embedding model.

## Recommended sequence — no implementation authorized by this audit

1. **Establish feasibility and ownership:** preserve the existing disabled
   indexing gate and Desktop checkout. Determine whether an approved
   single-engine integration can add searchable, file-bound text and
   timestamps without modifying Desktop or creating another index/search
   engine. If not, stop and obtain an explicit architecture decision.
2. **Verify the existing screenshot path** on disposable data on macOS:
   classification → Vision OCR → original index/FTS → authorized Web
   search → excerpt. Record actual text and failures, not just model
   availability. This is the only inspected visual OCR flow already present.
3. **Conditional visual adaptation:** only after the integration decision,
   specify ordinary-image coverage and video-frame extraction, sampling,
   indexing, match selection and timestamp semantics. Reuse existing
   decode/search/preview components where their contracts support the
   requirements; do not describe them as an already working frame-OCR path.
4. **Conditional speech workstream:** separately approve a recognition
   technology and integration, then define language preservation, timestamp
   guarantees, overlapping-window handling and original-video seeking.
   Do not assume the original engine can generate word/sentence timestamps.
5. **Conditional translation:** only after transcript storage and permissions
   are specified, approve a translation mechanism and selected-language UX.
   Preserve the original transcript and timestamp mapping; no capability is
   currently available to reuse as a translator.

## Required tests — planned, not run

Use synthetic media and disposable indexes only; do not touch the live
archive. Actual recognition tests require an approved local fixture,
available runtime and explicit authorization to run isolated indexing.

| Area | Required checks |
|---|---|
| Existing screenshot OCR | Synthetic macOS screenshot with known multilingual text, non-screenshot control, image size limit, blank/unreadable image, OCR failure, text/excerpt persistence, keyword search and authorized Web display. Test portable host's explicit OCR-unavailable behavior. |
| Ordinary image OCR | If approved: photograph with printed text, blank/corrupt image, orientation and multilingual content, explicit failure reporting, safe reprocessing and unchanged unrelated image search. |
| Video-frame OCR | Synthetic timed visual text at known moments, short-lived text, near-identical frames, multiple occurrences, first/last frame and frame extraction failure. Verify returned timestamp refers to the frame containing the searched text, including hybrid-vs-keyword and one-file/multiple-hit cases; test preview/seek and inaccessible or expired handles. |
| Audio extraction | Disposable video with known audio, silence, no audio, short tails and overlapping 30/25-second windows; verify decoded format, offsets, errors and cleanup on each supported platform. |
| Speech and timestamping | If approved: synthetic speech with known language and word/sentence timing, silence, overlapping boundaries, multiple occurrences, end-of-file and noisy/unsupported audio; verify search selection, timing tolerance, seek, failures and absence of fabricated timestamps. |
| Translation | If approved: known transcript and selected language, preserved original and time association, unsupported language, unavailable translator, authorization and no silent success fallback. |
| Index safety and regression | Disposable incomplete/unreadable crawl, reconnect, failed/retried processing, cancellation, concurrent owner, changed/deleted file, stale segment/handle, permissions, rollback and preservation of pre-existing rows and ranking. Do not remove the indexing safety gate merely to run tests. |

Existing test references provide **limited** evidence, not execution in this
audit: [SearchTextTests.aWordInNoFileIsFoundAtTheStartOfLongerOnes](../backend/engine/DigUp/Tests/DigUpKitTests/SearchTextTests.swift#L56)
inserts synthetic OCR text rather than running Vision;
[LongFilesTests.aScannedPagesWordsAreFoundByKeywordSearch](../backend/engine/DigUp/Tests/DigUpKitTests/LongFilesTests.swift#L256)
tests a synthetic scanned PDF on Vision-capable systems;
[VideoTests.framesAreTimedWhenShown](../backend/engine/DigUp/Tests/DigUpKitTests/VideoTests.swift#L27)
tests frame timing, not frame OCR; and
[test_archive_contract.py](../backend/tests/test_archive_contract.py#L581)
tests session-bound byte ranges and mocked render calls, not actual media
decoding. [preview-pane.test.mjs](../frontend/tests/preview-pane.test.mjs#L149)
tests component timestamp behavior, not transcription or browser playback.
