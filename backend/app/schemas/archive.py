from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


DigUpKind = Literal["screenshot", "image", "pdf", "doc", "audio", "video"]
SearchHitKind = Literal["screenshot", "image", "pdf", "doc", "audio", "video", "code"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["keyword", "hybrid"] = "hybrid"
    scope: Literal["archive", "code"] = "archive"
    kinds: list[DigUpKind] | None = None
    limit: int = Field(default=20, ge=1, le=100)
    prefix_last: StrictBool = Field(default=False, description="Match the last query word as a prefix.")

    @field_validator("query")
    @classmethod
    def query_must_contain_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Search query cannot be blank")
        return value


class SearchHit(BaseModel):
    id: str
    name: str
    folder: str
    kind: str
    engine_kind: SearchHitKind
    segment: str
    location: str | None
    loc: float | None
    loc_end: float | None
    score: float
    excerpt: str | None
    metadata: dict[str, str]
    modified: float
    size: int
    mime_type: str
    preview_url: str | None
    download_url: str
    reason: str


class SearchResponse(BaseModel):
    query: str
    mode: Literal["keyword", "hybrid"]
    meaning: bool
    strong: int = Field(description="Number of returned hits in DigUp's original strong-match prefix.")
    timings_ms: dict[str, int]
    warning: str | None = None
    total: int
    hits: list[SearchHit]


class ArchiveSource(BaseModel):
    id: str
    name: str
    location: str
    relative_path: str
    available: bool


class ArchiveFolder(BaseModel):
    name: str
    relative_path: str
    file_count: int | None = None


class ArchiveItem(SearchHit):
    relative_path: str
    source_id: str
    source_name: str
    processing_state: Literal["done", "partial", "pending", "failed", "skipped", "unindexed", "unknown"]


class ArchiveListing(BaseModel):
    sources: list[ArchiveSource]
    source_id: str | None
    folder: str | None
    breadcrumbs: list[ArchiveFolder]
    folders: list[ArchiveFolder]
    items: list[ArchiveItem]
    total: int
    limit: int
    offset: int
    schema_version: int | None


class BackfillRequest(BaseModel):
    enabled: StrictBool


class IndexingStatus(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: str
    job_id: str | None
    sync_available: bool
    sync_unavailable_reason: str


class EnginePrewarmResponse(BaseModel):
    encoder: Literal["stopped", "starting", "ready", "unavailable"]
    vectors: int


class EngineReloadResponse(BaseModel):
    vectors: int
    code_vectors: int


class PhotographyMetadata(BaseModel):
    camera: str | None
    lens: str | None
    aperture: str | None
    iso: str | None
    shutter_speed: str | None
    white_balance: str | None
    exposure_compensation: str | None
    location: str | None
    capture_time: str | None
    dimensions: str | None


class CurrentChecksum(BaseModel):
    sha256: str
