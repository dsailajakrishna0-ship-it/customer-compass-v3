"""Which MCP tool server to talk to.

Two servers implement the same four tools (contracts/mcp-tools.json): "fastmcp" (Python, this
repository's app/mcp/server.py) and "springboot" (Java, services/mcp-java). The default comes from
`MCP_BACKEND`; a chat request may name another. A backend with no URL is "not configured" and cannot
be chosen.
"""

from dataclasses import dataclass

from app.config import get_settings

LABELS = {"fastmcp": "FastMCP (Python)", "springboot": "Spring Boot (Java)"}


class UnknownBackendError(ValueError):
    """The requested backend does not exist or is not configured."""


@dataclass(frozen=True)
class Backend:
    id: str
    label: str
    url: str | None

    @property
    def configured(self) -> bool:
        return bool(self.url)


def backends() -> dict[str, Backend]:
    settings = get_settings()
    urls = {"fastmcp": settings.mcp_fastmcp_url, "springboot": settings.mcp_springboot_url}
    return {id_: Backend(id_, label, urls[id_] or None) for id_, label in LABELS.items()}


def resolve(requested: str | None = None) -> Backend:
    """The backend to use: the requested one, else the default. Raises UnknownBackendError."""
    known = backends()
    chosen = requested or get_settings().mcp_backend
    backend = known.get(chosen)
    if backend is None:
        raise UnknownBackendError(
            f'Unknown MCP server "{chosen}". Choose one of: {", ".join(known)}.'
        )
    if not backend.configured:
        raise UnknownBackendError(
            f"The {backend.label} server is not configured. Set MCP_{chosen.upper()}_URL "
            "(see .env.example) or choose another server."
        )
    return backend
