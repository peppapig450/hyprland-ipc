# SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>
#
# SPDX-License-Identifier: MIT

"""Pytest fixtures for Hyprland IPC tests.

This module provides a set of small fixtures that replace Hyprland's UNIX
sockets with synthetic implementations.  Each fixture focuses on one
particular edge-case so that unit tests can validate the client logic without
relying on a live compositor instance.
"""

from __future__ import annotations

import socket
import tempfile
import threading
import uuid
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

# ---------------------------------------------------------------------------#
#                                Fixtures                                    #
# ---------------------------------------------------------------------------#


def _patch_socket[T: _BaseFakeSocket](monkeypatch: pytest.MonkeyPatch, fake_cls: type[T]) -> None:
    """Globally replace ``socket.socket`` with *fake_cls* inside code-under-test."""
    monkeypatch.setattr(socket, "socket", fake_cls, raising=True)


@pytest.fixture(params=("success", "unknown", "bad"))
def fake_socket(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[str, None, None]:
    """Parametrised socket patcher.

    Yields the **name** of the fake that is active for this test.
    """
    _patch_socket(monkeypatch, _FAKE_SOCKET_MAP[request.param])
    yield request.param
    monkeypatch.undo()


# Sometimes explicit fixtures read better in tests --------------------------
@pytest.fixture()
def fake_socket_success(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _patch_socket(monkeypatch, _SuccessSocket)
    yield
    monkeypatch.undo()


@pytest.fixture()
def fake_socket_unknown(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _patch_socket(monkeypatch, _UnknownSocket)
    yield
    monkeypatch.undo()


@pytest.fixture()
def bad_socket(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    _patch_socket(monkeypatch, _BadSocket)
    yield
    monkeypatch.undo()


# --------------------------------------------------------------------------
# Live socket servers (UNIX domain) for integration-style fixtures.
# --------------------------------------------------------------------------

_SOCKET_BACKLOG = 1


def _make_short_socket(name: str) -> Path:
    """Return a guaranteed-short pathname inside the system temp dir."""
    return Path(tempfile.gettempdir()) / f"hypripc_{uuid.uuid4().hex[:8]}_{name}.sock"


@pytest.fixture()
def cmd_server(tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Start a dummy command socket at *tmp_path / 'a'*.

    Tests can rely on the existence of the path without having to set it up
    themselves. The fixture changes the working directory so that relative
    paths inside the code under test resolve correctly.
    """
    monkeypatch.chdir(tmp_path)

    sock_path = _make_short_socket("cmd")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(_SOCKET_BACKLOG)

    yield sock_path

    server.close()
    sock_path.unlink(missing_ok=True)


@pytest.fixture()
def evt_server(tmp_path: Path, *, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Start a dummy event socket at *tmp_path / 'b'* that emits two events."""
    monkeypatch.chdir(tmp_path)

    sock_path = _make_short_socket("evt")
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

    yield sock_path

    thread.join()
    sock_path.unlink(missing_ok=True)
