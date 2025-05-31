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

