# Stage 4F — DigUp model-backed indexing runtime resolution

## Outcome

The recurring `worker error: can't create a llama.cpp context` is caused by running the Metal-enabled DigUp process inside the restricted Codex command sandbox. In that environment, llama.cpp cannot create a Metal command queue. The unchanged existing FastAPI integration test passes when run outside the restricted sandbox on this Mac, with the same Python, CLI, model files, process arguments, and filtered child environment. No source or configuration change is needed.

The browser adapter remains unchanged. For local model-backed indexing on this machine, run the backend/test process in a normal host Terminal with access to Metal. A restricted runner will reproduce the queue-creation failure.

## Reproduction and process evidence

The existing `ArchiveApiIntegrationTests.test_index_search_preview_metadata_download_concurrency_and_restart` was run with the exact pinned release CLI, synthetic text/image/video fixtures, and a new temporary index each time.

| Execution context | Result | IndexService log | Child exit |
| --- | --- | --- | --- |
| Restricted command sandbox | Integration assertion fails; job state is `failed` | Metal command queue creation fails before model context initialization | IndexService `0`; SearchService `0` |
| Host process with Metal access | Test passes in 4.066 s | Full model ready in 1.56 s; text-only query model ready in 0.48 s | IndexService `0`; SearchService `0`; restarted SearchService `0` |

The IndexService process returns zero after emitting its JSON `error` event; that is its upstream helper protocol behavior. The FastAPI adapter correctly treats the `error` event as a failed indexing job. The unittest process returns 1 in the restricted run because the test asserts that indexing completed, and returns 0 in the host run.

### Restricted-run worker log

```text
load: control-looking token:     50 '<|tool_response>' was not control-type; this is probably a bug in the model. its type will be overridden
load: control-looking token:    212 '</s>' was not control-type; this is probably a bug in the model. its type will be overridden
load: '</s>' is a normal token here, removing it from EOG list
ggml_metal_init: error: failed to create command queue
ggml_backend_metal_device_init_backend: error: failed to allocate context
llama_init_from_model: failed to initialize the context: failed to initialize  backend
```

The test receives the original JSONL error message `worker error: can't create a llama.cpp context`; the adapter reports this as the failed job. The failure log is from llama.cpp's per-index `worker.log`, not a Python exception.

### Successful host-run worker logs

```text
[llama.cpp worker] ready in 1.56 s (full, llama.cpp b11461, vectors 1)
[llama.cpp worker] ready in 0.48 s (text-only, llama.cpp b11461, vectors 1)
```

The logs also contain non-fatal model-token warnings. No Metal initialization error appears in the successful run.

## Environment and configuration checked

- macOS 26.6.2, arm64; Swift 6.3.3; Python 3.14.7 in `backend/.venv`.
- The Mac reports 16 GiB RAM and 21 GiB available disk space at inspection time. `vm_stat` showed 3,910 free 16 KiB pages in that snapshot; it is time-varying. The identical integration run succeeds outside the sandbox, so available RAM is not the cause of this reproduced failure.
- The Xcode command-line tools are selected. `xcrun --find metal` reports that the standalone `metal` utility is unavailable; this does not prevent runtime model initialization outside the restricted process environment. The existing build uses embedded Metal shaders.
- `backend/engine/DigUp/Vendor/llama/BUILD` identifies `b11461`, Metal. `scripts/build-llama.sh` enables `GGML_METAL`, embeds its Metal library, and builds the multimodal library.
- The integration test uses the same Python 3.14.7 parent in both runs. The helper is the Swift CLI, not a Python embedding worker; `DIGUP_WORKER_DIR` is unset.
- `EngineSettings.process_environment()` passes the same allowlisted environment in both runs: `PATH`, `HOME`, `TMPDIR`, locale values, optional `DIGUP_DEVICE`, `DIGUP_BACKENDS`, `DIGUP_THREADS`, and dynamic-loader paths, plus `DIGUP_MODELS`. `DIGUP_DEVICE` was unset, so original default GPU offload was used. The child arguments were unchanged.
- The test starts SearchService's text-only encoder before IndexService's full encoder in both contexts. Both operate concurrently in the successful host run, so this test does not implicate simultaneous workers.
- The full model context parameters in upstream `LlamaEmbedder` are `n_ctx=2048`, `n_batch=2048`, `n_ubatch=2048`, `n_seq_max=16`, unified KV, embeddings enabled, and mean pooling. Text-only search uses `n_ctx=512`. On macOS the source defaults to `n_gpu_layers=999` unless the original `DIGUP_DEVICE=cpu` override is set.

These controlled runs rule out Python 3.14, the FastAPI process handoff, model lookup, model checksum/configuration, normal concurrent SearchService/IndexService startup, and this context configuration as causes. The distinguishing condition is the sandbox's inability to create the Metal command queue.

## Model identity and disposable index verification

The model paths, sizes, and SHA-256 values match the pinned declarations in `Sources/DigUpKit/ModelFiles.swift`:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `embeddinggemma-2-Q8_0.gguf` | 309,855,456 | `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135` |
| `mmproj-embeddinggemma-2-Q8_0.gguf` | 554,821,024 | `c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f` |

The successful integration test produced a disposable index with:

- SQLite `user_version = 5`, five synthetic files and eleven segments.
- Six non-null vectors, each 1,536 bytes (768 Float16 values); image and text files had vector-bearing segments.
- Eight FTS rows, `PRAGMA integrity_check = ok`, and no foreign-key violations.
- Successful original keyword and hybrid searches, image preview, original PNG download, video frame retrieval, concurrent searches, and SearchService restart.

The test used the original DigUp `IndexService` and `SearchService`; it did not substitute SQL, an embedding implementation, or a search path.

## Reproduction command

Run from a normal local Terminal, not from a process environment that denies Metal access:

```sh
cd /Users/macbookair/Desktop/iihs_Projects/digup-web/backend
PYTHONPATH=.:tests .venv/bin/python -m unittest test_archive_api.ArchiveApiIntegrationTests -v
```

The test creates and removes its own temporary media, authentication database, and index. It does not use the Application Support index or the project's persistent authentication databases.

## Changes and remaining limits

- No correction to the adapter, DigUp source, llama.cpp source/patch, model, schema, or runtime settings was made; the environment itself needs Metal access.
- The pinned submodule remains at `dc2651ad8299160bbe91e972f857e1a1599a8419` and its working tree is clean.
- Synthetic test scratch directories were removed after collecting logs and read-only index checks.
- This validates the local macOS build. It does not validate centralized Linux hosting, Entra sign-in, or deployment hardware/permissions.
