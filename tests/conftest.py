"""Pytest fixtures for Hyprland IPC tests.

This module provides a set of small fixtures that replace Hyprland's UNIX
sockets with synthetic implementations.  Each fixture focuses on one
particular edge-case so that unit tests can validate the client logic without
relying on a live compositor instance.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Literal, Self

import pytest


# ---------------------------------------------------------------------------#
#                               Fake sockets                                 #
# ---------------------------------------------------------------------------#


class _BaseFakeSocket:
    """Tiny drop-in replacement for :class:`socket.socket` (subset only)."""

    def __init__(self, family: int, type_: int) -> None:
        self.family = family
        self.type_ = type_
        self.sent: list[bytes] = []
        self._recv_data: list[bytes] = []
        self.type_ = type_

    # -- minimal API ---------------------------------------------------------
    def connect(self, path: str | bytes | Path) -> None:
        """Pretend to connect to a UNIX socket."""
        ...

    def sendall(self, payload: bytes, /) -> None:
        """Record *payload* so that the test suite can later assert on it."""
        self.sent.append(payload)

    def recv(self, _bufsize: int, /) -> bytes:
        """Return a chunk of pre-queued data from *self._recv_data*."""
        return self._recv_data.pop(0)

    # -- context-manager support --------------------------------------------
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exec_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: object | None,
    ) -> Literal[False]:
        return False


class _SuccessSocket(_BaseFakeSocket):
    """Fake socket that returns an ordinary Hyprland response."""

    def __init__(self, family: int, type_: int) -> None:
        super().__init__(family, type_)
        self._recv_data = [b"resp", b""]


class _UnknownSocket(_BaseFakeSocket):
    """Fake socket that returns an *unknown request* error."""

    def __init__(self, family: int, type_: int) -> None:
        super().__init__(family, type_)
        self._recv_data = [b"unknown request", b""]


class _BadSocket(_BaseFakeSocket):
    """Fake socket that fails immediately upon *connect*."""

    def connect(self, path: str | bytes | Path) -> None:
        raise ConnectionRefusedError("BOOM!")  # Force the error path


_FAKE_SOCKET_MAP: Mapping[str, type[_BaseFakeSocket]] = {
    "success": _SuccessSocket,
    "unknown": _UnknownSocket,
    "bad": _BadSocket,
}

# --------------------------------------------------------------------------
# Fixtures - each yields *None* because they only perform monkey-patching.
# --------------------------------------------------------------------------


@pytest.fixture()
def fake_socket_success(monkeypatch: pytest.MonkeyPatch) -> FixtureGen:
    """Replace :pyfunc:`socket.socket` with :class:`_SuccessSocket`."""
    monkeypatch.setattr(socket, "socket", _SuccessSocket)
    yield
    monkeypatch.setattr(socket, "socket", socket.socket, raising=False)


@pytest.fixture()
def fake_socket_unknown(monkeypatch: pytest.MonkeyPatch) -> FixtureGen:
    """Replace :pyfunc:`socket.socket` with :class:`_UnknownSocket`."""
    monkeypatch.setattr(socket, "socket", _UnknownSocket)
    yield
    monkeypatch.setattr(socket, "socket", socket.socket, raising=False)


@pytest.fixture()
def bad_socket(monkeypatch: pytest.MonkeyPatch) -> FixtureGen:
    """Replace :pyfunc:`socket.socket` with :class:`_BadSocket`."""
    monkeypatch.setattr(socket, "socket", _BadSocket)
    yield
    monkeypatch.setattr(socket, "socket", socket.socket, raising=False)


# --------------------------------------------------------------------------
# Live socket servers (UNIX domain) for integration-style fixtures.
# --------------------------------------------------------------------------

_SOCKET_BACKLOG = 1


@pytest.fixture()
def cmd_server(tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Start a dummy command socket at *tmp_path / 'a'*.

    Tests can rely on the existence of the path without having to set it up
    themselves. The fixture changes the working directory so that relative
    paths inside the code under test resolve correctly.
    """
    monkeypatch.chdir(tmp_path)

    sock_path = tmp_path / "a"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(_SOCKET_BACKLOG)

    yield

    server.close()
    sock_path.unlink(missing_ok=True)


@pytest.fixture()
def evt_server(tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Start a dummy event socket at *tmp_path / 'b'* that emits two events."""
    monkeypatch.chdir(tmp_path)

    sock_path = tmp_path / "b"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(_SOCKET_BACKLOG)

    def _serve() -> None:
        conn, _ = server.accept()
        try:
            # Hyprland separates events by *\n* and uses *>>* as the delimiter
            # between event name and payload. See: https://wiki.hyprland.org/IPC/
            conn.sendall(b"evt1>>data1\n")
            conn.sendall(b"evt2>>data2\n")
        finally:
            conn.close()
            server.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    yield

    thread.join()
    sock_path.unlink(missing_ok=True)
