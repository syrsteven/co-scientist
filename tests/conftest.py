"""All release acceptance is offline, including copied core regressions."""

import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_real_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("release tests forbid all real sockets")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
