# SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>
#
# SPDX-License-Identifier: MIT
from .__about__ import __version__
from .ipc import Event, HyprlandIPC, HyprlandIPCError


__all__ = ["Event", "HyprlandIPC", "HyprlandIPCError", "__version__"]
