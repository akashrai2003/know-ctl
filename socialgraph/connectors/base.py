from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class RawPost:
    urn: str
    platform: str
    content: str
    author: str | None = None
    subtitle: str | None = None
    date_raw: str | None = None
    source_url: str | None = None


@runtime_checkable
class BaseConnector(Protocol):
    platform: str

    async def fetch_saved_posts(self) -> list[RawPost]: ...
