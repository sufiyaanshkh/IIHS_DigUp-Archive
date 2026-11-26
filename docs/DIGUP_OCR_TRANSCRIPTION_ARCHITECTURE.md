# DigUp Web: OCR and transcription architecture feasibility

## 1. Scope and verdict

This is a **source-only feasibility investigation**, not an implementation plan
approved for execution. The Desktop checkout inspected is pinned at
`dc2651ad8299160bbe91e972f857e1a1599a8419`; Web HEAD was
`c2a4b652336ae6d5956041d8dcc45380cf8c2ebf` with pre-existing local changes.
The [earlier audit](DIGUP_OCR_TRANSCRIPTION_AUDIT.md) traces the existing
media pipelines in detail.

**NO GO for production implementation under the current demonstrated
interfaces.** A non-production extension may be feasible, but safe ingestion,
matched-occurrence retrieval, lifecycle ownership, schema compatibility and
authorization are not demonstrated. In particular, adding extracted text to
FTS does not by itself guarantee that the returned timestamp belongs to the
searched words. The requested speech and translation features, and ordinary
image/video OCR, are new Web capabilities rather than verified Desktop parity.

Evidence labels: **CONFIRMED** means found in source or cited documentation,
not exercised here; **PARTIAL** means some but not all required behavior exists;
**MISSING** means absent from the traced implementation; **UNKNOWN** means not
proven; **PROPOSED** means a design requiring further approval and validation.
External links describe candidate technologies, not installed dependencies.
No code, service, model, configuration, or data was changed or run for this
investigation.

## 2. Current end-to-end architecture

**CONFIRMED:** The browser's
[ArchiveShell](../frontend/src/components/archive/archive-shell.tsx#L15)
calls the [archive API client](../frontend/src/lib/archive-api.ts), which
calls [archive.search](../backend/app/api/routes/archive.py#L103).
[DigUpAdapter.search](../backend/app/engine/supervisor.py#L465) sends a JSONL
request via [SearchProcess.request](../backend/app/engine/supervisor.py#L148)
to the pinned Desktop `search-service`. The Desktop
[SearchService.handle](../backend/engine/DigUp/Sources/digup/SearchService.swift#L124)
uses [Searcher.search](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L115)
and the Desktop index. The adapter removes inaccessible hits, creates
short-lived session-bound handles, and routes preview and media access through
revalidation; [PreviewPane](../frontend/src/components/archive/preview-pane.tsx#L41)
can seek to an existing media location.

Desktop owns its SQLite format and indexing:
[IndexStore](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L19)
stores files, segments, vectors and FTS in `index.sqlite`; the code index is
separate. [Database](../backend/engine/DigUp/Sources/DigUpKit/Database.swift#L19)
uses read/write/create, WAL, foreign keys and transactions. WAL permits
concurrent access but is **not** an application-level ownership or lifecycle
protocol. The indexer and search helper are distinct processes with their own
store connections; one authoritative engine/format is not the same as
enforced single-writer coordination.

**CONFIRMED safety blocker:** Web
[IndexJob.start](../backend/app/engine/supervisor.py#L229) unconditionally
blocks new indexing. An incomplete crawl combined with
[Indexer.sync](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L90)
reconciliation can delete unseen records. Do not lift or bypass this gate for
OCR, transcription, or a proposed extension.

## 3. Existing media capabilities

| Requirement | Status and evidence |
|---|---|
| Screenshot OCR | **CONFIRMED** for macOS screenshots: [Indexer.prepare](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L401) calls [Apple OCR](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Extractors+Apple.swift#L82), and [Indexer.images](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L540) stores keyword text only if image embedding succeeded. [Portable OCR](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Images+Portable.swift#L73) does not provide equivalent OCR. |
| Ordinary image OCR | **MISSING** in the traced image indexing branch; ordinary images receive image embeddings, not OCR text. |
| Video OCR | **MISSING**: [Indexer.video](../backend/engine/DigUp/Sources/DigUpKit/Indexer.swift#L706) stores frame vectors, not frame text. |
| Audio extraction | **CONFIRMED**: [Apple AudioExtractor.windows](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift#L12) and [portable counterpart](../backend/engine/DigUp/Sources/DigUpKit/Platform/Portable/Media+Portable.swift#L78) produce windows for audio embeddings. |
| Transcript, spoken-word search, translation | **MISSING** in the traced media, worker, storage, and Web paths. Existing audio embeddings are not speech recognition. |
| Preview and playback | **PARTIAL**: existing result locations and seek/preview can be exposed; no transcript view, word-level association, translated transcript, or occurrence-specific endpoint exists. |

These are scoped source findings; uninspected external integrations are
**UNKNOWN**. No accuracy or deployed behavior was measured.

## 4. Search and timestamp limitations

**CONFIRMED:** [Searcher.search](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L115)
ORs normal keyword terms, aggregates coverage per file, combines keyword and
meaning signals, and returns at most one chosen segment per file. A strong
meaning hit can win over the keyword segment. Therefore it does not promise
exact-phrase matching, all occurrences, or a returned location belonging to
the matched words. Ranking and the chosen segment must not be reconstructed in
Python or JavaScript.

The [Apple frame extractor](../backend/engine/DigUp/Sources/DigUpKit/Platform/Apple/Media+Apple.swift#L64)
samples approximately every three seconds by default, applies a 1,200-frame
limit and visual deduplication. Frame times identify samples and derived
intervals, not the exact start or end of on-screen text. Brief text and subtle
changes can be missed. Audio windows default to 30 seconds with a 25-second
hop; their times do not identify individual words. A model's estimated word
times and a sentence's derived bounds must not be represented as guaranteed
exact timestamps.

**UNKNOWN:** Required language coverage, acceptable OCR/ASR error rates,
timestamp tolerance, frame-sampling recall, exact phrase versus token semantics,
whether every occurrence must be returned, and whether translated text must
itself be searchable. These require explicit product decisions and tests.

## 5. Existing extension boundaries

| Boundary | Source evidence and feasibility |
|---|---|
| Search JSONL | **CONFIRMED:** [SearchService.handle](../backend/engine/DigUp/Sources/digup/SearchService.swift#L124) supports search, text retrieval, rendering, reload and other existing operations, but no external extracted-text insertion or occurrence-search operation. Proxying a new JSONL operation cannot make the unchanged handler understand it. |
| Index-service control | **CONFIRMED:** [IndexService](../backend/engine/DigUp/Sources/digup/IndexService.swift#L14) accepts `sync`, `sync code`, `stop`, and backfill controls; no extracted-text import operation. |
| Embedding worker | **CONFIRMED:** [Embedder](../backend/engine/DigUp/Sources/DigUpKit/Worker.swift#L24) and [workerService](../backend/engine/DigUp/Sources/digup/WorkerService.swift#L8) supply embeddings, not an OCR/ASR ingestion callback. Replacing the worker alone does not wire new text into indexing. |
| Swift library | **CONFIRMED:** [Package.swift](../backend/engine/DigUp/Package.swift#L79) exports `DigUpKit`; [IndexStore.addSegment](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L438) is public and transactionally adds a segment and FTS row. **UNKNOWN:** whether an independently maintained caller can safely own and coordinate enrichment, replacement, cleanup and concurrent use. Public visibility is not an advertised external-ingestion contract. With no vector, `addSegment` stores modality `none`. |
| Existing plugins | **MISSING** in the inspected service and worker interfaces: no general ingestion/search plugin hook was identified. A universal absence outside the inspected scope is **UNKNOWN**. |

[Searcher.reload](../backend/engine/DigUp/Sources/DigUpKit/Searcher.swift#L61)
reloads file/vector state; Web's
[DigUpAdapter._reload_search](../backend/app/engine/supervisor.py#L406)
uses the existing reload operation. Reload alone is not write coordination or
proof that every cross-process mutation is visible consistently.

## 6. Single-engine integration options

**PROPOSED, conditional:**

1. **Extraction workers only.** A worker receives authorized media or bounded
   decoded input and returns versioned text, locations and errors. It has no
   index/database access, search endpoint, or ranking. This separates
   extraction from the one authoritative indexing/search implementation.
2. **External Swift adapter using unmodified DigUpKit.** A separately
   maintained Swift component could call public APIs on a *disposable* index.
   This is technically plausible, not a supported plugin or a demonstrated
   safe production owner. It must prove lifecycle and cross-process
   coordination. Even if writes succeed, unchanged Searcher cannot guarantee
   the requested phrase/occurrence/timestamp behavior. Direct Python/JS
   SQLite writes are not an acceptable shortcut.
3. **Separately maintained compatible engine extension.** If the user permits
   a derivative or extension outside the pinned checkout, implement located-text
   ingestion and matched-occurrence search inside the **same deployed engine
   implementation**, reusing DigUpKit search/ranking rather than building
   parallel Python/JS ranking. This may require changing derived copies of
   original engine code, or a new engine-side service that links the library;
   the exact public API and compatibility are unproven. Keeping the original
   checkout untouched is not the same as never modifying any derived Desktop
   source: obtain explicit approval before adopting this option. Do not run
   competing original and extended writers against one index. Existing
   search behavior must remain the default and be regression tested.
4. **No extension:** Keep original services unchanged and do not claim the
   requested end-to-end features. Extraction in isolation cannot make them
   searchable with reliable matching locations.

A second worker is not itself a second search engine; an independent FTS
index, separate search service with duplicate ranking, or autonomous
index-writer with no shared ownership protocol would violate the constraints.
An engine-side occurrence mode would require explicit semantic and ranking
design, not a promise that unchanged `Searcher` already provides it.

## 7. Proposed data flow and worker contract

**PROPOSED**, only after the integration boundary and safety gate are resolved:

1. An authorized index owner selects an eligible file and records its
   canonical identity and version; workers receive only the least-privilege
   read access or predecoded, bounded input. The existing disabled Web indexing
   gate remains in force.
2. The owner invokes a local extractor with a versioned request: opaque job
   ID, media version, operation, language/model selection, sample time or
   audio offset, bounded limits and cancellation. The worker returns text,
   sample/start/end times, optional word positions/boxes, model/version and
   explicit errors. Never trust a worker-supplied path or file ID as authority.
3. The owner checks that the file is still the same version and authorized;
   it atomically replaces only that extractor's previous results and commits
   searchable text through the approved engine integration. It then
   coordinates reload and returns a clear success/failure status. Retries must
   be idempotent and cancellation/crashes must not leave partial searchable
   results.
4. The same engine searches and, where supported, identifies the matching
   occurrence and its location. Web only adapts authorized results, creates
   session-bound handles, revalidates media on access and displays returned
   text/times safely. A separate transcript/occurrence request must resolve
   through the existing handle, not a browser-supplied path or naked segment
   ID.

This is a logical interface, **not an existing JSONL operation**, approved
schema, or claim that all items can be implemented without engine changes.
No worker may download models at runtime without explicit approval.

## 8. Data model and ownership

**CONFIRMED:** [IndexStore schema](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L110)
has segments, location fields, excerpts and FTS, but not a structured
word/translation/box model. Schema version is 5, and
[IndexStore.migrate](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L86)
rejects newer versions. A migration or extra tables cannot be assumed safe
for unchanged Desktop, rollback, backup or shared concurrent use.

**PROPOSED logical records**, not a physical schema:

* An extraction generation refers to stable file identity plus version
  (device/inode where available, size, mtime and, where needed, a content
  fingerprint), extractor/model version and status.
* OCR observations carry original text, language/confidence when available,
  optional box coordinates and, for video, the actual sampled frame time;
  interval estimates must be labeled as such.
* Transcript segments carry original text, language, start/end and optional
  estimated word boundaries. Sentence bounds are derived from associated
  words/segments; a model segment is not automatically a sentence.
* Each translation is linked to the source segment and target language,
  preserves the original and its time interval, and records model/version.
  Translation does not imply word-to-word temporal alignment.

The physical location and transaction protocol for optional boxes, word
records and translations are **UNKNOWN**. A non-searchable auxiliary record
store is not automatically a second search engine, but adds lifecycle,
atomicity, backup and authorization complexity and needs approval; putting
searchable FTS in another store would violate the single-engine requirement.
Model/version changes, source edits, rename, delete, root removal, failed
reprocessing, and rollback must have explicit behavior.
[IndexStore.requeue](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L268)
deletes old segments; [delete](../backend/engine/DigUp/Sources/DigUpKit/IndexStore.swift#L302)
removes file-related FTS rows. Extra records outside those lifecycle paths can
become stale or orphaned. WAL does not fix that.

## 9. OCR technology comparison

| Candidate | Strengths and limits | Status |
|---|---|---|
| [Apple Vision](https://developer.apple.com/documentation/vision/recognizing-text-in-images) | On-device macOS OCR; supports observations, confidence and normalized boxes. Supported languages depend on OS/API revision and recognition mode. Existing Desktop wraps it as plain text; ordinary images/frames are not wired to it. Not available in Linux containers. | **PROPOSED** host-native baseline for macOS experiments; language and quality require validation. |
| [Tesseract](https://github.com/tesseract-ocr/tesseract) | Local CPU OCR, Apache-2.0 engine; [official usage](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html) documents language data, multilingual selection and TSV boxes/confidence. Language packs, image quality and license for each distribution must be checked. | **PROPOSED** portable CPU baseline. |
| [PaddleOCR](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html) | Detection/recognition pipelines and model choices; the cited model documentation reports differing language support, model sizes and vendor measurements. Runtime/platform support and each chosen model's terms must be verified separately. | **PROPOSED** comparison only, not a dependency decision. |

For video, use actual decoded presentation timestamps and explicitly test
sampling, orientation, duplicate frames, variable frame rate and short-lived
text. Denser sampling increases cost without proving continuous coverage.

## 10. Speech recognition and translation comparison

| Candidate | Strengths and limits | Status |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | CTranslate2 inference with CPU and supported CUDA configurations; `word_timestamps=True` exposes estimated word intervals. Segment boundaries are not guaranteed sentence boundaries. Models and accuracy must be assessed separately; loading by model name can download weights. | **PROPOSED** Linux/CPU or NVIDIA baseline. |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Local CPU and host-native Apple Silicon/Metal/Core ML options; GPU/platform support depends on build. Word-timing interface and quality for a chosen version remain **UNKNOWN** until tested. | **PROPOSED** host-macOS comparison. |
| [WhisperX](https://github.com/m-bain/whisperX) | Optional language-specific forced alignment. Its documentation notes unalignable words and overlapping-speech limitations. It adds models and resource cost; do not assume all languages or words align. | **PROPOSED** only if evaluated timing needs justify it. |
| [OpenAI Whisper](https://github.com/openai/whisper) | Multilingual recognition; its documented speech translation is into English with appropriate multilingual models, not arbitrary chosen target languages. The `turbo` model is not trained for translation. | **CONFIRMED** upstream capability, not a complete translation solution. |
| [Argos Translate](https://github.com/argosopentech/argos-translate) | Offline text translation with separately installed directional language packages and optional pivoting; coverage, quality, package and model terms vary. First use may need separately provisioned sentence resources. | **PROPOSED** for a later local translation trial; do not assume every pair is supported. |
| [NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M) | Its model card states CC-BY-NC and research-oriented restrictions, not a production-ready unrestricted license. | **NOT RECOMMENDED** without explicit legal and deployment review. |

Preserve original transcript and use its source time span for translated text;
machine translation can reorder or omit words. ASR segment boundaries,
forced-alignment estimates and sentence segmentation must each be labeled
separately. No speaker diarization is needed for this proposal.

## 11. Host, Docker, GPU and resource feasibility

**CONFIRMED:** Current [compose.yaml](../compose.yaml) contains the frontend
service; [frontend Dockerfile](../frontend/Dockerfile) runs Next.js. The
backend/engine are not already deployed as OCR or ASR containers.

| Deployment | Assessment |
|---|---|
| macOS host | **PROPOSED:** Keep pinned Desktop engine, its index and native filesystem operations host-side. Apple Vision and Apple-accelerated `whisper.cpp` require host-native execution for these benefits. Exact host hardware and resource headroom are **UNKNOWN**. |
| Linux CPU container | **PROPOSED:** A future isolated extraction worker may use local CPU models, with explicit scoped input/output and no direct index write. Architecture, performance and secure transport are not verified. |
| Linux NVIDIA container | **PROPOSED:** Only on compatible NVIDIA hardware with driver, CUDA/cuDNN versions and [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html); validate selected version combinations. |
| Docker Desktop on macOS | **CONFIRMED LIMITATION:** Do not assume Linux containers obtain host Apple Metal or Vision. [Docker GPU documentation](https://docs.docker.com/desktop/features/gpu/) describes conventional GPU support through Windows/WSL2; other Docker products are not evidence of generic macOS container Metal passthrough. |

[CTranslate2 installation](https://opennmt.net/CTranslate2/installation.html)
lists macOS ARM64/x86 and Linux wheels and separately describes GPU support;
do not infer Apple Metal acceleration for its Python wheel.
[whisper.cpp's published example](https://github.com/ggml-org/whisper.cpp)
lists roughly 75 MiB/273 MB for its tiny model and 2.9 GiB/3.9 GB for large
(disk/memory); these are project-reported illustrative figures, not
measurements, sizing guarantees, or total system requirements. Concurrent
DigUp models, decoding, OS, frame storage and translation add overhead.
Set concurrency/CPU/memory/disk limits and measure real-time factor, peak
memory, thermal effects and queue latency on approved synthetic workloads.
There is no defensible throughput or minimum hardware commitment from this
inspection.

## 12. Security, indexing safety and operations

**CONFIRMED:** [DigUpAdapter._register_hit](../backend/app/engine/supervisor.py#L484)
resolves hits under allowed roots and applies exclusions;
[media](../backend/app/engine/supervisor.py#L544) validates the session-bound
handle, expiry, root and current path. [active_session](../backend/app/auth/authorization.py#L21)
provides authenticated session context. Existing checks must apply to
extraction, transcript, translation, frame and occurrence access, including
after a file move, deletion, exclusion change or permission revocation.

**PROPOSED safeguards:**

* Never expose source paths, raw engine IDs, private text or worker stderr to
  unauthorized clients; render OCR/transcripts as text, not executable HTML.
* Enforce least privilege, local/private worker transport, bounded input,
  media timeouts, decoded-size/resource limits, cancellation and controlled
  temporary-file cleanup. Treat media and worker results as untrusted.
* Bind extraction to a validated file version and revalidate before commit;
  fail closed on missing roots, stale identity, unavailable permissions or
  authorization changes. Do not crawl or reconcile production data during
  feasibility work.
* One owner coordinates writes, retry, replacement, delete/requeue, reload and
  backup; failures are observable, not success-shaped. Explicitly protect
  sensitive transcripts and any temporary audio at rest and in logs.
* Back up and restore consistently with SQLite WAL and the approved ownership
  protocol; test restore/rollback and unchanged-Desktop compatibility on
  disposable copies before any production proposal. Schema upgrades and
  model downloads require separate approval.

## 13. Dependencies and implementation sequence

No dependency, model, service or runtime has been installed or started.
Exact versions, model licenses, system libraries, architecture support,
SBOM/update policy and offline provisioning remain approval gates.

**PROPOSED sequence, each stage separately approved:**

0. Resolve the meaning of the source-modification prohibition, exact search
   semantics and timing/quality requirements; keep production indexing blocked.
1. Safest first milestone: a disposable, synthetic **engine-boundary proof**.
   Link pinned DigUpKit where possible, create a temporary index, test
   timestamped text, requeue/delete, reload and actual selected search
   locations. Do not add a production writer, deploy a worker, or touch a
   production index. A failure is an acceptable result and may require an
   approved engine extension.
2. If approved and step 1 passes its explicit criteria, demonstrate a
   single-owner engine-side located-text/occurrence contract and authorization
   on disposable data; preserve current default search/ranking. Decide
   compatible storage and migration/rollback only with evidence.
3. Trial image OCR using synthetic multilingual images; then sample synthetic
   video frames and measure recall and sample-time accuracy. Compare Vision on
   macOS and Tesseract where portable support matters.
4. Trial local video audio decoding and ASR with synthetic speech. Validate
   offsets, overlap, word estimates, sentence derivation and matching
   occurrence. Compare faster-whisper and a host-native whisper.cpp build;
   add alignment only if justified.
5. Trial opt-in translation of source-linked transcript segments for approved
   language pairs, preserving originals and segment times. Decide explicitly
   whether translations participate in search.
6. Only after owner/safety, authorization, compatibility and performance
   acceptance: propose an incremental deployment and rollback plan for
   separate approval. This report does not authorize implementation.

## 14. Synthetic test and regression plan

* **Engine boundary:** temporary indexes only; unchanged Desktop opens the
  approved schema; failed or interrupted transactions, stale generations,
  repeated ingestion, requeue/delete/move, concurrent search/reload and
  migration/rollback. Demonstrate exact ownership and absence of duplicate
  search/ranking. Check unchanged default result order and score on fixed
  fixtures.
* **Search semantics:** text in several segments, several occurrences per
  file, OR terms versus phrase, terms split across segments, semantic match in
  a different frame, limit/pagination and empty results. Prove that each
  returned time corresponds to the actual qualifying occurrence under the
  approved semantics; report unsupported cases instead of fabricating times.
* **OCR:** generated multilingual text, blank/corrupt images, orientation,
  confidence/box handling, short-lived or visually similar frame text,
  variable frame rate and frame presentation-time offsets.
* **ASR:** generated licensed/synthetic audio with known spoken word and
  sentence times, silence, overlapping windows, offsets, repeated phrases,
  no audio, corruption, missing/unalignable word timings, cancellation and
  error propagation. Measure against user-approved timing and recognition
  tolerances.
* **Translation:** source and target preservation, supported and unavailable
  language pairs, Unicode, reordered words, segment association, failed
  model and no unintended network download; verify any approved translated
  search independently.
* **Web/security:** synthetic allowed/excluded roots, cross-session and
  expired handles, inaccessible or changed source files, content escaping,
  authorized preview/seek, request limits, no path or transcript leak, and
  existing search/UI regressions. Confirm the indexing safety gate stays
  active until a separately approved safe architecture exists.
* **Performance:** measure CPU, memory, disk, model startup, indexing latency
  and concurrent search responsiveness on approved synthetic fixtures and
  selected hardware; compare against agreed thresholds, not vendor figures.

No tests or benchmarks were executed in this investigation.

## 15. Final answers and approvals

**A. Without modifying Desktop source?** **UNKNOWN, conditional.** Extraction
can be separate and the pinned checkout can remain untouched. Existing public
library APIs suggest a disposable experiment, but full safe ingestion and
accurate occurrence retrieval have not been established. A derivative engine
could change original-derived code outside the checkout; whether that is
allowed needs explicit approval.

**B. One indexing and search engine?** **POSSIBLY, not proven.** A single
extended DigUp-based owner/search implementation with extraction-only workers
is a plausible design; no second search index or duplicated Python/JS ranking.
Its lifecycle, compatibility and requested matching semantics require proof.

**C. Host versus Docker?** Prefer the host for the existing macOS engine,
index, native filesystem access and Apple Vision/Metal. A future Linux
container may host a CPU/NVIDIA extraction worker with narrow access; current
Compose only supplies the frontend. No service changes are authorized now.

**D. Recommended stack?** For evaluation only: Apple Vision on macOS plus
Tesseract as the portable OCR comparison; faster-whisper on CPU/NVIDIA and
whisper.cpp on Apple Silicon as ASR candidates; Argos Translate for approved
offline language pairs. Choose versions and models only after quality,
resource, licensing and integration tests; no candidate resolves the engine
boundary by itself.

**E. Safest first milestone?** A separately approved synthetic, disposable
DigUpKit boundary experiment that verifies ownership, lifecycle and actual
matched-location behavior before any model or production integration.

**F. User decisions required:** permission for separately maintained
derived-engine changes versus an unchanged library only; target OS/hardware
and deployment; required languages and licensing; phrase/occurrence and
translated-search semantics; timing, accuracy, cost and privacy tolerances;
storage/schema compatibility and rollback; approved model provisioning; and
whether/when the existing indexing safety blocker may be addressed. None is
assumed approved by this report.
