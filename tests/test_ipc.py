import os
import socket
import threading
from pathlib import Path

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
