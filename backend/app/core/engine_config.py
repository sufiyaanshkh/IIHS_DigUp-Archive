from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENGINE_ROOT = PROJECT_ROOT / "backend" / "engine" / "DigUp"
TEXT_MODEL = "embeddinggemma-2-Q8_0.gguf"
MEDIA_PROJECTOR = "mmproj-embeddinggemma-2-Q8_0.gguf"


def _project_path(value: str | None, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


@dataclass(frozen=True)
class EngineSettings:
    executable: Path
    index_dir: Path
    model_dir: Path
    roots: tuple[Path, ...]
    excluded_folders: tuple[Path, ...] = ()
    excluded_extensions: tuple[str, ...] = ()
    code_roots: tuple[Path, ...] = ()
    code_excluded_folders: tuple[Path, ...] = ()
    search_idle_seconds: int = 300
    request_timeout_seconds: int = 30
    handle_ttl_seconds: int = 1800

    @classmethod
    def from_env(cls) -> "EngineSettings":
        dev_root = PROJECT_ROOT / "var" / "digup-stage3a"
        raw_roots = os.getenv("IIHS_DIGUP_ROOTS")
        roots = tuple(
            _project_path(item.strip(), dev_root / "media")
            for item in raw_roots.split(os.pathsep) if item.strip()
        ) if raw_roots is not None else (dev_root / "media",)
        try:
            idle = int(os.getenv("IIHS_DIGUP_SEARCH_IDLE_SECONDS", "300"))
            timeout = int(os.getenv("IIHS_DIGUP_REQUEST_TIMEOUT_SECONDS", "30"))
            ttl = int(os.getenv("IIHS_DIGUP_HANDLE_TTL_SECONDS", "1800"))
        except ValueError as exc:
            raise ValueError("DigUp timeout settings must be integers") from exc
        if not 1 <= idle <= 3600 or not 1 <= timeout <= 600 or not 60 <= ttl <= 86400:
            raise ValueError("DigUp timeout settings are outside their supported ranges")

        index_dir = _project_path(os.getenv("IIHS_DIGUP_INDEX_DIR"), dev_root / "index")
        # Never let an omitted or accidental config send this adapter to DigUp's desktop index.
        if index_dir.as_posix().endswith("/Library/Application Support/DigUp/index.noindex"):
            raise ValueError("IIHS_DIGUP_INDEX_DIR must not point to DigUp Application Support")

        return cls(
            executable=_project_path(
                os.getenv("IIHS_DIGUP_CLI"), ENGINE_ROOT / ".build" / "release" / "digup"
            ),
            index_dir=index_dir,
            model_dir=_project_path(
                os.getenv("IIHS_DIGUP_MODELS"), ENGINE_ROOT / "Vendor" / "models"
            ),
            roots=roots,
            search_idle_seconds=idle,
            request_timeout_seconds=timeout,
            handle_ttl_seconds=ttl,
        )

    @property
    def executable_available(self) -> bool:
        return self.executable.is_file() and os.access(self.executable, os.X_OK)

    @property
    def models_available(self) -> bool:
        return all((self.model_dir / name).is_file() for name in (TEXT_MODEL, MEDIA_PROJECTOR))

    def process_environment(self) -> dict[str, str]:
        """Pass runtime essentials and model location only; do not forward Entra secrets to DigUp."""
        keys = (
            "PATH", "HOME", "TMPDIR", "TEMP", "LANG", "LC_ALL", "LC_CTYPE",
            "DIGUP_DEVICE", "DIGUP_BACKENDS", "DIGUP_THREADS", "LD_LIBRARY_PATH",
            "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH",
        )
        environment = {key: os.environ[key] for key in keys if key in os.environ}
        environment["DIGUP_MODELS"] = str(self.model_dir)
        return environment
