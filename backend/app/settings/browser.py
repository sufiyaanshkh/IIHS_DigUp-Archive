from __future__ import annotations

import os
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any


class DirectoryUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class BrowserRoot:
    path: Path
    label: str
    kind: str


class DirectoryBrowser:
    """Issues short-lived opaque references for explicitly browsable roots and their child folders."""

    def __init__(
        self,
        *,
        volumes_dir: Path = Path("/Volumes"),
        home: Path | None = None,
        test_volumes: tuple[tuple[Path, str], ...] = (),
    ) -> None:
        self.volumes_dir = volumes_dir
        self.home = (home or Path.home()).resolve()
        self.test_volumes = test_volumes
        self._lock = RLock()
        self._volume_refs: dict[str, tuple[BrowserRoot, float]] = {}
        self._directory_refs: dict[str, tuple[Path, Path, str, float]] = {}

    def volumes(self) -> list[dict[str, Any]]:
        rows: list[tuple[BrowserRoot, bool]] = []
        for path, label in self.test_volumes:
            rows.append((BrowserRoot(path, label, "test"), False))
        if sys.platform == "darwin" and self.volumes_dir.is_dir():
            try:
                children = sorted(self.volumes_dir.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                children = []
            for path in children:
                if path.is_symlink() or not path.is_dir() or not os.path.ismount(path):
                    continue
                rows.append((BrowserRoot(path, path.name, "mounted"), False))
        # These are explicit user folders, not a listing of the home directory or filesystem root.
        for name in ("Documents", "Desktop", "Downloads"):
            path = self.home / name
            if self._directory(path):
                rows.append((BrowserRoot(path, name, "local"), False))

        result = []
        with self._lock:
            self._expire()
            self._volume_refs.clear()
            seen: set[str] = set()
            for root, forced_available in rows:
                key = str(root.path)
                if key in seen:
                    continue
                seen.add(key)
                available = forced_available or self._directory(root.path)
                ref = uuid.uuid4().hex
                self._volume_refs[ref] = (root, time.monotonic() + 900)
                row: dict[str, Any] = {
                    "ref": ref,
                    "name": root.label,
                    "kind": root.kind,
                    "available": available,
                }
                if available:
                    try:
                        usage = shutil.disk_usage(root.path)
                        row.update({"capacity_bytes": usage.total, "free_bytes": usage.free})
                    except OSError:
                        row.update({"capacity_bytes": None, "free_bytes": None})
                else:
                    row.update({"capacity_bytes": None, "free_bytes": None})
                result.append(row)
        return result

    def issue_root_directory(self, path: Path, root: Path, label: str) -> str:
        safe_path, safe_root = self._safe(path, root)
        return self._issue_directory(safe_path, safe_root, label)

    def browse(
        self,
        *,
        volume_ref: str | None = None,
        directory_ref: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._expire()
            if volume_ref:
                item = self._volume_refs.get(volume_ref)
                if item is None:
                    raise DirectoryUnavailable("Storage location is unavailable; refresh the list")
                root, expires = item
                if expires <= time.monotonic():
                    raise DirectoryUnavailable("Storage location reference expired; refresh the list")
                base = root.path
                current = root.path
                label = root.label
            elif directory_ref:
                item = self._directory_refs.get(directory_ref)
                if item is None:
                    raise DirectoryUnavailable("Folder reference expired; reopen the folder browser")
                base, current, label, _ = item
            else:
                raise DirectoryUnavailable("Choose a storage location or folder")

            current, base = self._safe(current, base)
            current_ref = self._issue_directory(current, base, label)
            parent_ref = None
            if current != base:
                parent = current.parent
                parent_ref = self._issue_directory(parent, base, label)
            entries = []
            truncated = False
            try:
                with os.scandir(current) as items:
                    children = sorted(items, key=lambda item: item.name.casefold())
                for item in children:
                    if item.name.startswith(".") or item.is_symlink():
                        continue
                    try:
                        if not item.is_dir(follow_symlinks=False):
                            continue
                        path, _ = self._safe(Path(item.path), base)
                    except (OSError, DirectoryUnavailable):
                        continue
                    if len(entries) == 250:
                        truncated = True
                        break
                    entry_ref = self._issue_directory(path, base, label)
                    relative = path.relative_to(base)
                    entries.append({
                        "ref": entry_ref,
                        "name": path.name,
                        "relative_path": "." if str(relative) == "." else relative.as_posix(),
                    })
            except OSError as exc:
                raise DirectoryUnavailable("This folder cannot be listed") from exc

            relative = current.relative_to(base)
            return {
                "current": {
                    "ref": current_ref,
                    "name": current.name or label,
                    "relative_path": "." if str(relative) == "." else relative.as_posix(),
                },
                "parent_ref": parent_ref,
                "entries": entries,
                "truncated": truncated,
            }

    def resolve(self, ref: str) -> tuple[Path, Path, str]:
        with self._lock:
            self._expire()
            item = self._directory_refs.get(ref)
            if item is None:
                raise DirectoryUnavailable("Folder reference expired; reopen the folder browser")
            root, path, label, _ = item
            path, root = self._safe(path, root)
            return path, root, label

    def _issue_directory(self, path: Path, root: Path, label: str) -> str:
        with self._lock:
            ref = uuid.uuid4().hex
            self._directory_refs[ref] = (root, path, label, time.monotonic() + 900)
            if len(self._directory_refs) > 10_000:
                self._directory_refs = dict(list(self._directory_refs.items())[-8_000:])
            return ref

    def _expire(self) -> None:
        now = time.monotonic()
        self._volume_refs = {key: item for key, item in self._volume_refs.items() if item[1] > now}
        self._directory_refs = {
            key: item for key, item in self._directory_refs.items()
            if item[3] > now
        }

    @classmethod
    def _directory(cls, path: Path) -> bool:
        try:
            return not path.is_symlink() and path.is_dir()
        except OSError:
            return False

    @classmethod
    def _safe(cls, path: Path, root: Path) -> tuple[Path, Path]:
        try:
            if path.is_symlink() or root.is_symlink() or not path.is_dir() or not root.is_dir():
                raise DirectoryUnavailable("Storage location is disconnected or unavailable")
            canonical_root = root.resolve(strict=True)
            canonical_path = path.resolve(strict=True)
            canonical_path.relative_to(canonical_root)
            return canonical_path, canonical_root
        except (OSError, ValueError) as exc:
            if isinstance(exc, DirectoryUnavailable):
                raise
            raise DirectoryUnavailable("Folder is outside the approved storage location") from exc
