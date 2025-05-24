from __future__ import annotations
import os
import socket
import json
from pathlib import Path
from typing import Callable, Iterator, Any, TYPE_CHECKING
from collections.abc import Sequence
import selectors

if TYPE_CHECKING:
    from typing import cast

type AnyDict = dict[str, Any]
"""Type alias for generic dictionaries."""


class HyprlandIPCError(Exception):
    """Raised when HyprlandIPC fails to communicate."""


class HyprlandIPC:
    """A reusable Hyprland IPC client for commands and events."""

    def __init__(self, socket_path: Path, event_socket_path: Path):
        self.socket_path = socket_path
        self.event_socket_path = event_socket_path

    @classmethod
    def from_env(cls) -> HyprlandIPC:
        """Create a HyprlandIPC client by discovering socket paths from the environment.

        Requires:
            - XDG_RUNTIME_DIR
            - HYPRLAND_INSTANCE_SIGNATURE

        Raises:
            HyprlandIPCError: If required environment variables are missing or sockets don't exist.
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

        if not sock1.is_socket() or not sock2.is_socket():
            raise HyprlandIPCError("Expected Hyprland socket files not found.")

        return cls(sock1, sock2)

    def send(self, command: str) -> str:
        """Send a raw command and return response as string."""
        try:
            payload = command.encode(encoding="utf-8")

            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(str(self.socket_path))
                sock.sendall(payload)
                response = bytearray()
                while True:
                    if not (chunk := sock.recv(4096)):
                        break
                    response.extend(chunk)

            decoded = response.decode(encoding="utf-8").strip()

            # Throw error on "unknown request" response
            if decoded.startswith("unknown"):
                raise HyprlandIPCError(f"Hyprland returned an error: {decoded}")

            return decoded

        except Exception as e:
            raise HyprlandIPCError(
                f"Failed to send IPC command '{command}': {e}"
            ) from e

    def send_json(self, command: str) -> Any:
        """Send a command with 'j/' prefix and parse the JSON response."""
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
        """Send a single dispatch command."""
        try:
            self.send(f"dispatch {command}")
        except HyprlandIPCError as e:
            raise HyprlandIPCError(f"Failed to dispatch '{command}': {e}") from e

    def dispatch_many(self, commands: Sequence[str]) -> None:
        """Send multiple dispatch commands (as individual requests)."""
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
        Not all Hyprland versions support batch over IPC; fallback to dispatch_many.
        """
        try:
            cmd_str = "; ".join(commands)
            self.send(f"dispatch {cmd_str}")
        except HyprlandIPCError as e:
            # Detect error message and fallback
            # NOTE: this is untested as an effective fallback.
            if "unknown" in str(e).lower():
                self.dispatch_many(commands)
            else:
                raise

    def get_clients(self) -> list[AnyDict]:
        """List all windows with their properties as a JSON object."""
        return self.send_json("clients")

    def get_active_window(self) -> AnyDict:
        """Get the active window name and its properties as a JSON object."""
        return self.send_json("activewindow")

    def get_active_workspace(self) -> AnyDict:
        """Gets the active workspace and its properties as a JSON object."""
        return self.send_json("activeworkspace")

    def events(self) -> Iterator[tuple[str, str]]:
        """
        Listen  to .socket2.sock for Hyprland events.
        Yields (event_name, data) tuples.
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
                                return
                            buf.extend(chunk)
                            while b"\n" in buf:
                                line, _, rest = buf.partition(b"\n")
                                buf[:] = rest
                                if line:
                                    try:
                                        ev, _, data = line.partition(b">>")
                                        yield (ev.decode(), data.decode())
                                    except Exception:
                                        continue
                        except BlockingIOError:
                            continue

        except Exception as e:
            raise HyprlandIPCError(f"Failed to read events: {e}") from e

    def listen_events(self, handler: Callable[[str, str], None]) -> None:
        """Run a callback for each event (event_name, data). Blocks forever."""
        for event, data in self.events():
            handler(event, data)
