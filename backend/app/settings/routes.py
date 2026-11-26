from __future__ import annotations

import asyncio
import ipaddress
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.authorization import AuthenticatedSession, active_session, current_session, require_csrf, require_roles
from app.auth.action_audit import audit_action
from app.engine.supervisor import DigUpTimeout, DigUpUnavailable
from app.settings.browser import DirectoryUnavailable
from app.settings.native_picker import NativePickerUnavailable, choose_folders
from app.settings.schemas import DirectorySelection, ExtensionUpdate
from app.settings.service import SettingsService


router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"))],
)


def _settings(request: Request) -> SettingsService:
    return request.app.state.settings_service


async def _apply(request: Request) -> None:
    settings = _settings(request)
    audit_action(request, active_session(request), "archive.settings_changed")
    try:
        await request.app.state.digup.configure(settings.engine_settings())
    except (DigUpTimeout, DigUpUnavailable) as exc:
        raise HTTPException(status_code=503, detail="Settings were saved; DigUp will apply them when it reconnects") from exc


@router.get("")
def read_settings(request: Request):
    return _settings(request).all()


@router.get("/general")
def read_general(request: Request):
    return _settings(request).general()


@router.get("/folders")
def read_folders(request: Request):
    return _settings(request).folders()


@router.post("/folders/roots")
async def add_folder_root(body: DirectorySelection, request: Request,
                          _csrf: None = Depends(require_csrf)):
    settings = _settings(request)
    try:
        result = settings.add_root(body.directory_ref, section="folders")
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.post("/folders/native-roots")
async def add_native_folder_roots(request: Request, _csrf: None = Depends(require_csrf),
                                  session: AuthenticatedSession = Depends(current_session)):
    try:
        if request.client is None or not ipaddress.ip_address(request.client.host).is_loopback:
            raise HTTPException(status_code=403, detail="Native folder selection is available locally only")
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Native folder selection is available locally only") from exc
    try:
        selected = await asyncio.to_thread(choose_folders, request.app.state.settings.public_origin)
        if not selected:
            return {"cancelled": True, "folders": _settings(request).folders()}
        renewed = require_roles("SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR")(current_session(active_session(request)))
        if renewed.session_id != session.session_id:
            raise HTTPException(status_code=401, detail="Authentication required")
        result = _settings(request).add_native_roots(selected)
    except NativePickerUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await _apply(request)
    return {"cancelled": False, "folders": result}


@router.delete("/folders/roots/{root_id}")
async def remove_folder_root(root_id: str, request: Request,
                             _csrf: None = Depends(require_csrf)):
    try:
        result = _settings(request).remove_root(root_id, section="folders")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.post("/folders/exclusions")
async def add_folder_exclusion(body: DirectorySelection, request: Request,
                               _csrf: None = Depends(require_csrf)):
    settings = _settings(request)
    try:
        result = settings.add_exclusion(body.directory_ref, section="folders")
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.delete("/folders/exclusions/{exclusion_id}")
async def remove_folder_exclusion(exclusion_id: str, request: Request,
                                  _csrf: None = Depends(require_csrf)):
    try:
        result = _settings(request).remove_exclusion(exclusion_id, section="folders")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.put("/folders/extensions")
async def update_file_extensions(body: ExtensionUpdate, request: Request,
                                 _csrf: None = Depends(require_csrf)):
    result = _settings(request).set_extensions(body.extensions)
    await _apply(request)
    return result


@router.get("/code")
async def read_code(request: Request):
    settings = _settings(request)
    health = request.app.state.digup.health()
    status = {"files": 0, "vectors": 0, "state": "unavailable", "roots": []}
    try:
        engine = await request.app.state.digup.status()
        indexing = await request.app.state.digup.indexing_status()
        status = {
            "files": engine.get("code_files", 0),
            "vectors": engine.get("code_vectors", 0),
            "state": indexing.get("state", "idle"),
            "roots": indexing.get("code_roots", []),
        }
    except (DigUpTimeout, DigUpUnavailable):
        pass
    return settings.code(index_status=status, indexing_available=(
        health["digup_cli_available"] and health["models_available"]
        and request.app.state.digup.index_job.snapshot()["sync_available"]
    ))


@router.post("/code/roots")
async def add_code_root(body: DirectorySelection, request: Request,
                        _csrf: None = Depends(require_csrf)):
    settings = _settings(request)
    try:
        result = settings.add_root(body.directory_ref, section="code")
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.delete("/code/roots/{root_id}")
async def remove_code_root(root_id: str, request: Request,
                           _csrf: None = Depends(require_csrf)):
    try:
        result = _settings(request).remove_root(root_id, section="code")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.post("/code/exclusions")
async def add_code_exclusion(body: DirectorySelection, request: Request,
                             _csrf: None = Depends(require_csrf)):
    settings = _settings(request)
    try:
        result = settings.add_exclusion(body.directory_ref, section="code")
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.delete("/code/exclusions/{exclusion_id}")
async def remove_code_exclusion(exclusion_id: str, request: Request,
                                _csrf: None = Depends(require_csrf)):
    try:
        result = _settings(request).remove_exclusion(exclusion_id, section="code")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _apply(request)
    return result


@router.get("/volumes")
def list_volumes(request: Request):
    return {"volumes": _settings(request).volumes()}


@router.get("/browse")
def browse_directories(
    request: Request,
    volume_ref: str | None = None,
    directory_ref: str | None = None,
    root_id: str | None = None,
    section: str = "folders",
):
    if section not in ("folders", "code"):
        raise HTTPException(status_code=422, detail="Unknown folder section")
    try:
        return _settings(request).browse(volume_ref=volume_ref, directory_ref=directory_ref,
                                         root_id=root_id, section=section)
    except DirectoryUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/storage")
async def storage_info(request: Request):
    engine = request.app.state.digup
    settings = engine.settings
    database_names = ("index.sqlite", "code.sqlite")
    index_files = [settings.index_dir / name for name in database_names]
    archive_size = index_files[0].stat().st_size if index_files[0].is_file() else 0
    code_size = index_files[1].stat().st_size if index_files[1].is_file() else 0
    storage_root = settings.index_dir
    while not storage_root.exists() and storage_root != storage_root.parent:
        storage_root = storage_root.parent
    try:
        index_free = shutil.disk_usage(storage_root).free
    except OSError:
        index_free = None
    model_files = []
    for name, expected in (("embeddinggemma-2-Q8_0.gguf", 309_855_456),
                           ("mmproj-embeddinggemma-2-Q8_0.gguf", 554_821_024)):
        file = settings.model_dir / name
        size = file.stat().st_size if file.is_file() else None
        model_files.append({"name": name, "available": size is not None,
                            "size_bytes": size, "expected_bytes": expected})
    try:
        runtime = await engine.status()
        runtime_state = runtime.get("encoder", "unknown")
        service_running = runtime.get("search_service") == "running"
    except (DigUpTimeout, DigUpUnavailable):
        runtime_state = "unavailable"
        service_running = False
    return {
        "index": {
            "location": "Configured archive index",
            "database_files": list(database_names),
            "size_bytes": archive_size + code_size,
            "archive_size_bytes": archive_size,
            "code_size_bytes": code_size,
            "free_bytes": index_free,
        },
        "models": {
            "location": "Configured model directory",
            "name": "EmbeddingGemma 2 Q8_0",
            "files": model_files,
            "all_available": all(item["available"] for item in model_files),
            "runtime_state": runtime_state,
            "search_service_running": service_running,
        },
    }
