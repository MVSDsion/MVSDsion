"""MVSDsion additions on top of Fleasion: website sync, General rows and Skins."""

from __future__ import annotations

from .client import DEFAULT_WEBSITE_URL
from .service import MVSDsionService

__all__ = ['DEFAULT_WEBSITE_URL', 'MVSDsionService', 'get_service']

_service: MVSDsionService | None = None


def get_service() -> MVSDsionService:
    """Return the process-wide MVSDsion service (created on first use)."""
    global _service  # noqa: PLW0603
    if _service is None:
        _service = MVSDsionService()
    return _service
