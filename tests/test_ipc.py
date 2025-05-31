import socket
from pathlib import Path
from typing import Any

import pytest
from src.hyprland_ipc.ipc import Event, HyprlandIPC, HyprlandIPCError


# ---------------------------------------------------------------------------#
#                              Helper fixtures                               #
# ---------------------------------------------------------------------------#


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


def test_listen_events(cmd_server: None, evt_server: None) -> None:
    events: list[Event] = list(HyprlandIPC(Path("a"), Path("b")).events())
    assert events == [Event("evt1", "data1"), Event("evt2", "data2")]
