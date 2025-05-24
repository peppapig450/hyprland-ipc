from __future__ import annotations
import os
import socket
import json
from pathlib import Path
from typing import Callable, Iterator, Any
from collections.abc import Sequence


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
