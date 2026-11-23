# Copilot project handover audit

**Date:** 2026-11-23  
**Scope:** Current repository source, existing architecture reports, local runtime observations, and regression tests. This is a takeover audit, not a feature implementation or a production security certification.

## Executive summary

- The web adapter invokes the pinned original DigUp services; no replacement indexing, embedding, or ranking implementation was found.
- Local email/password authentication is **not implemented**. Registration and password recovery screens are previews; the working authentication implementation is Microsoft Entra OIDC. Live Entra sign-in has not been verified.
- The current source protects archive and settings APIs, but the **already-running backend does not match that source**: anonymous requests to its `/api/health` and `/api/settings/folders` returned 200. Its process started before the corresponding protected route files were modified. The frontend redirects anonymous users from protected pages, but that does not protect direct API requests. Treat the running instance as an older, insecure local development instance; do not expose it or use it for sensitive archive data. It was not stopped or restarted during this audit.
- There is a requirements conflict to resolve for the next milestone: new accounts must be ordinary `EMPLOYEE` users, but only `SUPER_ADMIN`, `ADMIN`, and `ARCHIVE_OPERATOR` can choose folders or start indexing. An ordinary newly registered user cannot complete the entire requested demo workflow without a separately authorised operator or an explicitly approved permission change.
- All 54 backend unittest cases passed on this Mac, including the original-engine synthetic indexing integration. Frontend lint passed with three warnings, and an isolated webpack production build passed.

## Repository and preservation

- Parent `git status --short`: `.gitmodules` and the DigUp submodule are staged additions; `.gitignore`, `README.md`, `backend/app/`, `backend/requirements.txt`, `backend/tests/`, `docs/`, `frontend/`, and `var/` are untracked. This audit did not reset or discard them.
- `backend/engine/DigUp` HEAD is `dc2651ad8299160bbe91e972f857e1a1599a8419`; `git status --short` in the submodule was empty.
- Both existing model files were read for SHA-256 verification; neither was changed:

| Model | Observed SHA-256 | Matches handover |
| --- | --- | --- |
| `embeddinggemma-2-Q8_0.gguf` | `2188ac1deca4b77dffefd603c2776a9d76d9d74ec01841392982ebb840b09135` | Yes |
| `mmproj-embeddinggemma-2-Q8_0.gguf` | `c4a8a52691ecef40618438928bdf9e68379b854e24166f292592353db0aab64f` | Yes |

No application source, dependency manifest, DigUp source, model, or existing archive data was intentionally modified. Tests used temporary data under `backend/tests/`; the build used a temporary copy under `var/`, removed after the build. No dependencies were installed.

## Implemented and verified

Verification here means the particular synthetic tests or observations described, not production readiness.

### Engine, search and media

- `backend/app/engine/supervisor.py` launches the existing `digup search-service` and `index-service`, using the original JSON Lines protocol. `keyword` and `hybrid` map to the original search operation's `meaning` flag. Search result handles are time-limited and session-bound; media access checks the configured roots.
- The current integration test indexed synthetic text, image, and video fixtures into a disposable index and exercised keyword and hybrid search, image preview and metadata, download, video-frame rendering, concurrent requests, and SearchService restart. It passed in this run with the pinned CLI and models.
- The prior [Stage 4F report](stage4f-engine-runtime-resolution.md) additionally records schema v5, 768-dimensional Float16 vectors, SQLite integrity checks, and successful model initialization on the host. Its restricted-sandbox Metal queue failure is an environmental finding, not a reason to alter the engine. This audit's successful integration run independently confirms the test passed in the present execution environment; it did not repeat Stage 4F's separate database inspection.
- The prior [Stage 4C report](stage4c-local-indexing-smoke-test.md) records synthetic PDF preview and other media tests. This audit did not repeat that exact PDF browser flow.

### Sessions, authorization and settings

- The current source issues opaque, server-side sessions with hashed session secrets, expiry and revocation checks, active-account checks, and `HttpOnly`, `Secure`, `SameSite=Lax`, `__Host-` cookies. Logout checks origin and CSRF, revokes the session, and clears the cookie. Tests exercise these behaviors.
- Current source requires an active session for archive APIs, requires management roles for indexing and settings, and requires origin/CSRF checks for mutating management requests. Frontend page guards also check sessions and roles. Backend tests verify authorization, session-bound handles, and settings protections.
- Settings source and tests cover persistent folder roots, exclusions and extensions, opaque directory references, root validation, code roots, and storage information. The folder browser is designed around macOS mounted volumes and explicit Documents, Desktop, and Downloads roots.
- ExifTool-backed image metadata is implemented separately from the DigUp index. Synthetic EXIF/XMP tests and the authenticated, session-bound metadata route passed. The dedicated response withholds GPS, camera/lens serials, and camera-owner fields; ExifTool is an external runtime requirement and was present during this audit.

## Implemented but not live-tested

- Microsoft Entra OIDC login, tenant/member checks, automatic `ACTIVE` / `EMPLOYEE` provisioning, session issuance, and the initial administrator bootstrap are present. Tests use synthetic claims and a fake Microsoft provider; no live IIHS tenant sign-in or Graph bootstrap was performed.
- The protected frontend-to-backend experience with a real Entra session, an authorised operator, and real approved media has not been validated in this audit. An anonymous browser request to `/archive` and `/settings` redirected to `/`, as the current frontend guard intends.
- Centralised, multi-user deployment, Linux hosting, live Entra account disablement/revocation propagation, and production HTTPS/proxy configuration are not verified.

## Partially implemented

- **Archive interaction:** Keyword/hybrid search, filters, selected-result details, still previews, and download exist. The web interface is not complete desktop parity. Video has frame previews rather than full playback/scrubbing; audio playback and timestamp navigation are not validated end to end.
- **Index lifecycle:** Manual start/stop, progress, and one active job are implemented. Automatic live watching, scheduled indexing, and desktop pause/resume are not provided by the web adapter. Helper/job state and media handles are process-local; coordinated multi-worker use is not established.
- **Code:** Code roots and exclusions can be configured for the original engine. Browser code search is explicitly unavailable and end-to-end code indexing/search has not been validated here.
- **Image metadata:** The dedicated metadata endpoint is implemented and synthetically tested, but comprehensive disclosure policy, real-world metadata coverage, and organisational approval remain open.
- **Account administration:** The Entra-only bootstrap can establish the first super administrator; broader role management and an end-to-end local demo account workflow are not established.

## Not implemented or not established

- Local email/password account creation, password hashing/storage, local sign-in, and demo-registration configuration. The registration form explicitly reports that no account is created; forgot/reset-password forms are previews. Login offers Microsoft sign-in only. Email verification currently redirects to the home page.
- Employee face enrollment, recognition, identity matching, and employee-name search: no implementation was found in the application source. Model selection, licensing, organisational authorisation, access control, retention, and deletion policies remain future work.
- Audio/video transcription, translation and transliteration workflows, full streaming playback, and institutional metadata search are not established by this audit. Capabilities in other DigUp versions must not be assumed for this pinned revision.

## Known limitations

- The running local backend currently permits anonymous access to some APIs, despite the protection in current source; see the process discrepancy below.
- Live Entra authentication, production HTTPS/proxy configuration, Linux hosting, and multi-user deployment remain unverified.
- `EMPLOYEE` users cannot manage folders or initiate indexing; a separately authorised operator is needed for that part of the demo.
- Model-backed indexing requires a host environment with Metal access on this Mac. The earlier restricted-sandbox failure does not justify changing DigUp.
- Indexing is manual, helper state is process-local, and web audio/video playback and code search are incomplete or unavailable.

## Current authentication integration and constraints

The only backend auth routes are Microsoft start/callback, session, and logout (`backend/app/api/routes/auth.py`). Microsoft user identity is the tenant/object-ID pair; email is profile data, not a unique identity key. The initial auth migration requires both Entra identity columns, and there is no password credential table or local credential verification. Any future local login therefore needs an additive, carefully migrated credential/identity design that does not conflate accounts by email or disrupt existing Entra users.

The existing session and authorization infrastructure should remain the common enforcement boundary. Registration must be explicitly demo-gated, never grant administrative privileges, and preserve secure cookie, expiry, CSRF, logout, and account-status behavior. Password hashing and dependency selection need explicit approval before installing any new package. The current cookie is always `Secure`; the demo's HTTPS or browser-localhost behavior and same-origin/CSRF configuration must be validated rather than assumed.

**Permission decision needed before implementation:** retain standard-user registration and use a separately provisioned operator to configure/index demo folders, or obtain explicit approval for a narrowly scoped alternative. Do not silently elevate self-registered accounts or bypass backend authorization.

## Running-process discrepancy

At audit time the local frontend on `127.0.0.1:3001` redirected anonymous `/archive` and `/settings` requests to `/`. The backend on `127.0.0.1:8003` returned 401 for anonymous `/auth/session`, but 200 for anonymous `/api/health` and `/api/settings/folders`; the frontend proxy also returned 200 for `/api/health`. Current route source instead requires an active session for health and a management role for settings. The backend process began at 10:03 on November 23, before the protected settings and archive route files' observed modification times. This supports a stale running process explanation, but the in-memory code was not independently inspected.

Do not treat the frontend redirect as an API security boundary. The instance is bound to loopback, not a public interface, but other local processes can reach it. Restarting it with the current source and a deliberately selected configuration, followed by anonymous and authorised API checks, is necessary before relying on its protections. The audit did not restart or reconfigure either existing service because doing so could interrupt ongoing work or change its data configuration.

## Validation performed

| Check | Result and scope |
| --- | --- |
| Submodule HEAD and working tree | Expected commit; clean `git status --short`. |
| Model SHA-256 | Both match the handover values. |
| `cd backend && .venv/bin/python -m unittest discover -s tests -v` | **54 passed**, no skips reported. Includes synthetic DigUp model-backed indexing, metadata, session, authorization, settings and contract tests. The test runner emitted a Starlette per-request cookie deprecation warning. |
| `cd frontend && npm run lint` | **Passed**, zero errors and three existing `@next/next/no-location-assign-relative-destination` warnings in login and API clients. |
| `npm run build -- --webpack` | **Passed** compilation, TypeScript, and static page generation using a disposable copy of frontend source/config and a symlink to existing dependencies. This avoided cleaning existing `.next` output or disturbing the running dev server. The staging copy was removed. |
| Live endpoints | Anonymous checks only; see running-process discrepancy above. No real archive files were indexed. |

The current backend virtual environment uses Python 3.14.7; Node reports 25.2.1. The repository uses `unittest`; `pytest` is not installed and was not needed.

## Documentation freshness

The [Stage 4D report](stage4d-settings-and-folder-management.md) and [desktop/web parity audit](digup-desktop-web-complete-parity-audit.md) describe their historical milestones; later changes add settings and role/session enforcement, so their earlier statements must not be read as current source. In particular, Stage 4D describes a loopback-only settings guard, while the current settings router uses role authorization; deployment must enforce appropriate network boundaries separately. `backend/app/auth/README.md` likewise describes an earlier authentication milestone and its scope statement predates current archive/settings protection. The [first-demo security and metadata report](first-demo-security-and-image-metadata.md) describes the later source, not necessarily code loaded by a previously started process.

## Recommended next milestone

After approval, implement **local demo authentication alongside Entra**, with explicit demo enablement, a reviewed password-hashing choice, an additive auth database migration, the existing session and backend authorization mechanisms, and focused regression tests. First resolve the ordinary-user versus folder/index-management role conflict and the local secure-cookie/origin setup. Validate on a newly started isolated backend with disposable database and synthetic media, retain the Entra tests, and do not alter original DigUp. Employee facial recognition remains a separate later milestone requiring organisational and licensing decisions.
    x§x 