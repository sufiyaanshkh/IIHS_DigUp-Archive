from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.engine_config import EngineSettings

log = logging.getLogger(__name__)


class DigUpUnavailable(RuntimeError):
    pass


class DigUpTimeout(DigUpUnavailable):
    pass


class DigUpConflict(RuntimeError):
    pass


class MediaNotFound(LookupError):
    pass


class MediaForbidden(PermissionError):
    pass


@dataclass
class MediaReference:
    path: Path
    root: Path
    hit: dict[str, Any]
    session_id: str
    expires_at: float
    code: bool = False
    archive: bool = False


class SearchProcess:
    """Persistent SearchService bridge. Requests are correlated by the original JSON-lines IDs."""

    def __init__(self, settings: EngineSettings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._stderr: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self.encoder_event: dict[str, Any] | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def _start(self) -> None:
        async with self._start_lock:
            if self.running:
                return
            await self._discard()
            if not self.settings.executable_available:
                raise DigUpUnavailable("DigUp CLI executable is unavailable")
            self.settings.index_dir.mkdir(parents=True, exist_ok=True)
            args = [str(self.settings.executable), "search-service", "--index",
                    str(self.settings.index_dir), "--encoder-idle", str(self.settings.search_idle_seconds)]
            for folder in self.settings.excluded_folders:
                args.extend(("--exclude", str(folder)))
            for extension in self.settings.excluded_extensions:
                args.extend(("--exclude-ext", extension))
            for folder in self.settings.code_roots:
                args.extend(("--code-root", str(folder)))
            for folder in self.settings.code_excluded_folders:
                args.extend(("--code-exclude", str(folder)))
            args.extend(str(root) for root in self.settings.roots)
            self._ready = asyncio.Event()
            self.last_error = None
            try:
                self.process = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=self.settings.process_environment(),
                )
            except OSError as exc:
                self.process = None
                log.warning("Could not start DigUp SearchService (%s)", type(exc).__name__)
                raise DigUpUnavailable("Could not start DigUp SearchService") from exc
            self._reader = asyncio.create_task(self._read_stdout())
            self._stderr = asyncio.create_task(self._drain_stderr())
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=self.settings.request_timeout_seconds)
            except (asyncio.TimeoutError, Exception) as exc:
                await self._discard()
                if isinstance(exc, DigUpUnavailable):
                    raise
                raise DigUpUnavailable("DigUp SearchService did not become ready") from exc

    async def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        try:
            async for raw in self.process.stdout:
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                if message.get("event") == "ready":
                    self._ready.set()
                elif message.get("event") == "encoder":
                    self.encoder_event = {key: value for key, value in message.items() if key != "id"}
                request_id = message.get("id")
                future = self._pending.pop(str(request_id), None) if request_id is not None else None
                if future is not None and not future.done():
                    future.set_result(message)
        except Exception:
            log.exception("DigUp SearchService response reader failed")
        finally:
            self._ready.set()
            error = DigUpUnavailable("DigUp SearchService exited")
            self.last_error = str(error)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()

    async def _drain_stderr(self) -> None:
        assert self.process and self.process.stderr
        try:
            while await self.process.stderr.readline():
                # The helper can log local paths; keep stderr drained but never relay it to the browser.
                continue
        except Exception:
            return

    async def request(self, operation: str, *, timeout: float | None = None, **fields: Any) -> dict[str, Any]:
        await self._start()
        process = self.process
        if process is None or process.stdin is None:
            raise DigUpUnavailable("DigUp SearchService is not running")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {"id": request_id, "op": operation, **fields}
        try:
            async with self._write_lock:
                process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
                await process.stdin.drain()
            response = await asyncio.wait_for(
                future, timeout=timeout or self.settings.request_timeout_seconds
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise DigUpTimeout("DigUp SearchService request timed out") from exc
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            future.cancel()
            raise
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            self._pending.pop(request_id, None)
            raise DigUpUnavailable("DigUp SearchService connection failed") from exc
        if response.get("ok") is False:
            raise ValueError(str(response.get("error", "DigUp request failed"))[:500])
        return response

    async def close(self) -> None:
        if not self.running:
            await self._discard()
            return
        try:
            await self.request("quit", timeout=5)
        except Exception:
            pass
        process = self.process
        if process:
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        await self._discard()

    async def _discard(self) -> None:
        tasks = [task for task in (self._reader, self._stderr) if task and task is not asyncio.current_task()]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.process = None
        self._reader = None
        self._stderr = None
        self.encoder_event = None


class IndexJob:
    """Track web-owned IndexService state; starting new jobs is disabled for safety."""

    SYNC_UNAVAILABLE = (
        "Indexing is disabled because DigUp cannot verify that every subtree was enumerated; "
        "an incomplete crawl could remove indexed records."
    )

    def __init__(self, settings: EngineSettings, *, after_sync=None):
        self.settings = settings
        self.after_sync = after_sync
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stop_requested = False
        self._state: dict[str, Any] = {"state": "idle", "job_id": None, "events": []}

    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self._task and not self._task.done():
                raise DigUpConflict("An indexing job is already running")
            raise DigUpConflict(self.SYNC_UNAVAILABLE)

    async def _run(self, settings: EngineSettings) -> None:
        args = [str(settings.executable), "index-service", "--index", str(settings.index_dir),
                "--backfill", "--linger", "0"]
        if settings.roots:
            args.append("--prune")
        for folder in settings.excluded_folders:
            args.extend(("--exclude", str(folder)))
        for extension in settings.excluded_extensions:
            args.extend(("--exclude-ext", extension))
        for folder in settings.code_roots:
            args.extend(("--code-root", str(folder)))
        for folder in settings.code_excluded_folders:
            args.extend(("--code-exclude", str(folder)))
        args.extend(str(root) for root in settings.roots)
        try:
            self._process = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=settings.process_environment(),
            )
            if self._stop_requested and self._process.stdin:
                self._process.stdin.write(b"stop\n")
                await self._process.stdin.drain()
            stderr_task = asyncio.create_task(self._drain_index_stderr())
            assert self._process.stdout
            async for raw in self._process.stdout:
                try:
                    event = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                self._record(event)
            return_code = await self._process.wait()
            await stderr_task
            if self._state["state"] not in ("failed", "stopped"):
                if return_code == 0 and self.after_sync:
                    try:
                        await self.after_sync()
                        self._state["search_reload"] = "complete"
                    except Exception:
                        self._state["search_reload"] = "pending"
                self._state["state"] = (
                    "stopped" if self._stop_requested else
                    "completed" if return_code == 0 and not self._state.get("error") else "failed"
                )
                if return_code != 0:
                    self._state["error"] = "DigUp IndexService exited unexpectedly"
        except Exception as exc:
            self._state["state"] = "failed"
            log.warning("DigUp IndexService failed (%s)", type(exc).__name__)
            self._state["error"] = "DigUp IndexService could not complete the job"
        finally:
            self._state["finished_at"] = time.time()
            self._process = None

    async def _drain_index_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        async for _ in process.stderr:
            continue

    def _record(self, event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "scanning":
            self._state["state"] = "scanning"
            self._state["checked"] = event.get("checked", self._state.get("checked", 0))
        elif kind in ("sync", "file", "rest", "summary", "waiting", "idle"):
            self._state["state"] = "indexing" if kind not in ("waiting", "idle") else str(kind)
        if kind == "file":
            note = _safe_event_text(str(event.get("note", "")), self.settings)
            item = {"name": Path(str(event.get("path", ""))).name,
                    "kind": event.get("kind"), "state": event.get("state"),
                    "seconds": event.get("seconds"), "note": note[:300]}
            self._state["files"].append(item)
            self._state["files"] = self._state["files"][-100:]
            self._state["done"] = event.get("done", self._state.get("done", 0))
            self._state["total"] = event.get("total", self._state.get("total", 0))
        if kind == "error":
            self._state["state"] = "failed"
            self._state["error"] = _safe_event_text(str(event.get("message", "Indexing failed")),
                                                     self.settings) or "Indexing failed"
        event_fields = {
            "scanning": ("checked", "code"),
            "sync": ("new", "added", "changed", "moved", "removed", "unchanged", "ms",
                     "searchable", "pending", "unfinished", "vectors", "code"),
            "file": ("new", "done", "total", "kind", "state", "seconds", "code"),
            "summary": ("new", "states", "ms", "code"),
            "rest": ("done", "total", "code"),
            "waiting": ("for", "code"),
            "idle": ("files", "pending", "searchable", "unfinished", "vectors", "code"),
            "error": ("fatal", "code"),
            "exit": (),
        }
        safe_event = {"event": kind}
        for key in event_fields.get(str(kind), ()):
            if key in event:
                safe_event[key] = event[key]
        self._state.setdefault("events", []).append(safe_event)
        self._state["events"] = self._state["events"][-100:]

    async def stop(self) -> dict[str, Any]:
        async with self._lock:
            if not self._task or self._task.done():
                return self.snapshot()
            self._stop_requested = True
            self._state["state"] = "stopping"
            if self._process and self._process.stdin:
                self._process.stdin.write(b"stop\n")
                await self._process.stdin.drain()
            return self.snapshot()

    async def set_backfill(self, enabled: bool) -> dict[str, Any]:
        async with self._lock:
            process = self._process
            if (not self._task or self._task.done() or self._stop_requested or
                    process is None or process.returncode is not None or process.stdin is None):
                raise DigUpConflict("An active indexing job is required to change backfill")
            try:
                process.stdin.write(b"backfill on\n" if enabled else b"backfill off\n")
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionError, OSError) as exc:
                raise DigUpUnavailable("Could not send the backfill command to DigUp") from exc
            self._state["backfill_requested"] = enabled
            return self.snapshot()

    async def reload_search(self, search_process: SearchProcess) -> dict[str, Any]:
        async with self._lock:
            if self._task and not self._task.done():
                raise DigUpConflict("Wait until the indexing job finishes before reloading search")
            return await search_process.request("reload")

    def snapshot(self) -> dict[str, Any]:
        return dict(self._state, files=list(self._state.get("files", [])),
                    events=list(self._state.get("events", [])),
                    sync_available=False, sync_unavailable_reason=self.SYNC_UNAVAILABLE)

    async def close(self) -> None:
        await self.stop()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                if self._process:
                    self._process.terminate()
                try:
                    await asyncio.wait_for(self._task, timeout=3)
                except asyncio.TimeoutError:
                    if self._process:
                        self._process.kill()


class DigUpAdapter:
    def __init__(self, settings: EngineSettings):
        self.settings = settings
        self.search_process = SearchProcess(settings)
        self.index_job = IndexJob(settings, after_sync=self._reload_search)
        self._media: dict[str, MediaReference] = {}

    async def configure(self, settings: EngineSettings) -> None:
        self.settings = settings
        self.search_process.settings = settings
        self.index_job.settings = settings
        if self.search_process.running:
            await self.search_process.request(
                "folders",
                roots=[str(root) for root in settings.roots],
                skipped=[str(folder) for folder in settings.excluded_folders],
                types=list(settings.excluded_extensions),
                code_roots=[str(root) for root in settings.code_roots],
                code_skipped=[str(folder) for folder in settings.code_excluded_folders],
            )

    async def _reload_search(self) -> None:
        if self.search_process.running:
            await self.search_process.request("reload")

    async def prewarm(self) -> dict[str, Any]:
        response = await self.search_process.request("prewarm")
        return {"encoder": response["encoder"], "vectors": response["vectors"]}

    async def reload_search(self) -> dict[str, Any]:
        response = await self.index_job.reload_search(self.search_process)
        return {"vectors": response["vectors"], "code_vectors": response["code_vectors"]}

    def health(self) -> dict[str, Any]:
        return {"status": "ok", "digup_cli_available": self.settings.executable_available,
                "models_available": self.settings.models_available,
                "search_service_running": self.search_process.running,
                "index_job_state": self.index_job.snapshot()["state"]}

    async def status(self) -> dict[str, Any]:
        response = await self.search_process.request("status")
        return {"search_service": "running", "encoder": response.get("encoder", "unknown"),
                "vectors": response.get("vectors", 0), "files": response.get("files", 0),
                "code_vectors": response.get("code_vectors", 0), "code_files": response.get("code_files", 0),
                "searchable": response.get("searchable", 0), "pending": response.get("pending", 0),
                "unfinished": response.get("unfinished", 0),
                "models_available": self.settings.models_available,
                "indexing": self.index_job.snapshot()}

    async def indexing_status(self) -> dict[str, Any]:
        snapshot = self.index_job.snapshot()
        try:
            response = await self.search_process.request("summaries", code=False)
        except DigUpUnavailable:
            return {**snapshot, "summary_available": False, "roots": []}
        rows = response.get("roots", [])
        roots = self._safe_summaries(rows, self.settings.roots)
        try:
            code_response = await self.search_process.request("summaries", code=True)
            code_roots = self._safe_summaries(code_response.get("roots", []), self.settings.code_roots)
        except (DigUpUnavailable, ValueError):
            code_roots = []
        return {**snapshot, "summary_available": True, "roots": roots, "code_roots": code_roots}

    @staticmethod
    def _safe_summaries(rows: list[dict[str, Any]], configured_roots: tuple[Path, ...]) -> list[dict[str, Any]]:
        summaries = []
        for index, row in enumerate(rows):
            configured = configured_roots[index] if index < len(configured_roots) else None
            summaries.append({
                "source": configured.name if configured else f"source-{index + 1}",
                "missing": row.get("missing", False),
                "unreadable": row.get("unreadable", False),
                "files": row.get("files", 0), "indexed": row.get("indexed", 0),
                "pending": row.get("pending", 0), "failed": row.get("failed", 0),
                "skipped": row.get("skipped", 0), "unfinished": row.get("unfinished", 0),
                "kinds": row.get("kinds", {}),
            })
        return summaries

    async def search(self, query: str, kinds: list[str] | None, mode: str, limit: int,
                     *, session_id: str, code: bool = False, prefix_last: bool = False) -> dict[str, Any]:
        response = await self.search_process.request(
            "search", q=query, kinds=kinds, limit=limit, meaning=(mode == "hybrid"),
            prefix_last=prefix_last, code=code
        )
        hits = []
        strong = 0
        self._expire_handles()
        for index, raw_hit in enumerate(response.get("hits", [])):
            safe = self._register_hit(raw_hit, session_id, code=code)
            if safe is not None:
                hits.append(safe)
                if index < response.get("strong", 0):
                    strong += 1
        return {"query": query, "mode": mode, "meaning": response.get("meaning", False),
                "strong": strong, "timings_ms": response.get("ms", {}),
                "warning": response.get("warning"), "total": len(hits), "hits": hits}

    def _register_hit(self, hit: dict[str, Any], session_id: str, *, code: bool = False,
                      root_hint: Path | None = None, archive: bool = False) -> dict[str, Any] | None:
        path_text = hit.get("path")
        if not isinstance(path_text, str) or (hit.get("kind") == "code") != code:
            return None
        try:
            actual = Path(path_text).resolve(strict=True)
            roots = self.settings.code_roots if code else self.settings.roots
            exclusions = self.settings.code_excluded_folders if code else self.settings.excluded_folders
            if root_hint is None:
                root = _permitted_root(actual, roots, exclusions)
            else:
                requested_root = root_hint.resolve(strict=True)
                if archive:
                    root = _permitted_root(actual, (requested_root,), exclusions)
                else:
                    configured_roots = tuple(folder.resolve(strict=True) for folder in roots)
                    root = _permitted_root(actual, (requested_root,), exclusions) \
                        if requested_root in configured_roots else None
            if root is None or not actual.is_file():
                return None
            if not code and not archive and actual.suffix.lower().lstrip(".") in self.settings.excluded_extensions:
                return None
            relative = actual.relative_to(root)
        except (OSError, ValueError):
            return None
        handle = secrets.token_urlsafe(24)
        info = hit.get("info") if isinstance(hit.get("info"), dict) else {}
        kind = str(hit.get("kind", "doc"))
        segment = str(hit.get("segment", "name"))
        loc = hit.get("loc")
        loc_end = hit.get("loc_end")
        reference = MediaReference(actual, root, hit, session_id,
                                   time.monotonic() + self.settings.handle_ttl_seconds, code, archive)
        self._media[handle] = reference
        if len(self._media) > 1000:
            self._expire_handles(force=True)
        display_kind = "document" if kind in ("doc", "pdf") else kind
        if kind == "screenshot":
            display_kind = "screenshot"
        location = _location(kind, segment, loc, loc_end)
        preview = f"/api/media/{handle}/preview"
        if kind == "video":
            preview = f"/api/media/{handle}/frame?at={loc if loc is not None else 0}"
        return {
            "id": handle,
            "name": actual.name,
            "folder": str(relative.parent) if str(relative.parent) != "." else root.name,
            "kind": display_kind,
            "engine_kind": kind,
            "segment": segment,
            "location": location,
            "loc": loc,
            "loc_end": loc_end,
            "score": hit.get("score"),
            "excerpt": hit.get("excerpt"),
            "metadata": info,
            "modified": hit.get("modified"),
            "size": hit.get("size"),
            "mime_type": mimetypes.guess_type(actual.name)[0] or "application/octet-stream",
            "preview_url": preview if kind in ("image", "screenshot", "pdf", "video") else None,
            "download_url": f"/api/media/{handle}/download",
            "reason": _reason(kind, segment, loc, loc_end, hit.get("z"), hit.get("keyword_rank")),
        }

    def _expire_handles(self, force: bool = False) -> None:
        now = time.monotonic()
        for handle, reference in list(self._media.items()):
            if reference.expires_at <= now or (force and len(self._media) > 900):
                self._media.pop(handle, None)

    def media(self, handle: str, *, session_id: str) -> MediaReference:
        reference = self._media.get(handle)
        if reference is None or reference.expires_at <= time.monotonic():
            self._media.pop(handle, None)
            raise MediaNotFound("Search result handle expired or was not found")
        if not secrets.compare_digest(reference.session_id, session_id):
            raise MediaNotFound("Search result handle expired or was not found")
        try:
            actual = reference.path.resolve(strict=True)
            roots = self.settings.code_roots if reference.code else self.settings.roots
            exclusions = self.settings.code_excluded_folders if reference.code else self.settings.excluded_folders
            configured_roots = []
            for folder in roots:
                try:
                    configured_roots.append(folder.resolve(strict=True))
                except OSError:
                    continue
            root = (_permitted_root(actual, (reference.root,), exclusions)
                    if reference.archive or reference.root in configured_roots else None)
        except OSError as exc:
            raise MediaNotFound("Media source is unavailable") from exc
        if (not actual.is_file() or root is None or
                (not reference.code and not reference.archive
                 and actual.suffix.lower().lstrip(".") in self.settings.excluded_extensions)):
            raise MediaForbidden("Media is outside configured archive roots")
        reference.path = actual
        reference.root = root
        return reference

    async def render(self, handle: str, *, at: float | None, pixels: int,
                     session_id: str, frame_only: bool = False) -> Path:
        media = self.media(handle, session_id=session_id)
        kind = str(media.hit.get("kind", ""))
        if frame_only and kind != "video":
            raise MediaNotFound("Frame rendering is available for video results only")
        render_kind = {"image": "image", "screenshot": "image", "pdf": "pdf", "video": "video"}.get(kind)
        if render_kind is None:
            raise MediaNotFound("This media kind has no image preview")
        loc = at
        if loc is None:
            loc = float(media.hit.get("loc") or 0)
        info = media.hit.get("info") if isinstance(media.hit.get("info"), dict) else {}
        if kind == "pdf":
            pages = int(info.get("pages", "0") or 0)
            if loc < 1 or pages and loc > pages:
                raise ValueError("PDF page is outside the indexed document")
        if kind == "video":
            duration = float(info.get("duration", "0") or 0)
            if loc < 0 or duration and loc > duration:
                raise ValueError("Video timestamp is outside the indexed clip")
        response = await self.search_process.request(
            "render", path=str(media.path), kind=render_kind, loc=loc, pixels=pixels
        )
        image = Path(str(response.get("image", ""))).resolve(strict=True)
        preview_root = (self.settings.index_dir / "previews").resolve(strict=True)
        if not image.is_file() or not _within(image, preview_root):
            raise DigUpUnavailable("DigUp returned an invalid preview location")
        return image

    async def close(self) -> None:
        await asyncio.gather(self.search_process.close(), self.index_job.close(), return_exceptions=True)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _permitted_root(path: Path, roots: tuple[Path, ...], exclusions: tuple[Path, ...]) -> Path | None:
    skipped = [folder.resolve() for folder in exclusions]
    for folder in roots:
        try:
            root = folder.resolve(strict=True)
        except OSError:
            continue
        if _within(path, root) and not any(
            skip != root and _within(skip, root) and _within(path, skip) for skip in skipped
        ):
            return root
    return None


def _safe_event_text(value: str, settings: EngineSettings) -> str:
    for path in (*settings.roots, settings.index_dir, settings.executable, settings.model_dir):
        value = value.replace(str(path), "[configured path]")
    # Helper errors are free-form strings; keep path-like diagnostics private.
    if "/" in value or "\\" in value:
        return "[details withheld]"
    return value[:300]


def _location(kind: str, segment: str, loc: Any, loc_end: Any) -> str | None:
    if loc is None:
        return None
    try:
        value = float(loc)
    except (TypeError, ValueError):
        return None
    if segment in ("page", "page_image"):
        return f"p. {int(value)}"
    if segment in ("lines", "cells"):
        try:
            end = int(float(loc_end)) if loc_end is not None else int(value)
        except (TypeError, ValueError):
            return None
        start = int(value)
        unit = "line" if segment == "lines" else "cell"
        return f"{unit} {start}" if start == end else f"{unit}s {start}–{end}"
    if kind in ("audio", "video"):
        seconds = max(0, int(value))
        return f"{seconds // 60}:{seconds % 60:02d}"
    return None


def _reason(kind: str, segment: str, loc: float | None, loc_end: float | None,
            z: float | None, keyword_rank: int | None) -> str:
    if not (z if z is not None else 0) >= 2:
        return "Has your words" if keyword_rank is not None else "Matches its name"
    if segment == "image":
        return "Matches what's on screen" if kind == "screenshot" else "Matches the picture"
    if segment == "ocr":
        return "Matches the text in it"
    if segment in ("frame", "audio"):
        place = _reason_clock(loc) if loc is not None else ""
        if segment == "frame":
            return f"Matches the frame at {place}"
        return f"Matches the sound at {place}" if kind == "video" else f"Matches what's heard at {place}"
    if segment in ("page", "page_image"):
        page = f"page {int(loc)}" if loc is not None else "a page"
        return f"Matches the text on {page}" if segment == "page" else f"Matches {page}"
    if segment == "chunk":
        return "Matches its text"
    if segment in ("lines", "cells"):
        if loc is None:
            return "Matches the code"
        start = int(loc)
        end = int(loc_end) if loc_end is not None else start
        unit = "line" if segment == "lines" else "cell"
        span = f"{unit} {start}" if start == end else f"{unit}s {start}–{end}"
        return f"Matches {span}"
    return "Matches its name"


def _reason_clock(seconds: float) -> str:
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600}:{total // 60 % 60:02d}:{total % 60:02d}"
    minutes = (abs(total) // 60) * (-1 if total < 0 else 1)
    return f"{minutes}:{total - minutes * 60:02d}"
