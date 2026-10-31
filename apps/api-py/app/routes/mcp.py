"""Which MCP tool servers exist, which are configured, and which answer (for the web app's radio buttons)."""

import asyncio

from fastapi import APIRouter

from app.config import get_settings
from app.mcp.client import mcp_session
from app.mcp.registry import Backend, backends

router = APIRouter(prefix="/mcp", tags=["mcp"])

PROBE_SECONDS = 2.0


async def _reachable(backend: Backend) -> bool:
    if not backend.configured:
        return False
    try:
        async with asyncio.timeout(PROBE_SECONDS):
            async with mcp_session(backend.id):
                return True
    except Exception:  # noqa: BLE001 - any failure to connect means "not reachable"
        return False


@router.get("/servers")
async def servers():
    known = list(backends().values())
    reachable = await asyncio.gather(*(_reachable(b) for b in known))
    return {
        "default": get_settings().mcp_backend,
        "servers": [
            {"id": b.id, "label": b.label, "configured": b.configured, "reachable": ok}
            for b, ok in zip(known, reachable, strict=True)
        ],
    }
