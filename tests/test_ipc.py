import socket
from pathlib import Path
import tempfile
import uuid
from typing import Any

import pytest
from src.hyprland_ipc.ipc import Event, HyprlandIPC, HyprlandIPCError


# ---------------------------------------------------------------------------#
#                              Helper fixtures                               #
# ---------------------------------------------------------------------------#


@pytest.fixture()
def ipc(tmp_path: Path) -> HyprlandIPC:
    """HyprlandIPC pointing at dummy paths."""
    return HyprlandIPC(tmp_path / "cmd.sock", tmp_path / "evt.sock")


# ---------------------------------------------------------------------------#
#                              Event dataclass                               #
# ---------------------------------------------------------------------------#


def test_event_equality_and_attrs() -> None:
    e1 = Event("name", "data")
    e2 = Event("name", "data")
    assert e1 == e2
    assert (e1.name, e1.data) == ("name", "data")


# ---------------------------------------------------------------------------#
#                                 from_env                                   #
# ---------------------------------------------------------------------------#


@pytest.mark.parametrize(
    ("env", "missing_names"),
    [
        ({}, ("XDG_RUNTIME_DIR", "HYPRLAND_INSTANCE_SIGNATURE")),
        ({"XDG_RUNTIME_DIR": "/tmp"}, ("HYPRLAND_INSTANCE_SIGNATURE",)),  # noqa: S108
        ({"HYPRLAND_INSTANCE_SIGNATURE": "sig"}, ("XDG_RUNTIME_DIR",)),
    ],
)
def test_from_env_missing(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], missing_names: tuple[str, ...]
) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    with pytest.raises(HyprlandIPCError) as exc:
        HyprlandIPC.from_env()

    msg = str(exc.value)
    for name in missing_names:
        assert name in msg


def test_from_env_socket_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_dir = Path(tempfile.gettempdir()) / f"hypripc_{uuid.uuid4().hex[:8]}"
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
    monkeypatch.setenv("HYPRLAND_INSTANCE_SIGNATURE", "sig")

    base = runtime_dir / "hypr" / "sig"
    base.mkdir(parents=True, exist_ok=True)
    cmd = base / ".socket.sock"
    evt = base / ".socket2.sock"

    # make them real sockets so that Path.is_socket() is true
    for p in (cmd, evt):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(str(p))
        s.listen(1)
        s.close()

    ipc_obj = HyprlandIPC.from_env()
    assert ipc_obj.socket_path.samefile(cmd.resolve())
    assert ipc_obj.event_socket_path.samefile(evt.resolve())


# ---------------------------------------------------------------------------#
#                                   send()                                   #
# ---------------------------------------------------------------------------#

# ---------------------------------------------------------------------------#
#                               send_json()                                  #
# ---------------------------------------------------------------------------#


@pytest.mark.parametrize(
    "commands, expect",
    [
        (["x", "y"], ["x", "y"]),
    ],
)
# ---------------------------------------------------------------------------#
#                                dispatch()                                  #
# ---------------------------------------------------------------------------#

# ---------------------------------------------------------------------------#
#                              dispatch_many()                               #
# ---------------------------------------------------------------------------#

    called: list[str] = []
# ---------------------------------------------------------------------------#
#                                 batch()                                    #
# ---------------------------------------------------------------------------#


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


# ---------------------------------------------------------------------------#
#                            Convenience wrappers                            #
# ---------------------------------------------------------------------------#


def test_get_wrappers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        HyprlandIPC, "send_json", lambda self, c: [1, 2] if c == "clients" else {"k": "v"}
    )
    ipc_obj: HyprlandIPC = HyprlandIPC(Path("a"), Path("b"))
    assert [client["id"] for client in ipc_obj.get_clients()] == [1, 2]
    assert ipc_obj.get_active_window() == {"k": "v"}
    assert ipc_obj.get_active_workspace() == {"k": "v"}


# ---------------------------------------------------------------------------#
#                                  events()                                  #
# ---------------------------------------------------------------------------#


def test_events_iteration(cmd_server, evt_server) -> None:
    """Real socket integration test."""
    ipc_obj = HyprlandIPC(cmd_server, evt_server)
    events = list(ipc_obj.events())
    assert events == [Event("evt1", "data1"), Event("evt2", "data2")]
