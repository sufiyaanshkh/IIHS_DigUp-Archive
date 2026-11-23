from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    tenant_id: str | None
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    session_max_age: int
    cookie_secure: bool
    public_origin: str | None
    demo_registration_allowed: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        raw_age = os.getenv("IIHS_SESSION_MAX_AGE_SECONDS", "43200")
        try:
            age = int(raw_age)
        except ValueError as exc:
            raise ValueError("IIHS_SESSION_MAX_AGE_SECONDS must be an integer") from exc
        if not 1 <= age <= 43200:
            raise ValueError("IIHS_SESSION_MAX_AGE_SECONDS must be between 1 and 43200")
        return cls(
            tenant_id=os.getenv("IIHS_ENTRA_TENANT_ID"),
            client_id=os.getenv("IIHS_ENTRA_CLIENT_ID"),
            client_secret=os.getenv("IIHS_ENTRA_CLIENT_SECRET"),
            redirect_uri=os.getenv("IIHS_ENTRA_REDIRECT_URI"),
            session_max_age=age,
            cookie_secure=True,
            public_origin=os.getenv("IIHS_PUBLIC_ORIGIN"),
            demo_registration_allowed=os.getenv("IIHS_DEMO_REGISTRATION_ALLOWED") == "1",
        )

    @property
    def entra_ready(self) -> bool:
        return all((self.tenant_id, self.client_id, self.client_secret, self.redirect_uri))
