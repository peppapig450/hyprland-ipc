"""Pytest fixtures for Hyprland IPC tests.

This module provides a set of small fixtures that replace Hyprland's UNIX
sockets with synthetic implementations.  Each fixture focuses on one
particular edge-case so that unit tests can validate the client logic without
relying on a live compositor instance.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Generator
from os import PathLike
from pathlib import Path
from typing import Literal, Self

import pytest


type PathType = str | bytes | Path | PathLike[str] | PathLike[bytes]
"""Type alias representing any possible Path."""

type FixtureGen = Generator[None, None, None]
"""Type alias for annotating fixture's empty generators."""


class _BaseFakeSocket:
    """Minimal socket implementation shared by all fake sockets."""

    family: int
    type_: int

    def __init__(self, family: int, type_: int) -> None:
        self.family = family
        self.type_ = type_
        self.sent: list[bytes] = []
        self._recv_data: list[bytes] = []

    # ---------------------------------------------------------------------
    # Socket API subset
    # ---------------------------------------------------------------------
    def connect(self, path: PathType) -> None:
        """Pretend to connect to a UNIX socket."""
        ...

    def sendall(self, payload: bytes, /) -> None:
        """Record *payload* so that the test suite can later assert on it."""

    def recv(self, bufsize: int, /) -> bytes:
        """Return a chunk of pre-queued data from *self._recv_data*."""
        return self._recv_data.pop(0)

    # ------------------------------------------------------------------
    # Context-manager protocol so ``with socket.socket() as s: ...`` keeps
    # working.
    # ------------------------------------------------------------------
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exec_type: type[BaseException] | None, exc: BaseException | None, tb: object | None
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

    def connect(self, path: PathType) -> None:
        return super().connect(path)

    def recv(self, bufsize: int) -> bytes:
        return b""

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

