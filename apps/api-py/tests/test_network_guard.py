"""The network guard in conftest.py: tests may reach this machine, nothing else."""

import socket

import pytest


def test_an_outside_host_is_refused_before_any_connection_is_attempted():
    with pytest.raises(RuntimeError, match="may only use localhost"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_an_outside_ip_address_is_refused_too():
    with pytest.raises(RuntimeError, match="may only use localhost"):
        socket.socket().connect(("93.184.216.34", 80))


def test_this_machine_is_allowed():
    """A closed local port is refused by the operating system, not by the guard."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.close()
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


@pytest.mark.network
def test_a_test_marked_network_is_not_guarded():
    """Only checks the guard is off: resolving a name needs no connection to be attempted."""
    assert socket.getaddrinfo("localhost", 80)
