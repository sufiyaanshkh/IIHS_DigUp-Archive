from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


DigUpKind = Literal["screenshot", "image", "pdf", "doc", "audio", "video"]
SearchHitKind = Literal["screenshot", "image", "pdf", "doc", "audio", "video", "code"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["keyword", "hybrid"] = "hybrid"
    scope: Literal["archive", "code"] = "archive"
    kinds: list[DigUpKind] | None = None
    limit: int = Field(default=20, ge=1, le=100)

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
    strong: int
    timings_ms: dict[str, int]
    warning: str | None = None
    total: int
    hits: list[SearchHit]


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
