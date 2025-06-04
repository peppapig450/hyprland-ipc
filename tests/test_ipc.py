# SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>
#
# SPDX-License-Identifier: MIT

import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from hyprland_ipc.ipc import Event, HyprlandIPC, HyprlandIPCError, normalize


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


@pytest.mark.parametrize(
    ("socket_fixture", "expected", "exc"),
    [
        ("fake_socket_success", "resp", None),
        ("fake_socket_unknown", None, HyprlandIPCError),
        ("bad_socket", None, HyprlandIPCError),
    ],
)
def test_send(
    socket_fixture: str,
    expected: str | None,
    exc: None | type[BaseException],
    request: pytest.FixtureRequest,
    ipc: HyprlandIPC,
) -> None:
    # activate the correct fake socket for this parameterised case
    request.getfixturevalue(socket_fixture)

    if exc is not None:
        with pytest.raises(exc):
            ipc.send("cmd")
    else:
        assert ipc.send("cmd") == expected


# ---------------------------------------------------------------------------#
#                               send_json()                                  #
# ---------------------------------------------------------------------------#


@pytest.mark.parametrize(
    ("send_return", "expected", "raises"),
    [
        ('{"key": "value"}', {"key": "value"}, None),
        ("", {}, None),
        ("notjson", None, HyprlandIPCError),
    ],
)
def test_send_json(
    monkeypatch: pytest.MonkeyPatch,
    ipc: HyprlandIPC,
    send_return: str,
    expected: dict[str, Any] | None,
    raises: type[BaseException] | None,
) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda *_: send_return)

    if raises:
        with pytest.raises(raises):
            ipc.send_json("cmd")
    else:
        assert ipc.send_json("cmd") == expected


def test_send_json_unexpected(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(HyprlandIPCError) as exc:
        ipc.send_json("clients")
    assert "Failed to send or parse JSON" in str(exc.value)


# ---------------------------------------------------------------------------#
#                                dispatch()                                  #
# ---------------------------------------------------------------------------#


def test_dispatch_composes_command(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    sent: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "send", lambda _self, c: sent.append(c))
    ipc.dispatch("togglefloating")
    assert sent == ["dispatch togglefloating"]


def test_dispatch_error(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    monkeypatch.setattr(HyprlandIPC, "send", lambda *_: (_ for _ in ()).throw(HyprlandIPCError()))
    with pytest.raises(HyprlandIPCError):
        ipc.dispatch("do")


# ---------------------------------------------------------------------------#
#                              dispatch_many()                               #
# ---------------------------------------------------------------------------#


def test_dispatch_many_calls_each(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    called: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "dispatch", lambda _self, c: called.append(c))
    ipc.dispatch_many(["a", "b"])
    assert called == ["a", "b"]


# ---------------------------------------------------------------------------#
#                                 batch()                                    #
# ---------------------------------------------------------------------------#


def test_batch_success(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    sent: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "send", lambda _self, c: sent.append(c))
    ipc.batch(["x", "y"])
    assert sent == ["dispatch x; y"]


def test_batch_fallback(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    monkeypatch.setattr(
        HyprlandIPC, "send", lambda *_: (_ for _ in ()).throw(HyprlandIPCError("unknown"))
    )
    called: list[str] = []
    monkeypatch.setattr(HyprlandIPC, "dispatch_many", lambda _self, cmds: called.extend(cmds))
    ipc.batch(["m", "n"])
    assert called == ["m", "n"]


# ---------------------------------------------------------------------------#
#                            Convenience wrappers                            #
# ---------------------------------------------------------------------------#


def test_wrapper_methods(monkeypatch: pytest.MonkeyPatch, ipc: HyprlandIPC) -> None:
    monkeypatch.setattr(
        HyprlandIPC,
        "send_json",
        lambda _self, c: [{"id": 1}, {"id": 2}] if c == "clients" else {"k": "v"},
    )

    assert [c["id"] for c in ipc.get_clients()] == [1, 2]
    assert ipc.get_active_window() == {"k": "v"}
    assert ipc.get_active_workspace() == {"k": "v"}


# ---------------------------------------------------------------------------#
#                                  events()                                  #
# ---------------------------------------------------------------------------#


def test_events_iteration(cmd_server, evt_server) -> None:
    """Real socket integration test."""
    ipc_obj = HyprlandIPC(cmd_server, evt_server)
    events = list(ipc_obj.events())
    assert events == [Event("evt1", "data1"), Event("evt2", "data2")]


# ---------------------------------------------------------------------------#
#                                 normalize()                                #
# ---------------------------------------------------------------------------#


def test_normalize_returns_same_list() -> None:
    data = [{"a": 1}, {"b": 2}]
    assert normalize(data, "list") is data


def test_normalize_wraps_dict_as_list() -> None:
    data = {"k": "v"}
    assert normalize(data, "list") == [data]


@pytest.mark.parametrize("value", [None, "str", 1, [1, 2], 3.14])
def test_normalize_invalid_inputs(value: object) -> None:
    assert normalize(value, "list") == []
    assert normalize(value, "dict") == {}
