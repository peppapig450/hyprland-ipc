"""
HyprlandIPC: A reusable, type-safe Python IPC client for Hyprland's UNIX sockets.

- Send hyprctl-like commands and receive replies (raw or JSON).
- Send dispatches, single or batch.
- Listen for real-time Hyprland events via .socket2.sock.
- Raise descriptive errors for any IPC failures.

Designed for scripting, automation, and event-driven Hyprland tools.
"""

from __future__ import annotations

import json
import os
import selectors
import socket
from collections.abc import Sequence, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from typing import cast

type AnyDict = dict[str, Any]
"""Type alias for generic dictionaries representing Hyprland's JSON responses."""

@dataclass
class Event:
    """A Hyprland event, with a name and associated data string."""
    name: str
    data: str

class HyprlandIPCError(Exception):
    """Raised when HyprlandIPC fails to communicate or parse responses."""


class HyprlandIPC:
    """
    A reusable Hyprland IPC client for commands and events.

    Usage:
        ipc = HyprlandIPC.from_env()
        clients = ipc.get_clients()
        for event in ipc.events():
            ...
    """

    def __init__(self, socket_path: Path, event_socket_path: Path):
        """
        Initialize the IPC client with explicit socket paths.

        Args:
            socket_path: Path to the command socket (.socket.sock).
            event_socket_path: Path to the event socket (.socket2.sock).
        """
        self.socket_path = socket_path
        self.event_socket_path = event_socket_path

    @classmethod
    def from_env(cls) -> HyprlandIPC:
        """
        Create a HyprlandIPC client by discovering socket paths from the environment.

        Environment:
            - XDG_RUNTIME_DIR
            - HYPRLAND_INSTANCE_SIGNATURE

        Raises:
            HyprlandIPCError: If required environment variables are missing or sockets don't exist.

        Returns:
            HyprlandIPC: Ready-to-use client.
        """
        xdg_runtime = os.getenv("XDG_RUNTIME_DIR")
        hypr_instance_sig = os.getenv("HYPRLAND_INSTANCE_SIGNATURE")

        if not xdg_runtime or not hypr_instance_sig:
            missing: list[str] = []
            if not xdg_runtime:
                missing.append("XDG_RUNTIME_DIR")
            if not hypr_instance_sig:
                missing.append("HYPRLAND_INSTANCE_SIGNATURE")
            raise HyprlandIPCError(
                f"Must run under Hyprland (missing: {', '.join(missing)})"
            )

        base = Path(xdg_runtime).resolve() / "hypr" / hypr_instance_sig
        sock1 = base / ".socket.sock"
        sock2 = base / ".socket2.sock"

        # Ensure the sockets exist and are sockets
        if not sock1.is_socket() or not sock2.is_socket():
            raise HyprlandIPCError("Expected Hyprland socket files not found.")

        return cls(sock1, sock2)

    def send(self, command: str) -> str:
        """
        Send a raw command and return response as a string.

        Args:
            command: The command to send (e.g. 'j/clients' or 'dispatch ...').

        Raises:
            HyprlandIPCError: On connection, send, or protocol failure.

        Returns:
            str: The raw string response from Hyprland.
        """
        try:
            payload = command.encode(encoding="utf-8")

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(str(self.socket_path))
                sock.sendall(payload)
                response = bytearray()
                while True:
                    # Read until socket closes
                    if not (chunk := sock.recv(4096)):
                        break
                    response.extend(chunk)

            decoded = response.decode(encoding="utf-8").strip()

            # Hyprland signals an error with "unknown request"
            if decoded.startswith("unknown"):
                raise HyprlandIPCError(f"Hyprland returned an error: {decoded}")

            return decoded

        except Exception as e:
            raise HyprlandIPCError(
                f"Failed to send IPC command '{command}': {e}"
            ) from e

    def send_json(self, command: str) -> Any:
        """
        Send a command with 'j/' prefix and parse the JSON response.

        Args:
            command: The command after 'j/' (e.g. 'clients', 'activewindow').

        Raises:
            HyprlandIPCError: On IPC or JSON parse failure.

        Returns:
            Any: Parsed JSON response (typically dict or list).
        """
        try:
            resp = self.send(f"j/{command}")
            return json.loads(resp) if resp else {}
        except json.JSONDecodeError as e:
            raise HyprlandIPCError(
                f"Invalid JSON response for command '{command}': {e}"
            ) from e
        except HyprlandIPCError:
            raise  # Re-raise IPC errors cleanly
        except Exception as e:
            raise HyprlandIPCError(
                f"Failed to send or parse JSON for command '{command}': {e} "
            )

    def dispatch(self, command: str) -> None:
        """
        Send a single dispatch command.

        Args:
            command: e.g., 'focuswindow address:0xabc', 'fullscreen 1'

        Raises:
            HyprlandIPCError: On failure.
        """
        try:
            self.send(f"dispatch {command}")
        except HyprlandIPCError as e:
            raise HyprlandIPCError(f"Failed to dispatch '{command}': {e}") from e

    def dispatch_many(self, commands: Sequence[str]) -> None:
        """
        Send multiple dispatch commands (as individual requests).

        Args:
            commands: Iterable of dispatch commands.

        Raises:
            HyprlandIPCError: On failure of any command.
        """
        for cmd in commands:
            try:
                self.dispatch(cmd)
            except HyprlandIPCError as e:
                raise HyprlandIPCError(
                    f"Failed to dispatch command '{cmd}': {e}"
                ) from e

    def batch(self, commands: Sequence[str]) -> None:
        """
        Send multiple dispatch commands as a single string, separated by ';'.

        Not all Hyprland versions support batch over IPC; falls back to dispatch_many if batch fails.

        Args:
            commands: Iterable of dispatch commands.

        Raises:
            HyprlandIPCError: On overall failure.
        """
        try:
            cmd_str = "; ".join(commands)
            self.send(f"dispatch {cmd_str}")
        except HyprlandIPCError as e:
            # Detect error message and fallback
            # Fallback unverified. May not work on older Hyprland versions.
            if "unknown" in str(e).lower():
                self.dispatch_many(commands)
            else:
                raise

    def get_clients(self) -> list[AnyDict]:
        """
        List all windows with their properties as a JSON object.

        Returns:
            list[AnyDict]: List of client window info dicts.
        """
        return self.send_json("clients")

    def get_active_window(self) -> AnyDict:
        """
        Get the active window name and its properties as a JSON object.

        Returns:
            AnyDict: Active window info.
        """
        return self.send_json("activewindow")

    def get_active_workspace(self) -> AnyDict:
        """
        Get the active workspace and its properties as a JSON object.

        Returns:
            AnyDict: Active workspace info.
        """        
        return self.send_json("activeworkspace")

    def events(self) -> Iterator[Event]:
        """
        Listen to .socket2.sock for Hyprland events.

        Yields:
            Event: Each event as an Event(name, data) object.
                - name: The event type (e.g. 'workspace', 'activewindowv2')
                - data: The event data string.

        Raises:
            HyprlandIPCError: On socket read error.
        """
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(str(self.event_socket_path))
                sock.setblocking(False)

                sel = selectors.DefaultSelector()
                sel.register(sock, selectors.EVENT_READ)
                
                buf = bytearray()

                while True:
                    for key, _ in sel.select(timeout=0.01): # 10ms timeout
                        conn = cast(socket.socket, key.fileobj)
                        try:
                            chunk = conn.recv(4096)
                            if not chunk:
                                return # Disconnected
                            buf.extend(chunk)
                            while b"\n" in buf:
                                line, _, rest = buf.partition(b"\n")
                                buf[:] = rest
                                if line:
                                    try:
                                        ev, _, data = line.partition(b">>")
                                        yield Event(ev.decode(), data.decode())
                                    except Exception:
                                        continue
                        except BlockingIOError:
                            continue

        except Exception as e:
            raise HyprlandIPCError(f"Failed to read events: {e}") from e

    def listen_events(self, handler: Callable[[Event], None]) -> None:
        """
        Run a callback for each event as it is received (blocks forever).

        Args:
            handler: Callable that accepts Event.
        """
        for event in self.events():
            handler(event)
