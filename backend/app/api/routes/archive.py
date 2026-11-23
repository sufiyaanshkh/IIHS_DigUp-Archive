from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
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
from app.schemas.archive import CurrentChecksum, PhotographyMetadata, SearchRequest, SearchResponse

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


@router.post("/search", response_model=SearchResponse)
async def search(body: SearchRequest, request: Request,
                 session: AuthenticatedSession = Depends(current_session)):
    if body.scope == "code" and session.role not in ("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"):
        raise HTTPException(status_code=403, detail="You are not allowed to search code")
    if body.scope == "code" and body.kinds:
        raise HTTPException(status_code=422, detail="File kind filters are not supported for code search")
    try:
        return await _adapter(request).search(body.query.strip(), body.kinds, body.mode, body.limit,
                                              session_id=session.session_id, code=body.scope == "code")
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except DigUpUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="DigUp could not process this search") from exc


@router.get("/indexing/status")
async def indexing_status(request: Request,
                          _session: AuthenticatedSession = Depends(require_roles(
                              "SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"))):
    try:
        return await _adapter(request).indexing_status()
    except DigUpTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc


@router.post("/indexing/sync", status_code=202)
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
