"""Shared pytest fixtures.

Each async test gets its own event loop (pytest-asyncio's default, function-
scoped). app.db and app.rag.qdrant_store keep process-wide singleton
connections (a Postgres pool and a Qdrant client) for reuse across requests
within one running server — but that pattern breaks across tests, since a
connection/client created on one test's event loop can't be reused once that
loop is closed. This fixture resets both singletons after every test so each
one starts clean on its own loop.
"""

import socket

import pytest
import pytest_asyncio

from app.config import reset_settings
from app.db import close_pool
from app.rag.qdrant_store import close_client

# Addresses a test may talk to: this machine (the Postgres and Qdrant containers publish their ports here)
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


@pytest.fixture(autouse=True)
def _no_outside_network(request, monkeypatch):
    """Tests may reach this machine only. A test that really needs the internet must say so with
    `@pytest.mark.network`; everything else fails loudly instead of silently depending on a service."""
    if request.node.get_closest_marker("network"):
        return
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def refuse(host):
        raise RuntimeError(
            f"this test tried to reach {host!r}. Tests may only use localhost; mark a test that "
            "really needs the internet with @pytest.mark.network."
        )

    def guarded_connect(self, address):
        if isinstance(address, tuple) and str(address[0]) not in LOCAL_HOSTS:
            refuse(address[0])
        return real_connect(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host is not None and str(host) not in LOCAL_HOSTS:
            refuse(host)
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Settings are cached; every test starts and ends with a re-read of the environment."""
    reset_settings()
    yield
    reset_settings()


@pytest_asyncio.fixture(autouse=True)
async def _reset_singletons():
    yield
    await close_pool()
    await close_client()
