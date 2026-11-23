from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectorySelection(StrictModel):
    directory_ref: str = Field(min_length=16, max_length=64)


class ExtensionUpdate(StrictModel):
    extensions: list[str] = Field(max_length=100)

    @field_validator("extensions")
    @classmethod
    def normalize_extensions(cls, values: list[str]) -> list[str]:
        normalized: set[str] = set()
        for value in values:
            extension = value.strip().lower()
            if extension.startswith("*."):
                extension = extension[2:]
            elif extension.startswith("."):
                extension = extension[1:]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", extension):
                raise ValueError("Use a file extension such as .tmp or .cache")
            normalized.add(extension)
        return sorted(normalized)
