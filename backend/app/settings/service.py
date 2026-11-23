from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.engine_config import EngineSettings, PROJECT_ROOT
from app.settings.browser import DirectoryBrowser, DirectoryUnavailable


class SettingsError(RuntimeError):
    pass


class PathEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=16, max_length=64)
    path: str
    volume_path: str
    volume_label: str
    name: str
    relative_path: str


class SettingsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    roots: list[PathEntry] = Field(default_factory=list)
    excluded_folders: list[PathEntry] = Field(default_factory=list)
    excluded_extensions: list[str] = Field(default_factory=list)
    code_roots: list[PathEntry] = Field(default_factory=list)
    code_excluded_folders: list[PathEntry] = Field(default_factory=list)


class SettingsService:
    def __init__(
        self,
        base_engine: EngineSettings,
        *,
        path: Path | None = None,
        browser: DirectoryBrowser | None = None,
    ) -> None:
        configured = os.getenv("IIHS_SETTINGS_PATH")
        default_path = PROJECT_ROOT / "var" / "settings.json"
        self.path = (path or (Path(configured).expanduser() if configured else default_path)).resolve()
        self.base_engine = base_engine
        self.browser = browser or DirectoryBrowser()
        self._lock = RLock()
        self._document = self._read_or_seed()

    def _read_or_seed(self) -> SettingsDocument:
        if self.path.exists():
            try:
                return SettingsDocument.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                raise SettingsError("The settings file is invalid; it was left unchanged") from exc
        roots = [self._seed_path(path) for path in self.base_engine.roots]
        excluded = [self._seed_path(path) for path in self.base_engine.excluded_folders]
        code_roots = [self._seed_path(path) for path in self.base_engine.code_roots]
        code_excluded = [self._seed_path(path) for path in self.base_engine.code_excluded_folders]
        return SettingsDocument(
            roots=roots,
            excluded_folders=excluded,
            excluded_extensions=sorted(set(self.base_engine.excluded_extensions)),
            code_roots=code_roots,
            code_excluded_folders=code_excluded,
        )

    @staticmethod
    def _seed_path(path: Path) -> PathEntry:
        resolved = path.expanduser().resolve()
        return PathEntry(
            id=uuid.uuid4().hex,
            path=str(resolved),
            volume_path=str(resolved),
            volume_label=resolved.name or "Configured location",
            name=resolved.name or "Configured location",
            relative_path=".",
        )

    def _commit(self, candidate: SettingsDocument) -> None:
        serialized = candidate.model_dump_json(indent=2) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                if hasattr(os, "fchmod"):
                    os.fchmod(handle.fileno(), 0o600)
                elif os.name != "nt":
                    raise SettingsError("Secure settings file permissions are unavailable")
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
        self._document = candidate

    def engine_settings(self) -> EngineSettings:
        with self._lock:
            document = self._document
            return replace(
                self.base_engine,
                roots=tuple(Path(item.path) for item in document.roots),
                excluded_folders=tuple(Path(item.path) for item in document.excluded_folders),
                excluded_extensions=tuple(document.excluded_extensions),
                code_roots=tuple(Path(item.path) for item in document.code_roots),
                code_excluded_folders=tuple(Path(item.path) for item in document.code_excluded_folders),
            )

    def all(self) -> dict[str, Any]:
        return {
            "general": self.general(),
            "folders": self.folders(),
            "code": self.code(),
        }

    def general(self) -> dict[str, Any]:
        with self._lock:
            return {
                "indexing_behavior": "manual",
                "automatic_indexing_available": False,
                "desktop_only": [
                    {"name": "Search shortcut", "desktop_default": "Command + Shift + Space"},
                    {"name": "Open at login", "desktop_default": "Managed by the desktop app"},
                    {"name": "Automatic update checks", "desktop_default": "Managed by the desktop app"},
                    {"name": "Check Now", "desktop_default": "Desktop-only update action"},
                    {"name": "Indexing hours", "desktop_default": "Off (01:00–07:00 retained)"},
                    {"name": "Index on battery power", "desktop_default": "On"},
                ],
            }

    def folders(self) -> dict[str, Any]:
        with self._lock:
            return {
                "roots": [self._public_entry(item) for item in self._document.roots],
                "excluded_folders": [self._public_entry(item) for item in self._document.excluded_folders],
                "excluded_extensions": list(self._document.excluded_extensions),
            }

    def code(self, *, index_status: dict[str, Any] | None = None,
             indexing_available: bool = False) -> dict[str, Any]:
        with self._lock:
            return {
                "roots": [self._public_entry(item) for item in self._document.code_roots],
                "excluded_folders": [self._public_entry(item) for item in self._document.code_excluded_folders],
                "indexing_available": indexing_available,
                "search_available": bool(self._document.code_roots),
                "search_note": "Archive operators can search configured code roots in the browser. Indexing must be started separately.",
                "editor": {"available": False, "note": "Opening results in a desktop code editor is desktop-only."},
                "index": index_status or {"files": 0, "vectors": 0, "state": "idle", "roots": []},
            }

    def volumes(self) -> list[dict[str, Any]]:
        return self.browser.volumes()

    def browse(
        self,
        *,
        volume_ref: str | None = None,
        directory_ref: str | None = None,
        root_id: str | None = None,
        section: Literal["folders", "code"] = "folders",
    ) -> dict[str, Any]:
        if root_id:
            with self._lock:
                entries = self._document.roots if section == "folders" else self._document.code_roots
                entry = next((item for item in entries if item.id == root_id), None)
            if entry is None:
                raise DirectoryUnavailable("Configured folder was not found")
            path = Path(entry.path)
            root = Path(entry.volume_path)
            ref = self.browser.issue_root_directory(path, root, entry.volume_label)
            return self.browser.browse(directory_ref=ref)
        return self.browser.browse(volume_ref=volume_ref, directory_ref=directory_ref)

    def add_root(self, directory_ref: str, *, section: Literal["folders", "code"]) -> dict[str, Any]:
        path, volume, label = self.browser.resolve(directory_ref)
        entry = self._entry(path, volume, label)
        with self._lock:
            candidate = self._document.model_copy(deep=True)
            field = "roots" if section == "folders" else "code_roots"
            rows = getattr(candidate, field)
            if not any(Path(item.path) == path for item in rows):
                rows.append(entry)
            if section == "folders":
                self._assert_exclusions(candidate.roots, candidate.excluded_folders)
            else:
                self._assert_exclusions(candidate.code_roots, candidate.code_excluded_folders)
            self._commit(candidate)
        return self.folders() if section == "folders" else self.code()

    def add_native_roots(self, selected: list[str]) -> dict[str, Any]:
        with self._lock:
            paths = [self._native_root(value) for value in selected]
            candidate = self._document.model_copy(deep=True)
            existing = {os.path.normcase(item.path) for item in candidate.roots}
            identities: set[tuple[int, int]] = set()
            for item in candidate.roots:
                try:
                    info = Path(item.path).stat()
                    if info.st_ino:
                        identities.add((info.st_dev, info.st_ino))
                except OSError:
                    continue
            changed = False
            for path in paths:
                try:
                    info = path.stat()
                except OSError as exc:
                    raise DirectoryUnavailable("The selected folder is unavailable or cannot be accessed") from exc
                identity = (info.st_dev, info.st_ino)
                key = os.path.normcase(str(path))
                if key in existing or (info.st_ino and identity in identities):
                    continue
                label = path.parent.name or path.anchor or "Selected location"
                candidate.roots.append(self._entry(path, path, label))
                existing.add(key)
                if info.st_ino:
                    identities.add(identity)
                changed = True
            if changed:
                self._assert_exclusions(candidate.roots, candidate.excluded_folders)
                self._commit(candidate)
        return self.folders()

    @staticmethod
    def _native_root(value: str) -> Path:
        try:
            if os.name == "nt" and not hasattr(Path, "is_junction"):
                raise DirectoryUnavailable("Windows folder selection requires Python with junction detection")
            path = Path(value)
            if not path.is_absolute() or ".." in path.parts or "\x00" in value:
                raise DirectoryUnavailable("The selected folder path is invalid")
            for part in (path, *path.parents):
                if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
                    raise DirectoryUnavailable("Folders reached through links or junctions cannot be added")
            path = path.resolve(strict=True)
            if not path.is_dir():
                raise DirectoryUnavailable("The selected folder is unavailable")
            with os.scandir(path):
                pass
            return path
        except DirectoryUnavailable:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise DirectoryUnavailable("The selected folder is unavailable or cannot be accessed") from exc

    def remove_root(self, root_id: str, *, section: Literal["folders", "code"]) -> dict[str, Any]:
        with self._lock:
            candidate = self._document.model_copy(deep=True)
            roots_field, excludes_field = ("roots", "excluded_folders") if section == "folders" else (
                "code_roots", "code_excluded_folders"
            )
            roots = getattr(candidate, roots_field)
            selected = next((item for item in roots if item.id == root_id), None)
            if selected is None:
                raise KeyError("Configured folder was not found")
            setattr(candidate, roots_field, [item for item in roots if item.id != root_id])
            remaining_roots = getattr(candidate, roots_field)
            setattr(candidate, excludes_field, [item for item in getattr(candidate, excludes_field)
                if any(Path(item.path) != Path(root.path) and
                       self._inside(Path(item.path), Path(root.path)) for root in remaining_roots)])
            self._commit(candidate)
        return self.folders() if section == "folders" else self.code()

    def add_exclusion(self, directory_ref: str, *, section: Literal["folders", "code"]) -> dict[str, Any]:
        path, volume, label = self.browser.resolve(directory_ref)
        with self._lock:
            candidate = self._document.model_copy(deep=True)
            roots_field, excludes_field = ("roots", "excluded_folders") if section == "folders" else (
                "code_roots", "code_excluded_folders"
            )
            roots = getattr(candidate, roots_field)
            if not any(Path(root.path) != path and self._inside(path, Path(root.path)) for root in roots):
                raise ValueError("Excluded folders must be inside a configured root and cannot equal the root")
            rows = getattr(candidate, excludes_field)
            if not any(Path(item.path) == path for item in rows):
                rows.append(self._entry(path, volume, label))
            self._assert_exclusions(roots, rows)
            self._commit(candidate)
        return self.folders() if section == "folders" else self.code()

    def remove_exclusion(self, exclusion_id: str, *, section: Literal["folders", "code"]) -> dict[str, Any]:
        with self._lock:
            candidate = self._document.model_copy(deep=True)
            field = "excluded_folders" if section == "folders" else "code_excluded_folders"
            rows = getattr(candidate, field)
            if not any(item.id == exclusion_id for item in rows):
                raise KeyError("Excluded folder was not found")
            setattr(candidate, field, [item for item in rows if item.id != exclusion_id])
            self._commit(candidate)
        return self.folders() if section == "folders" else self.code()

    def set_extensions(self, extensions: list[str]) -> dict[str, Any]:
        with self._lock:
            candidate = self._document.model_copy(deep=True)
            candidate.excluded_extensions = extensions
            self._commit(candidate)
        return self.folders()

    def _entry(self, path: Path, volume: Path, label: str) -> PathEntry:
        relative = path.relative_to(volume)
        return PathEntry(
            id=uuid.uuid4().hex,
            path=str(path),
            volume_path=str(volume),
            volume_label=label,
            name=path.name or label,
            relative_path="." if str(relative) == "." else relative.as_posix(),
        )

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _assert_exclusions(cls, roots: list[PathEntry], exclusions: list[PathEntry]) -> None:
        for item in exclusions:
            if not any(Path(item.path) != Path(root.path) and cls._inside(Path(item.path), Path(root.path))
                       for root in roots):
                raise ValueError("Excluded folders must remain inside configured roots")

    @staticmethod
    def _public_entry(item: PathEntry) -> dict[str, Any]:
        path = Path(item.path)
        volume = Path(item.volume_path)
        try:
            relative = path.relative_to(volume)
            relative_path = "." if str(relative) == "." else relative.as_posix()
        except ValueError:
            relative_path = item.relative_path
        available = DirectoryBrowser._directory(path) and DirectoryBrowser._directory(volume)
        return {
            "id": item.id,
            "name": item.name,
            "location": item.volume_label,
            "relative_path": relative_path,
            "available": available,
        }
