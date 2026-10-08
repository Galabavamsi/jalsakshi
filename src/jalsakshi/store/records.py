"""Storage-level records that are not domain types (call sessions, the activity feed).

Domain types live in `jalsakshi.core.models`; these exist only because the store keeps them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CallSession(BaseModel):
    """IVR call session: caller-owned data, recorded steps and the Step Functions task token."""

    call_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    steps: dict[str, Any] = Field(default_factory=dict)
    last_step: str | None = None
    task_token: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    expires_at: datetime | None = None


class ActivityEntry(BaseModel):
    """One line of the console's live activity feed (docs/ARCHITECTURE.md section 13)."""

    at: datetime
    kind: str
    village_id: str | None = None
    text_en: str
    text_hi: str
