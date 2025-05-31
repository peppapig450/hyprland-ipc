import socket
from pathlib import Path
from typing import Any

import pytest
from src.hyprland_ipc.ipc import Event, HyprlandIPC, HyprlandIPCError


# Tests for event dataclass


def test_event_equality():
    e1 = Event("name", "data")
    e2 = Event("name", "data")
    assert e1 == e2
    assert e1.name == "name"
    assert e1.data == "data"


# Tests for from_env


@pytest.mark.parametrize(
    "xdg, sig, missing",
    [
        (False, False, "XDG_RUNTIME_DIR and HYPRLAND_INSTANCE_SIGNATURE"),
        (True, False, "HYPRLAND_INSTANCE_SIGNATURE"),
        (False, True, "XDG_RUNTIME_DIR"),
    ],
)
def test_from_env_missing_vars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg: bool, sig: bool, missing: str
) -> None:
    if xdg:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    else:
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    if sig:
        monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")
    else:
        monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)

    with pytest.raises(HyprlandIPCError) as exc:
        HyprlandIPC.from_env()
    assert missing in str(exc.value)


def test_from_env_sockets_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")
    base = tmp_path / "hypr" / "sig"
    base.mkdir(parents=True, exist_ok=True)

    with pytest.raises(HyprlandIPCError) as exc:
        HyprlandIPC.from_env()
    assert "socket files not found" in str(exc.value)


def test_from_env_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")
    base = tmp_path / "hypr" / "sig"
    base.mkdir(parents=True, exist_ok=True)
    sock1 = base / ".socket.sock"
    sock2 = base / ".socket2.sock"

    server1 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server1.bind(str(sock1))
    server1.listen(1)
    server2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server2.bind(str(sock2))
    server2.listen(1)
    try:
        ipc_obj = HyprlandIPC.from_env()
        assert isinstance(ipc_obj, HyprlandIPC)
        assert ipc_obj.socket_path == sock1
        assert ipc_obj.event_socket_path == sock2
    finally:
        server1.close()
        server2.close()


# Tests for send


def test_send_success(fake_socket_success: None) -> None:
    ipc_obj = HyprlandIPC(Path("/tmp/cmd"), Path("/tmp/evt"))
    result = ipc_obj.send("cmd")
    assert result == "resp"


def test_send_unknown_error(fake_socket_unknown: None) -> None:
    ipc_obj = HyprlandIPC(Path("/tmp/cmd"), Path("/tmp/evt"))
    with pytest.raises(HyprlandIPCError):
        ipc_obj.send("cmd")


def test_send_socket_failure(bad_socket: None) -> None:
    ipc_obj = HyprlandIPC(Path("/tmp/cmd"), Path("/tmp/evt"))
    with pytest.raises(HyprlandIPCError) as exc:
        ipc_obj.send("cmd")
    assert "Failed to send IPC command" in str(exc.value)


# Tests for send_json


def test_send_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda self, c: '{"key": "value"}')
    ipc_obj = HyprlandIPC(Path("a"), Path("b"))
    result: dict[str, Any] = ipc_obj.send_json("cmd")
    assert result == {"key": "value"}


def test_send_json_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda self, c: "")
    ipc_obj: HyprlandIPC = HyprlandIPC(Path("a"), Path("b"))
    result: dict[str, Any] = ipc_obj.send_json("cmd")
    assert result == {}


def test_send_json_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda self, c: "notjson")
    ipc_obj = HyprlandIPC(Path("a"), Path("b"))
    with pytest.raises(HyprlandIPCError):
        ipc_obj.send_json("cmd")


# Tests for dispatch methods


def test_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "send", lambda self, c: calls.append(c))
    ipc_obj = HyprlandIPC(Path("a"), Path("b"))
    ipc_obj.dispatch("do")
    assert calls == ["dispatch do"]


def test_dispatch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(self, c: str) -> None:
        raise HyprlandIPCError("oopsies daisies")

    monkeypatch.setattr(HyprlandIPC, "send", fake_send)
    ipc_obj = HyprlandIPC(Path("a"), Path("b"))
    with pytest.raises(HyprlandIPCError) as exc:
        ipc_obj.dispatch("do")
    assert "Failed to dispatch 'do'" in str(exc.value)


@pytest.mark.parametrize(
    "commands, expect",
    [
        (["x", "y"], ["x", "y"]),
    ],
)
def test_dispatch_many(commands: list[str], expect: list[str]) -> None:
    called: list[str] = []

    def fake_dispatch(self, c: str) -> None:
        called.append(c)

    monkeypatch_util = pytest.MonkeyPatch()
    monkeypatch_util.setattr(HyprlandIPC, "dispatch", fake_dispatch)
    ipc_obj = HyprlandIPC(Path("a"), Path("b"))
    ipc_obj.dispatch_many(commands)
    assert called == expect
    monkeypatch_util.undo()


# Tests for batch


def test_batch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "send", lambda self, c: calls.append(c))
    ipc_obj: HyprlandIPC = HyprlandIPC(Path("a"), Path("b"))
    ipc_obj.batch(["x", "y"])
    assert calls == ["dispatch x; y"]


def test_batch_fallback(
    monkeypatch: pytest.MonkeyPatch, monkeypatch_session: pytest.MonkeyPatch
) -> None:
    def bad_send(self, c: str) -> None:
        raise HyprlandIPCError("unknown error")

    called: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "send", bad_send)
    monkeypatch_session.setattr(
        HyprlandIPC, "dispatch_many", lambda self, cmds: called.extend(cmds)
    )
    ipc_obj: HyprlandIPC = HyprlandIPC(Path("a"), Path("b"))
    ipc_obj.batch(["m", "n"])
    assert called == ["m", "n"]


# Tests for wrapper methods


def test_get_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        HyprlandIPC, "send_json", lambda self, c: [1, 2] if c == "clients" else {"k": "v"}
    )
    ipc_obj: HyprlandIPC = HyprlandIPC(Path("a"), Path("b"))
    assert [client["id"] for client in ipc_obj.get_clients()] == [1, 2]
    assert ipc_obj.get_active_window() == {"k": "v"}
    assert ipc_obj.get_active_workspace() == {"k": "v"}


# Test for listen_events


def test_listen_events(cmd_server: None, evt_server: None) -> None:
    events: list[Event] = list(HyprlandIPC(Path("a"), Path("b")).events())
    assert events == [Event("evt1", "data1"), Event("evt2", "data2")]
