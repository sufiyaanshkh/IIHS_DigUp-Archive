from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import stat
import sqlite3
from contextlib import closing
from urllib.parse import quote
from pathlib import Path
from threading import BoundedSemaphore
from typing import BinaryIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from app.auth.authorization import AuthenticatedSession, current_session, require_csrf, require_roles
from app.auth.action_audit import audit_action
from app.services.image_metadata import (
    MetadataExtractionFailed,
    MetadataToolUnavailable,
    image_metadata,
)
from app.engine.supervisor import (
    DigUpConflict,
    DigUpTimeout,
    DigUpUnavailable,
    MediaForbidden,
    MediaNotFound,
)
from app.schemas.archive import (
    ArchiveListing, ArchiveSource, ArchiveFolder, ArchiveItem, BackfillRequest, CurrentChecksum, EnginePrewarmResponse, EngineReloadResponse, IndexingStatus,
    PhotographyMetadata, SearchRequest, SearchResponse,
)

router = APIRouter(prefix="/api")
_checksum_slots = BoundedSemaphore(2)


def _adapter(request: Request):
    return request.app.state.digup


def _authorized_media(request: Request, handle: str, session: AuthenticatedSession):
    reference = _adapter(request).media(handle, session_id=session.session_id)
    if reference.code and session.role not in ("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"):
        raise HTTPException(status_code=403, detail="You are not allowed to access code")
    return reference


@router.get("/health")
def health(request: Request, _session: AuthenticatedSession = Depends(current_session)):
    return _adapter(request).health()


@router.get("/engine/status")
async def engine_status(request: Request,
                        _session: AuthenticatedSession = Depends(current_session)):
    try:
        return await _adapter(request).status()
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/engine/prewarm", response_model=EnginePrewarmResponse)
async def engine_prewarm(
    request: Request,
    session: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")),
    _csrf: None = Depends(require_csrf),
):
    try:
        result = await _adapter(request).prewarm()
        audit_action(request, session, "archive.engine_prewarm")
        return result
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="DigUp could not prewarm search") from exc


@router.post("/engine/reload", response_model=EngineReloadResponse)
async def engine_reload(
    request: Request,
    session: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")),
    _csrf: None = Depends(require_csrf),
):
    try:
        result = await _adapter(request).reload_search()
        audit_action(request, session, "archive.engine_reload")
        return result
    except DigUpConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="DigUp could not reload search") from exc


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request,
                 session: AuthenticatedSession = Depends(current_session)):
    if body.scope == "code" and session.role not in ("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"):
        raise HTTPException(status_code=403, detail="You are not allowed to search code")
    if body.scope == "code" and body.kinds:
        raise HTTPException(status_code=422, detail="File kind filters are not supported for code search")
    try:
        return await _adapter(request).search(body.query.strip(), body.kinds, body.mode, body.limit,
                                              session_id=session.session_id, code=body.scope == "code",
                                              prefix_last=body.prefix_last)
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="DigUp could not process this search") from exc


@router.get("/archive", response_model=ArchiveListing)
def browse_archive(
    request: Request,
    response: Response,
    session: AuthenticatedSession = Depends(current_session),
    source_id: str | None = None,
    folder: str = Query(default=".", max_length=1024),
    q: str = Query(default="", max_length=200),
    media_type: str | None = Query(default=None, pattern="^(image|video|audio|document|screenshot)$"),
    state: str | None = Query(default=None, pattern="^(done|partial|pending|failed|skipped|unindexed|unknown)$"),
    extension: str | None = Query(default=None, pattern="^[a-zA-Z0-9]{1,12}$"),
    min_size: int | None = Query(default=None, ge=0),
    max_size: int | None = Query(default=None, ge=0),
    modified_after: float | None = None,
    modified_before: float | None = None,
    sort: str = Query(default="name", pattern="^(name|modified|size|state)$"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000_000),
):
    """List supported files in configured roots and annotate them from DigUp's read-only index."""
    response.headers["Cache-Control"] = "private, no-store"
    settings_service = request.app.state.settings_service
    configured = settings_service.configured_archive_roots()
    sources = [ArchiveSource(**settings_service._public_entry(item)) for item in configured]
    empty = dict(sources=sources, source_id=None, folder=None, breadcrumbs=[], folders=[], items=[],
                 total=0, limit=limit, offset=offset, schema_version=None)
    if source_id is None:
        return empty
    selected = next((item for item in configured if item.id == source_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Archive source was not found")
    try:
        root = Path(selected.path).resolve(strict=True)
        if not root.is_dir():
            raise OSError
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Configured archive source is unavailable") from exc
    if folder != "." and (folder.startswith("/") or "\\" in folder or "\x00" in folder or
                           any(part in ("", ".", "..") for part in folder.split("/"))):
        raise HTTPException(status_code=422, detail="Invalid archive folder")
    relative_parts = () if folder == "." else tuple(folder.split("/"))
    try:
        current = root.joinpath(*relative_parts).resolve(strict=True)
        current.relative_to(root)
        if not current.is_dir():
            raise ValueError
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Archive folder was not found") from exc
    engine_settings = _adapter(request).settings
    exclusions = tuple(path.resolve() for path in engine_settings.excluded_folders)
    if any(current == excluded or excluded in current.parents for excluded in exclusions):
        raise HTTPException(status_code=404, detail="Archive folder was not found")

    if min_size is not None and max_size is not None and min_size > max_size:
        raise HTTPException(status_code=422, detail="Minimum file size must not exceed maximum")
    try:
        folders, file_rows = _scan_archive_folder(current, root, exclusions)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Configured archive folder cannot be listed") from exc

    # The root is the unified view (recursive); opening a folder shows only its immediate files.
    # shortcut: walk the source on each request, upgrade to a filesystem cache if large roots make listing slow.
    if folder != ".":
        file_rows = [row for row in file_rows if Path(row["path"]).parent == current]
    paths = [row["path"] for row in file_rows]
    index_rows: dict[str, tuple[str, str, str]] = {}
    index_version = None
    index_file = engine_settings.index_dir / "index.sqlite"
    if index_file.is_file() and paths:
        uri = f"file:{quote(str(index_file.resolve()), safe='/')}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as db:
                version = db.execute("PRAGMA user_version").fetchone()[0]
                if version == 5:
                    for start in range(0, len(paths), 500):
                        batch = paths[start:start + 500]
                        marks = ",".join("?" for _ in batch)
                        for indexed_path, indexed_kind, indexed_state, info in db.execute(
                            f"SELECT path,kind,state,info FROM files WHERE path IN ({marks})", batch
                        ):
                            index_rows[indexed_path] = (indexed_kind, indexed_state, info)
                    index_version = version
        except sqlite3.Error:
            index_rows.clear()

    needle = q.casefold()
    normalized_extension = extension.lower().lstrip(".") if extension else None
    selected_rows = []
    for row in file_rows:
        actual = Path(row["path"])
        relative_path = actual.relative_to(root).as_posix()
        kind = row["kind"]
        indexed = index_rows.get(str(actual))
        file_state = indexed[1] if indexed else "unindexed" if index_version == 5 else "unknown"
        info_text = indexed[2] if indexed else "{}"
        if media_type == "document" and kind not in ("pdf", "doc"):
            continue
        if media_type and media_type != "document" and kind != media_type:
            continue
        if state and file_state != state:
            continue
        if needle and needle not in relative_path.casefold():
            continue
        if normalized_extension and actual.suffix.lower().lstrip(".") != normalized_extension:
            continue
        if min_size is not None and row["size"] < min_size or max_size is not None and row["size"] > max_size:
            continue
        if modified_after is not None and row["modified"] < modified_after:
            continue
        if modified_before is not None and row["modified"] > modified_before:
            continue
        try:
            info = json.loads(info_text or "{}")
        except (TypeError, json.JSONDecodeError):
            info = {}
        metadata = {str(key): str(value) for key, value in info.items() if value is not None and isinstance(value, (str, int, float, bool))} if isinstance(info, dict) else {}
        selected_rows.append({"path": str(actual), "kind": kind, "size": row["size"],
                              "modified": row["modified"], "state": file_state, "info": metadata,
                              "relative_path": relative_path, "segment": "name", "score": 0.0,
                              "excerpt": None, "loc": None, "loc_end": None})

    total = len(selected_rows)
    sort_key = {"name": lambda row: (row["relative_path"].casefold(), row["relative_path"]),
                "modified": lambda row: (row["modified"], row["relative_path"]),
                "size": lambda row: (row["size"], row["relative_path"]),
                "state": lambda row: (row["state"], row["relative_path"])}[sort]
    selected_rows.sort(key=lambda row: row["relative_path"])
    selected_rows.sort(key=sort_key, reverse=direction == "desc")
    page_rows = selected_rows[offset:offset + limit]
    adapter = _adapter(request)
    items: list[ArchiveItem] = []
    for row in page_rows:
        safe = adapter._register_hit(row, session.session_id, root_hint=root, archive=True)
        if safe is None:
            continue
        items.append(ArchiveItem(**safe, relative_path=str(row["relative_path"]),
                                 source_id=source_id, source_name=selected.name,
                                 processing_state=str(row["state"])))
    return ArchiveListing(sources=sources, source_id=source_id, folder=folder,
                          breadcrumbs=_archive_breadcrumbs(selected.name, relative_parts),
                          folders=folders, items=items, total=total, limit=limit, offset=offset,
                          schema_version=index_version)


def _scan_archive_folder(current: Path, root: Path,
                         exclusions: tuple[Path, ...]) -> tuple[list[ArchiveFolder], list[dict[str, object]]]:
    files: list[dict[str, object]] = []
    folder_counts: dict[Path, int] = {}
    immediate_folders: list[Path] = []

    def walk(directory: Path, first_folder: Path | None = None) -> None:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    resolved = path.resolve(strict=True)
                    resolved.relative_to(root)
                    if any(resolved == excluded or excluded in resolved.parents for excluded in exclusions):
                        continue
                    if directory == current:
                        immediate_folders.append(resolved)
                        folder_counts[resolved] = 0
                    walk(resolved, first_folder or resolved)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                resolved = path.resolve(strict=True)
                resolved.relative_to(root)
                if any(resolved == excluded or excluded in resolved.parents for excluded in exclusions):
                    continue
                kind = _archive_file_kind(resolved)
                if kind is None:
                    continue
                stat_result = entry.stat(follow_symlinks=False)
                files.append({"path": str(resolved), "kind": kind, "size": stat_result.st_size,
                              "modified": stat_result.st_mtime})
                if first_folder is not None:
                    folder_counts[first_folder] = folder_counts.get(first_folder, 0) + 1

    walk(current)
    folders = [ArchiveFolder(name=path.name, relative_path=path.relative_to(root).as_posix(),
                             file_count=folder_counts[path])
               for path in sorted(immediate_folders, key=lambda item: item.name.casefold())]
    return folders, files


def _archive_file_kind(path: Path) -> str | None:
    extension = path.suffix.lower().lstrip(".")
    if extension in {"jpg", "jpeg", "jpe", "jfif", "png", "gif", "bmp", "tif", "tiff", "webp", "heic", "heif", "avif", "psd", "tga", "pnm", "ppm", "pgm", "cr2", "nef", "arw", "dng", "raf", "orf", "rw2"}:
        if path.name.startswith(("Screenshot", "Screen Shot", "CleanShot", "SCR-")):
            return "screenshot"
        try:
            if os.getxattr(path, "com.apple.metadata:kMDItemIsScreenCapture"):
                return "screenshot"
        except (AttributeError, OSError):
            pass
        return "image"
    if extension == "pdf":
        return "pdf"
    if extension in {"txt", "text", "md", "markdown", "typ", "rtf", "docx", "doc", "odt", "html", "htm", "xlsx", "pptx", "ods", "odp"}:
        return "doc"
    if extension in {"mp3", "m4a", "m4b", "aac", "wav", "wave", "flac", "ogg", "oga", "opus", "aiff", "aif", "wma", "amr", "caf", "mka"}:
        return "audio"
    if extension in {"mp4", "m4v", "mov", "mkv", "webm", "avi", "wmv", "flv", "3gp", "3g2", "mpg", "mpeg", "m2v", "ogv", "mxf"}:
        return "video"
    return None


def _archive_breadcrumbs(root_name: str, parts: tuple[str, ...]) -> list[ArchiveFolder]:
    crumbs = [ArchiveFolder(name=root_name, relative_path=".")]
    for index, name in enumerate(parts):
        crumbs.append(ArchiveFolder(name=name, relative_path="/".join(parts[:index + 1])))
    return crumbs


@router.get("/indexing/status", response_model=IndexingStatus)
async def indexing_status(request: Request,
                          _session: AuthenticatedSession = Depends(require_roles(
                              "SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"))):
    try:
        return await _adapter(request).indexing_status()
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@router.post("/indexing/sync", status_code=202,
             responses={409: {"description": "Indexing is unavailable until incomplete crawls are safe"}})
async def indexing_sync(
    request: Request,
    _session: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")),
    _csrf: None = Depends(require_csrf),
):
    try:
        result = await _adapter(request).index_job.start()
        audit_action(request, _session, "archive.indexing_started")
        return result
    except DigUpConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/indexing/stop", status_code=202)
async def indexing_stop(
    request: Request,
    _session: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")),
    _csrf: None = Depends(require_csrf),
):
    result = await _adapter(request).index_job.stop()
    audit_action(request, _session, "archive.indexing_stopped")
    return result


@router.post("/indexing/backfill")
async def indexing_backfill(
    body: BackfillRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")),
    _csrf: None = Depends(require_csrf),
):
    try:
        result = await _adapter(request).index_job.set_backfill(body.enabled)
        audit_action(request, session, "archive.backfill_enabled" if body.enabled else "archive.backfill_disabled")
        return result
    except DigUpConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/media/{handle}")
def media_metadata(handle: str, request: Request, response: Response,
                   session: AuthenticatedSession = Depends(current_session)):
    try:
        reference = _authorized_media(request, handle, session)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    hit = reference.hit
    info = hit.get("info") if isinstance(hit.get("info"), dict) else {}
    source_relative_path = None
    current_size = None
    if hit.get("kind") in ("image", "screenshot", "video"):
        try:
            source_relative_path = reference.path.relative_to(reference.root).as_posix()
            current_size = reference.path.stat().st_size
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Media is outside configured archive roots") from exc
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Media source is unavailable") from exc
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "name": reference.path.name,
        "kind": hit.get("kind"),
        "segment": hit.get("segment"),
        "location": hit.get("loc"),
        "location_end": hit.get("loc_end"),
        "modified": hit.get("modified"),
        "size": hit.get("size"),
        "metadata": info,
        "excerpt": hit.get("excerpt"),
        "source_relative_path": source_relative_path,
        "current_size": current_size,
    }


@router.get("/media/{handle}/image-metadata", response_model=PhotographyMetadata)
def image_media_metadata(
    handle: str,
    request: Request,
    response: Response,
    session: AuthenticatedSession = Depends(current_session),
):
    try:
        reference = _authorized_media(request, handle, session)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    kind = reference.hit.get("kind")
    if kind not in ("image", "screenshot", "video"):
        raise HTTPException(status_code=415, detail="Photography metadata is available for image and video results only")
    try:
        metadata = image_metadata(reference.path, kind)
        response.headers["Cache-Control"] = "private, no-store"
        return metadata
    except MetadataToolUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MetadataExtractionFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _stream_checksum(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


@router.get("/media/{handle}/checksum", response_model=CurrentChecksum)
def media_checksum(handle: str, request: Request, response: Response,
                   session: AuthenticatedSession = Depends(current_session)):
    try:
        reference = _authorized_media(request, handle, session)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if reference.hit.get("kind") not in ("image", "screenshot", "video"):
        raise HTTPException(status_code=415, detail="Checksum is available for image and video results only")
    if not _checksum_slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="Checksum service is busy")
    try:
        try:
            before = reference.path.stat(follow_symlinks=False)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(reference.path, flags)
            with os.fdopen(fd, "rb") as stream:
                opened = os.fstat(stream.fileno())
                if not stat.S_ISREG(opened.st_mode) or _file_identity(before) != _file_identity(opened):
                    raise HTTPException(status_code=409, detail="Media changed while calculating checksum")
                try:
                    verified = _adapter(request).media(handle, session_id=session.session_id)
                except MediaNotFound as exc:
                    raise HTTPException(status_code=404, detail=str(exc)) from exc
                except MediaForbidden as exc:
                    raise HTTPException(status_code=403, detail=str(exc)) from exc
                if _file_identity(verified.path.stat(follow_symlinks=False)) != _file_identity(opened):
                    raise HTTPException(status_code=409, detail="Media changed while calculating checksum")
                digest = _stream_checksum(stream)
                after = os.fstat(stream.fileno())
            current = reference.path.stat(follow_symlinks=False)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Media source is unavailable") from exc
        except OSError as exc:
            raise HTTPException(status_code=422, detail="Media checksum could not be calculated") from exc
        if _file_identity(opened) != _file_identity(after) or _file_identity(after) != _file_identity(current):
            raise HTTPException(status_code=409, detail="Media changed while calculating checksum")
        try:
            verified = _adapter(request).media(handle, session_id=session.session_id)
        except MediaNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MediaForbidden as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            if _file_identity(verified.path.stat(follow_symlinks=False)) != _file_identity(after):
                raise HTTPException(status_code=409, detail="Media changed while calculating checksum")
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Media source is unavailable") from exc
        response.headers["Cache-Control"] = "private, no-store"
        return {"sha256": digest}
    finally:
        _checksum_slots.release()


@router.get("/media/{handle}/preview")
async def media_preview(
    handle: str,
    request: Request,
    loc: float | None = Query(default=None, ge=0),
    pixels: int = Query(default=1024, ge=64, le=2048),
    session: AuthenticatedSession = Depends(current_session),
):
    try:
        _authorized_media(request, handle, session)
        preview = await _adapter(request).render(handle, at=loc, pixels=pixels,
                                                 session_id=session.session_id)
    except MediaNotFound as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _preview_response(preview)


@router.get("/media/{handle}/frame")
async def video_frame(
    handle: str,
    request: Request,
    at: float = Query(ge=0),
    pixels: int = Query(default=1024, ge=64, le=2048),
    session: AuthenticatedSession = Depends(current_session),
):
    try:
        _authorized_media(request, handle, session)
        preview = await _adapter(request).render(handle, at=at, pixels=pixels, frame_only=True,
                                                 session_id=session.session_id)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _preview_response(preview)


@router.get("/media/{handle}/download")
def media_download(handle: str, request: Request,
                   session: AuthenticatedSession = Depends(current_session)):
    try:
        reference = _authorized_media(request, handle, session)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return FileResponse(
        reference.path,
        filename=reference.path.name,
        media_type="application/octet-stream",
        content_disposition_type="attachment",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/media/{handle}/stream")
def media_stream(handle: str, request: Request,
                 session: AuthenticatedSession = Depends(current_session)):
    try:
        reference = _authorized_media(request, handle, session)
    except MediaNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MediaForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    kind = reference.hit.get("kind")
    if kind not in ("audio", "video"):
        raise HTTPException(status_code=415, detail="Playback is available for audio and video results only")
    guessed = mimetypes.guess_type(reference.path.name)[0]
    media_type = guessed if guessed and guessed.startswith(f"{kind}/") else "application/octet-stream"
    return FileResponse(reference.path, media_type=media_type, headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


def _preview_response(path: Path) -> FileResponse:
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, no-store",
                                 "Content-Disposition": 'inline; filename="preview.jpg"'})
