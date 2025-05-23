from __future__ import annotations
import os
import socket
import json
from pathlib import Path
from typing import Callable, Iterator, Any


class HyprlandIPCError(Exception):
    """Raised when HyprlandIPC fails to communicate."""


class HyprlandIPC:
    """A reusable Hyprland IPC client for commands and events."""

    def __init__(
        self, socket_path: Path, event_socket_path: Path
    ):
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