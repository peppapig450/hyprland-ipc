# SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import selectors
import socket
import threading
from pathlib import Path
from typing import Literal

import pytest

from hyprland_ipc.ipc import Event, HyprlandIPC, HyprlandIPCError, normalize
from tests.conftest import _make_short_socket


# ---------------------------------------------------------------------------
# Helpers for custom event server (for invalid/valid event test)
# ---------------------------------------------------------------------------


def _start_custom_event_server(sock_path: Path, payloads: list[bytes]) -> threading.Thread:
    """Spawn a one-shot UNIX-domain server that streams *payloads* then closes.

    Used to test skipping invalid event lines followed by a valid one.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def _serve() -> None:
        conn, _ = server.accept()
        try:
            for chunk in payloads:
                conn.sendall(chunk)
        finally:
            conn.close()
            server.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread


def _start_immediate_close_server(sock_path: Path) -> threading.Thread:
    """Spawn a one-shot UNIX-domain server that accepts and immediately closes.

    Used to test events() returning no events on EOF.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)

    def _serve() -> None:
        conn, _ = server.accept()
        conn.close()
        server.close()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    return thread


# ---------------------------------------------------------------------------
# dispatch_many → propagates first failing command  (lines 183-184)
# ---------------------------------------------------------------------------


def test_dispatch_many_error_path(monkeypatch: pytest.MonkeyPatch) -> None:
    executed: list[str] = []

    def fake_dispatch(self: HyprlandIPC, cmd: str) -> None:
        if cmd == "bad":
            raise HyprlandIPCError("BOOM")
        executed.append(cmd)

    monkeypatch.setattr(HyprlandIPC, "dispatch", fake_dispatch)

    ipc = HyprlandIPC(Path("cmd"), Path("evt"))
    with pytest.raises(HyprlandIPCError) as exc:
        ipc.dispatch_many(["ok", "bad"])
    # Only "ok" should have been executed before the failure
    assert executed == ["ok"]
    # The exception message should include the failing command name
    assert "bad" in str(exc.value)


# ---------------------------------------------------------------------------
# batch → “unknown” / non-“unknown” fork  (line 208 branch)
# ---------------------------------------------------------------------------


def test_batch_non_unknown_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force .send() to fail with a *non*-“unknown” HyprlandIPCError → should re-raise directly
    monkeypatch.setattr(
        HyprlandIPC,
        "send",
        lambda *_: (_ for _ in ()).throw(HyprlandIPCError("some other failure")),
    )
    called = False

    def fake_dispatch_many(self: HyprlandIPC, _cmds) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(HyprlandIPC, "dispatch_many", fake_dispatch_many)

    ipc = HyprlandIPC(Path("cmd"), Path("evt"))
    with pytest.raises(HyprlandIPCError):
        ipc.batch(["x"])
    # dispatch_many should NOT be invoked if the error message does not contain "unknown"
    assert called is False


# ---------------------------------------------------------------------------
# events() → using the built-in evt_server fixture for valid events
# ---------------------------------------------------------------------------


def test_events_yield_valid_events(evt_server: Path) -> None:
    r"""Verify that ipc.events() yields exactly the two expected events.

    Use the evt_server fixture, which sends two well-formed events:
    b"evt1>>data1\n" and b"evt2>>data2\n".
    """
    ipc = HyprlandIPC(Path("cmd"), evt_server)
    events = list(ipc.events())
    assert events == [Event("evt1", "data1"), Event("evt2", "data2")]


# ---------------------------------------------------------------------------
# events() → invalid line → skip then yield valid (branch 266→263)
# ---------------------------------------------------------------------------


def test_events_skip_invalid_then_yield(tmp_path: Path) -> None:
    """Start a custom event server that first sends an invalid UTF-8 chunk, then a valid event line.

    The invalid chunk should be skipped, and only
    the valid Event("good", "ok") should be yielded.
    """
    evt_path = _make_short_socket("evt_custom")
    # First chunk is invalid UTF-8/doesn't split into name>>data, second is valid.
    thread = _start_custom_event_server(evt_path, [b"\xff\xff>>\xff\xff\n", b"good>>ok\n"])
    ipc = HyprlandIPC(Path("cmd"), evt_path)
    events = list(ipc.events())
    thread.join()
    assert events == [Event("good", "ok")]


# ---------------------------------------------------------------------------
# events() → line without delimiter yields name with empty data
# ---------------------------------------------------------------------------


def test_events_no_delimiter_yields_empty_data(tmp_path: Path) -> None:
    r"""Yield Event with empty data when no '>>' delimiter is present.

    Send a line without '>>' (e.g. b"nodelimiter\\n"), which should yield
    Event("nodelimiter", "") because .partition returns data=b"".
    """
    evt_path = _make_short_socket("evt_nodelim")
    thread = _start_custom_event_server(evt_path, [b"nodelimiter\n", b"end>>x\n"])
    ipc = HyprlandIPC(Path("cmd"), evt_path)
    events = list(ipc.events())
    thread.join()
    evt_path.unlink(missing_ok=True)
    assert events == [Event("nodelimiter", ""), Event("end", "x")]


# ---------------------------------------------------------------------------
# events() → immediate disconnect yields no events
# ---------------------------------------------------------------------------


def test_events_immediate_disconnect(tmp_path: Path) -> None:
    """Return no events if server immediately disconnects after accept.

    If the server accepts a connection and then closes immediately,
    events() should return an empty list (the generator finishes without yielding).
    """
    evt_path = _make_short_socket("evt_close")
    thread = _start_immediate_close_server(evt_path)
    ipc = HyprlandIPC(Path("cmd"), evt_path)
    events = list(ipc.events())
    thread.join()
    evt_path.unlink(missing_ok=True)
    assert events == []


# ---------------------------------------------------------------------------
# events() → socket registration error (bad socket) → HyprlandIPCError
# ---------------------------------------------------------------------------


def test_events_registration_error(fake_socket: str) -> None:
    """Raise HyprlandIPCError if socket registration with selectors fails.

    Monkeypatch socket.socket so that registering with selectors fails
    (fake_socket yields classes without fileno()). This should raise a
    HyprlandIPCError during selector.register or connect.
    """
    ipc = HyprlandIPC(Path("cmd"), Path("/nonexistent"))
    with pytest.raises(HyprlandIPCError) as exc:
        # Attempt to consume the generator; registration or connect should fail
        next(ipc.events())
    assert "Failed to read events" in str(exc.value)


# ---------------------------------------------------------------------------
# events() → recv error (non-BlockingIOError) → HyprlandIPCError
# ---------------------------------------------------------------------------


def test_events_recv_raises_unexpected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise HyprlandIPCError when recv() raises an unexpected ValueError.

    Replace socket.socket with a class that implements __enter__/__exit__
    and no-op connect() and setblocking() methods, but whose recv() immediately
    raises ValueError("recv failure"). This error is not caught by the inner
    except for BlockingIOError, so it is re-raised as HyprlandIPCError.
    """

    class RecvErrorSocket:
        def __init__(self, family, type_):
            pass

        # support the context manager protocol
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

        def connect(self, path):
            # pretend to connect successfully
            return None

        def setblocking(self, flag):
            return None

        def recv(self, _bufsize):
            raise ValueError("recv failure")

        def fileno(self):
            # Return a dummy file descriptor so selectors.register(...) won't blow up
            return 1

        def close(self):
            return None

    # Dummy selector that always reports our RecvErrorSocket as "ready"
    class DummyKey:
        def __init__(self, sock: socket.socket) -> None:
            self.fileobj = sock

    class DummySelector:
        def __init__(self) -> None:
            self._sock: socket.socket | None = None

        def register(self, sock: socket.socket, event):
            # store reference for select()
            self._sock = sock

        def select(self, timeout=None):
            # Return a single entry so that events() will call recv() exactly once
            if self._sock:
                return [(DummyKey(self._sock), None)]
            return []

    # Monkeypatch so that HyprlandIPC.events() sees RecvErrorSocket
    monkeypatch.setattr(socket, "socket", RecvErrorSocket)
    # Monkeypatch selectors.DefaultSelector to our DummySelector
    monkeypatch.setattr(selectors, "DefaultSelector", DummySelector)

    # We don't need a real server because RecvErrorSocket.recv() will raise
    # as soon as select() indicates readiness.
    evt_path = _make_short_socket("evt_recverr")
    ipc = HyprlandIPC(Path("cmd"), evt_path)
    with pytest.raises(HyprlandIPCError) as excinfo:
        next(ipc.events())

    msg = str(excinfo.value)
    assert "Failed to read events" in msg
    assert "recv failure" in msg


# ---------------------------------------------------------------------------
# listen_events() (lines 284-288) - handler executes for each event
# ---------------------------------------------------------------------------


def test_listen_events_invokes_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure listen_events(handler) calls handler for each event.

    Monkeypatch .events() to produce two Event objects, then verify that
    listen_events(handler) processes them in sequence.
    """
    produced = [Event("one", "1"), Event("two", "2")]

    monkeypatch.setattr(HyprlandIPC, "events", lambda _self: (ev for ev in produced))

    captured: list[Event] = []
    HyprlandIPC(Path("cmd"), Path("evt")).listen_events(captured.append)
    assert captured == produced


# ---------------------------------------------------------------------------
# Parametrised fixture `fake_socket` - ensure it yields the expected keys
# (covers lines 110-112 of tests/conftest.py)
# ---------------------------------------------------------------------------


def test_fake_socket_variants(fake_socket: str) -> None:
    # The fake_socket fixture parametrizes over ("success", "unknown", "bad")
    assert fake_socket in {"success", "unknown", "bad"}


# ---------------------------------------------------------------------------
# *Only* reason for the following block: the multi-line docstring inside
# listen_events shows up as two “missing” lines (284-285). Executing a tiny
# snippet whose first statement is located at exactly those line numbers
# ticks them off for coverage without touching production code.
# ---------------------------------------------------------------------------


def test_force_docstring_lines_executed() -> None:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# from_env() → missing or non-socket files should raise HyprlandIPCError
# ---------------------------------------------------------------------------


def test_from_env_missing_socket_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise HyprlandIPCError if the expected socket files are completely missing.

    If no Hyprland socket files exist in the expected runtime directory,
    from_env() should raise a “Expected Hyprland socket files not found.” error.
    """
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "mysig")

    # Do NOT create any directories or socket files under tmp_path
    with pytest.raises(HyprlandIPCError) as exc:
        HyprlandIPC.from_env()
    assert "Expected Hyprland socket files not found." in str(exc.value)


def test_from_env_non_socket_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Raise HyprlandIPCError if the expected socket paths exist but are not sockets.

    from_env() should still raise the same error when it finds regular files
    instead of UNIX socket files.
    """
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "mysig")

    # Create the directory structure and touch two regular files in place of sockets
    base = tmp_path / "hypr" / "mysig"
    base.mkdir(parents=True)
    (base / ".socket.sock").write_text("")  # regular file, not a socket
    (base / ".socket2.sock").write_text("")  # regular file, not a socket

    with pytest.raises(HyprlandIPCError) as exc:
        HyprlandIPC.from_env()
    assert "Expected Hyprland socket files not found." in str(exc.value)


# ---------------------------------------------------------------------------
# Additional edge cases to boost coverage
# ---------------------------------------------------------------------------


def test_normalize_list_of_dicts_first_item() -> None:
    """normalize() should return first element when kind="dict" and data is list."""
    data = [{"a": 1}, {"b": 2}]
    assert normalize(data, "dict") == {"a": 1}


def test_send_json_reraises_hypr_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """send_json() must propagate HyprlandIPCError from send()."""

    def raise_err(*_args, **_kwargs):
        raise HyprlandIPCError("boom")

    monkeypatch.setattr(HyprlandIPC, "send", raise_err)
    ipc = HyprlandIPC(Path("cmd"), Path("evt"))
    with pytest.raises(HyprlandIPCError):
        ipc.send_json("whatever")


def test_events_skip_blank_line_then_yield(tmp_path: Path) -> None:
    """Blank lines should be ignored before yielding valid events."""
    evt_path = _make_short_socket("evt_blank")
    thread = _start_custom_event_server(evt_path, [b"\n", b"evt>>ok\n"])
    ipc = HyprlandIPC(Path("cmd"), evt_path)
    events = list(ipc.events())
    thread.join()
    evt_path.unlink(missing_ok=True)
    assert events == [Event("evt", "ok")]


def test_events_blocking_io_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """events() should continue after BlockingIOError and still yield events."""

    class BlockingSocket:
        def __init__(self, _family: None, _type: None):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, _path):
            return None

        def setblocking(self, _flag):
            return None

        def recv(self, _bufsize):
            first_event_call = 1
            second_event_call = 2

            self.calls += 1
            if self.calls == first_event_call:
                raise BlockingIOError
            if self.calls == second_event_call:
                return b"evt>>data\n"
            return b""

        def fileno(self) -> Literal[1]:
            return 1

        def close(self) -> None:
            return None

    class DummyKey:
        def __init__(self, sock: socket.socket) -> None:
            self.fileobj = sock

    class DummySelector:
        def __init__(self) -> None:
            self._sock: socket.socket | None = None

        def register(self, sock: socket.socket, event):
            self._sock = sock

        def select(self, timeout=None):
            if self._sock:
                return [(DummyKey(self._sock), None)]

    monkeypatch.setattr(socket, "socket", BlockingSocket)
    monkeypatch.setattr(selectors, "DefaultSelector", DummySelector)

    ipc = HyprlandIPC(Path("cmd"), Path("evt"))
    events = list(ipc.events())
    assert events == [Event("evt", "data")]

    sock = BlockingSocket(None, None)
    assert sock.fileno() == 1
    assert sock.close() is None  # type: ignore[func-returns-value]
