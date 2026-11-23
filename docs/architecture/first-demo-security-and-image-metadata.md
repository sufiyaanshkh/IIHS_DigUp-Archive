# First demo: authentication, archive security and image metadata

## Authentication and authorization

The FastAPI Entra OIDC flow and local authentication use the existing HttpOnly server-side session cookie. Entra validates the IIHS tenant and member identity and provisions eligible users as `ACTIVE` / `EMPLOYEE`. No Microsoft password, access token, or ID token is stored in the browser. The frontend proxies `/auth/*` and `/api/*` through Next.js to the configured `ARCHIVE_API_ORIGIN`.

The Next.js home page checks the server session and redirects authenticated users to `/archive`. Archive and settings pages perform server-side session checks before rendering. The backend remains the enforcement boundary:

| Operation | Allowed roles |
| --- | --- |
| Search, result metadata, preview, image metadata, download | Any active role |
| Indexing status and operations | `SUPER_ADMIN`, `ADMIN`, `ARCHIVE_OPERATOR` |
| Settings and folder configuration | `SUPER_ADMIN`, `ADMIN`, `ARCHIVE_OPERATOR` |

State-changing archive/settings operations require the same-origin `Origin` and the session-derived `X-CSRF-Token`. The browser keeps this token only in React Query memory. A `401` redirects to sign-in; logout revokes the server-side session. The archive toolbar hides management controls from roles that cannot use them, but backend dependencies enforce each request independently.

Search results receive short-lived opaque handles. Each handle is bound to the session that created it. Preview, frame, metadata and download requests resolve the handle only for that session; API responses do not include archive filesystem paths.

## Image and video metadata endpoint

`GET /api/media/{handle}/image-metadata` accepts image, screenshot, and video results and returns nine nullable photography fields: `camera`, `lens`, `aperture`, `iso`, `shutter_speed`, `white_balance`, `exposure_compensation`, `location`, and `capture_time`, plus nullable file `dimensions`. This replaces the former grouped image response. It uses the same authenticated, session-bound reference used by preview and download. Other media types receive `415`; expired or other-session handles receive `404`; unavailable ExifTool receives `503`; unreadable media metadata receives `422`. Successful responses are marked `private, no-store`.

ExifTool is invoked with an argument array (not a shell), a 12-second timeout, JSON output, and the handle-resolved file path. A bounded in-memory cache is keyed by file identity, size and modification time. The endpoint does not change DigUp extraction, embeddings, ranking, or SQLite schema. It reads the original media file on demand.

The detail pane displays the nine photography fields plus filename, media type, current size, dimensions, and source-relative location. GPS coordinates are visible to active users authorized for the media; other-session and anonymous requests cannot retrieve them. Camera/lens serial numbers, owner, creator, copyright, and other metadata are not returned by this endpoint. Coordinates are not geocoded. ExifTool converts some GPS values to floating point and may discard trailing zeroes or round exceptionally precise values; exact original coordinate precision is therefore not guaranteed. Capture timestamps use original capture or content-creation tags, preserving available subseconds and offsets; filesystem and generic container creation/modification times are not substitutes.

ExifTool reads EXIF and supported XMP tags in images and supported QuickTime/container tags in videos. Available fields depend on the format and the original file. Generic QuickTime creation timestamps are not treated as original recording times. Missing or unrecognized values are null and shown as “Not available”. Unknown numeric white-balance codes are not guessed.

The existing media endpoint provides the source-relative path and current file size only after session-bound root validation; it does not expose absolute server paths. The inspector does not display importer, ingestion-job, provenance, or checksum information.

`GET /api/media/{handle}/checksum` calculates a current-file SHA-256 only when explicitly requested. It streams the authorized image/video, detects changes or replacement during the read, and does not write the file or index. Responses are `private, no-store`; failures do not expose source paths. This checksum is not a historical ingestion checksum. The inspector does not add AI object tagging, keyword mapping, or face recognition.

### Runtime requirement

ExifTool must be installed on the FastAPI host. `IIHS_EXIFTOOL` may point to an executable when it is not on `PATH`; it must be an executable file. The development machine was validated with ExifTool 13.55. ExifTool is an OS-level runtime tool and was not added to Python dependencies. On macOS with Homebrew, install with `brew install exiftool`.

### Verification limits

Synthetic EXIF/XMP fixtures and the authenticated metadata endpoint are covered by backend tests. The full DigUp indexing integration test remains dependent on successful llama.cpp context creation; it failed in this environment with the original worker error `can't create a llama.cpp context`. Live Microsoft Entra authentication also requires IIHS tenant/application configuration and was not exercised against IIHS services.
