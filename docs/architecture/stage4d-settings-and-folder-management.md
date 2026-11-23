# Stage 4D — Settings and Folder Management

## Scope and upstream source

This implementation adds browser settings around the pinned DigUp CLI without replacing its indexer, search service, extractors, model, or index format. The engine submodule remains at `dc2651ad8299160bbe91e972f857e1a1599a8419` and has no local modifications.

The source of truth for desktop preferences is `backend/engine/DigUp/Sources/DigUpApp/AppSettings.swift` and `SettingsWindow.swift`; the behavior for time windows is in `Sources/DigUpKit/IndexHours.swift`. The web adapter can apply source folders, skipped folders, skipped extensions, code roots, and code exclusions through the existing `index-service` CLI and SearchService `folders` JSON-lines operation.

## Original settings inventory and web mapping

| Original DigUp setting or control | Original default / validation | Web behavior |
|---|---|---|
| Folders to search (`roots`) | Empty on a fresh desktop install; persisted as URLs. Desktop onboarding requires explicit folder selection. | Configurable in Folders using opaque browser references; server stores canonical paths. The web adapter seeds the first settings document from its existing server root configuration. |
| Skip these folders (`excludedFolders`) | Empty by default; folders must be inside selected roots. | Configurable; backend rejects paths outside configured roots and sends `--exclude` to IndexService and `skipped` to SearchService. |
| Skip these file types (`excludedTypes`) | Empty by default; upstream normalizes forms such as `HEIC, .txt, *.md` to lowercase extensions. | Configurable; accepts one extension at a time, strips a leading `.` or `*.`, lowercases, deduplicates, and validates a bounded extension token. Sends repeated `--exclude-ext` and SearchService `types`. |
| Index directory (`indexDirectory`) | `~/Library/Application Support/DigUp/index.noindex` in the desktop app. | Read-only generic location label; backend continues using its existing `IIHS_DIGUP_INDEX_DIR` / project-local development default. Not redirected to the desktop index. |
| Model directory (`modelsDirectory`) | `ModelFiles.installed`; passed to helpers as `DIGUP_MODELS`. | Read-only generic location label and actual required-file availability. No model download, replacement, or relocation controls. |
| Search shortcut (`hotkey`) | `cmd+shift+space`. | Displayed as desktop-only. A global macOS shortcut has no browser equivalent. |
| Open DigUp when you log in | Read from macOS `SMAppService` state; no fixed app preference default. | Displayed as desktop-only; web service does not change login items. |
| Check for updates automatically / Check Now | Sparkle updater preference and action; automatic check behavior is owned by Sparkle. | Displayed as desktop-only; no updater is exposed through the web adapter. |
| Index on battery power (`indexOnBattery`) | `true`. If false, the initial backfill waits for charger power; new files still index. | Displayed as desktop-only. This server process does not implement macOS power monitoring. |
| Index only at set hours (`indexHoursOn`, `indexHours`) | Off by default. Retained time window defaults to 01:00–07:00 (`60`–`420` minutes after midnight). `IndexHours` normalizes minute values modulo 1440; equal start/end means all day; ranges can cross midnight. | Displayed as desktop-only. No scheduler, watcher, or time-based indexing was added. Web indexing starts only when requested. |
| Encoder idle timeout (`encoderIdleSeconds`) | 600 seconds in `AppSettings`; app-only setting, clamped to at least 1 second. | Not exposed as a browser control. Existing web adapter timeout configuration remains server-side. |
| Onboarded (`onboarded`) | `false` until desktop onboarding completes. | Desktop onboarding state; no browser setting. |
| Code roots (`codeRoots`) and skipped code folders (`codeExcludedFolders`) | Empty roots means code search is off; code exclusions are inside selected code roots. | Configurable in Code; sent using original `--code-root` and `--code-exclude` arguments and SearchService `code_roots` / `code_skipped`. Archive operators can search the separate code index using the Code scope or `code:` prefix. Adding roots does not start indexing. |
| Open code in (`codeEditor`) | Optional bundle ID; desktop discovers installed supported editors and falls back to the default app. | Displayed as desktop-only. A browser cannot launch a server-installed editor. |
| Code quiet timeout (`codeQuietSeconds`) | 60 seconds by default; used by the desktop app's code-index behavior. | Not exposed as a control. The web adapter delegates work to the original IndexService and does not add a watcher. |
| Folder indexing progress / pause | Desktop `IndexProgress` reports progress and can pause/resume its app-managed job. | Web toolbar already exposes start/stop and status. Pause/resume is not present in the current IndexService browser contract. |
| Storage size, model status, privacy/license information | Desktop reads the real local index/model state. | Storage tab reads current backend index database file sizes, volume free space, model file sizes/presence, and the SearchService encoder status. Paths are represented by generic labels. |

The General tab is deliberately read-only: the original General controls depend on the native app, macOS login items, Sparkle, or a global hotkey. The `manual` behavior shown there describes the web adapter, not a new persisted DigUp preference. There is no writable General preference in this stage.

## Settings persistence

- Settings are separate from `auth.sqlite` and from both DigUp SQLite indexes.
- The default document is `var/settings.json`; `IIHS_SETTINGS_PATH` can select another location.
- The versioned JSON document stores roots and exclusions as server-only canonical paths, plus user-facing labels and relative paths. The HTTP response never returns those absolute paths.
- A setting update validates a candidate document, serializes it to a same-directory temporary file with mode `0600`, flushes it, then atomically replaces the settings file. Invalid existing JSON is left untouched and startup fails clearly rather than resetting settings.
- If the settings document does not exist, its initial folder configuration is seeded from the existing `EngineSettings` root configuration. Defaults are not written until a user changes a setting.

## HTTP API

All settings routes are under `/api/settings` and require an authorized management session. The native-picker route additionally checks the backend peer for loopback; a proxy can obscure the original client, so both servers must be bound to loopback. The existing Next.js same-origin `/api/*` rewrite forwards requests to FastAPI.

| Method and path | Request | Response / behavior |
|---|---|---|
| `GET /api/settings` | — | `general`, `folders`, and `code` settings. |
| `GET /api/settings/general` | — | Manual web indexing behavior and original desktop-only General controls. No writable General preference exists in this adapter. |
| `GET /api/settings/folders` | — | Included roots, folder exclusions, and normalized excluded extensions. |
| `POST /api/settings/folders/roots` | `{"directory_ref":"opaque-ref"}` | Adds an included folder; returns Folders settings. |
| `DELETE /api/settings/folders/roots/{root_id}` | — | Removes a root and any exclusions that are no longer valid under remaining roots. |
| `POST /api/settings/folders/exclusions` | `{"directory_ref":"opaque-ref"}` | Adds an exclusion only inside an included root. |
| `DELETE /api/settings/folders/exclusions/{exclusion_id}` | — | Removes one exclusion. |
| `PUT /api/settings/folders/extensions` | `{"extensions":[".tmp","LOG"]}` | Normalizes and persists extension values; returns Folders settings. |
| `GET /api/settings/code` | — | Code roots/exclusions, live code index counters/state where available, and truthful browser-search/editor availability. |
| `POST /api/settings/code/roots` / `DELETE /api/settings/code/roots/{root_id}` | Opaque directory reference / ID | Adds or removes code roots. |
| `POST /api/settings/code/exclusions` / `DELETE /api/settings/code/exclusions/{exclusion_id}` | Opaque directory reference / ID | Adds or removes exclusions under code roots. |
| `GET /api/settings/volumes` | — | Mounted macOS volumes and the explicitly allowed Documents, Desktop, and Downloads locations, with opaque references and capacity/free-space values where available. |
| `GET /api/settings/browse` | `volume_ref` or `directory_ref`; optionally configured `root_id` and `section` | Lists eligible child directories, relative to the browsing root. No client-provided path is accepted. |
| `GET /api/settings/storage` | — | Pathless index/model location labels, total and per-database SQLite file sizes, free space, approved model file status, and encoder state. |

Common errors: `403` for an unauthorized request or a non-local native-picker peer; `409` for stale references or unavailable/disconnected locations; `404` for an unknown configured ID; `422` for invalid extensions, malformed input, or an exclusion outside its selected root; `503` if the native chooser is unavailable or DigUp cannot accept the live settings update. If a live SearchService update fails, the atomic settings write is retained and the response explains that DigUp will apply it on reconnect.

## Directory and volume safety

- **Native Add a folder:** the Folders tab can open a multi-select native chooser on the backend's local desktop. Set `IIHS_NATIVE_FOLDER_PICKER=1` on the backend and configure `IIHS_PUBLIC_ORIGIN` as a loopback origin. Both the frontend and backend must also be bound to loopback; a reverse proxy's loopback connection does not establish that its browser client is local. Restarting an existing backend to change its environment requires separate operational approval.
- The new `POST /api/settings/folders/native-roots` requires an active `SUPER_ADMIN`, `ADMIN`, or `ARCHIVE_OPERATOR` session and the existing CSRF/origin checks. It rechecks the session after the dialog closes. The browser does not submit arbitrary paths: the backend receives them from the native helper, validates the whole selection, and commits new nonduplicate roots together. Cancellation does not save settings or start indexing. Absolute paths remain in the local settings document, not the HTTP response.
- macOS uses the system `osascript` JavaScript bridge and `NSOpenPanel`; Windows uses PowerShell and the `IFileOpenDialog` API; Linux uses GTK 3 and PyGObject in the backend's Python environment. No packages are installed by this application. A missing helper, graphical desktop, or required GTK binding produces an error; there is no manual path fallback. On Windows, PowerShell execution policy is respected and Python must support junction detection. Settings files inherit their parent directory's Windows ACL; use an appropriately restricted settings directory.
- Selection and validation respect OS filesystem permissions; a chooser grant does not guarantee that the backend process can read a folder. Root paths containing symbolic links or junctions are rejected rather than followed silently, which may exclude some linked mount paths. Disconnected or unreadable folders cause the entire new selection to be rejected without changing settings.
- The native picker does not change DigUp's recursion or indexing behavior. Containment of symlink descendants during an eventual crawl still requires platform-specific verification; selecting a folder is not proof that all descendants are eligible or accessible.

- In the legacy browser still used for exclusions and code folders, discovered macOS external volumes must be actual mounted directories under `/Volumes`; it also exposes only the explicit home folders `Documents`, `Desktop`, and `Downloads`.
- A volume is listed, never indexed automatically. The user chooses individual roots.
- Browser requests contain only short-lived random references (15 minutes), not filesystem paths. Directory listings are limited to non-hidden directories, never follow symlinks, and cap one response at 250 children.
- Every reference is resolved and canonicalized on the server; the selected path must remain inside its approved root. Symlink selections and path traversal are rejected.
- Previously configured roots remain visible with an `available` state if a drive disconnects. Index start revalidates every configured root and exclusion; it refuses to launch if any is missing, a symlink, or outside its matching root set.
- Settings routes are not an authentication boundary for a centrally hosted deployment. Before exposing the service beyond loopback, authentication/authorization, CSRF protections, and per-user source permissions must be in place.

## Original engine mapping and job lifecycle

`DigUpAdapter.configure()` updates the backend's current `EngineSettings`. If SearchService is already running, the adapter sends its original JSON-lines `folders` operation with `roots`, `skipped`, `types`, `code_roots`, and `code_skipped`. The next SearchService start receives equivalent original CLI flags.

Each IndexJob captures an immutable settings snapshot at start. Later settings edits update the next run but do not mutate the arguments of an active run. The original `digup index-service` remains the only indexer. The adapter passes original `--exclude`, `--exclude-ext`, `--code-root`, and `--code-exclude` flags; `--backfill` and `--linger 0` preserve the web job lifecycle. `--prune` is used only when archive roots are configured, so a code-only run cannot prune the main archive index. No Python file scanner, extraction pipeline, embedding implementation, new schema, or search algorithm is introduced.

The index directory, model directory, and model files remain server configuration, not browser-editable settings. The existing SQLite schema v5, FTS5, and original vector representation are untouched.

## Test cleanup

The Stage 4C service on port 8001 and its child DigUp SearchService were stopped gracefully after confirming the child had released the disposable index. The exact `var/digup-smoke-test/` directory was then removed (synthetic fixtures, `index/index.sqlite` and generated index files, temporary `auth.sqlite`, and generated previews/caches). The Stage 4C report was preserved. The port 8000 service, `var/auth.sqlite`, `var/digup-stage3a/`, and `var/stage3b-smoke/` were left untouched. `var/digup-smoke-test/` was verified absent.

## Verification

Backend settings and API contract tests use disposable temporary directories under `backend/tests`; no real archive media or default Application Support index is used by those tests. The full backend suite passed (49 tests) when run with Metal access. Frontend ESLint passed. `npx next build --webpack` passed TypeScript and static page generation; the default Turbopack builder could not start its worker process in this environment. The built Settings page was opened at `http://127.0.0.1:3001/settings` against a disposable FastAPI instance. The pathless Storage response reported both approved model files present at their expected sizes and a stopped lazy encoder; Code status reported CLI/model availability and code search unavailable. The temporary preview services and their scratch auth/index files were stopped and removed.

For a local demo that keeps the existing ports 8000 and 3000 untouched, use isolated project-local paths and ports:

```bash
cd /Users/macbookair/Desktop/iihs_Projects/digup-web/backend
IIHS_AUTH_DB_PATH=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/stage4d-dev/auth.sqlite \
IIHS_SETTINGS_PATH=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/stage4d-dev/settings.json \
IIHS_DIGUP_ROOTS='' \
IIHS_DIGUP_INDEX_DIR=/Users/macbookair/Desktop/iihs_Projects/digup-web/var/stage4d-dev/index \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In another terminal:

```bash
cd /Users/macbookair/Desktop/iihs_Projects/digup-web/frontend
ARCHIVE_API_ORIGIN=http://127.0.0.1:8001 npm run dev -- --hostname 127.0.0.1 --port 3001
```

Open `http://127.0.0.1:3001/settings`. Select only disposable or approved media folders before starting an index. The API origin in a production Next.js rewrite must be set at build time; the command above uses the development server.

## Remaining limitations

- This is a local-development configuration surface, not a centrally hosted access-controlled settings service.
- macOS schedules, power policy, global shortcut, login launch, Sparkle update controls, code editor launching, and desktop pause/resume remain desktop-only.
- The browser adapter can configure and search code roots using original DigUp. Code results and passages require an archive-operator role; indexing remains manual.
- The browser folder chooser's discovery is macOS-specific; deployment on another server OS needs a deliberately configured allowed-root policy before use.
- The original DigUp engine and model were not changed or rebuilt for this stage.
