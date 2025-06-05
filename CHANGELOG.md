<!--
SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>

SPDX-License-Identifier: MIT
-->
# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2025-06-05
### Added
- `HyprlandIPC` class for sending commands through Hyprland's Unix sockets.
- `send` and `send_json` helpers for raw and JSON replies.
- `dispatch`, `dispatch_many` and `batch` methods to control Hyprland.
- Wrapper methods `get_clients`, `get_active_window`, and `get_active_workspace` for common JSON queries.
- Low level `events` generator and `listen_events` callback interface.
- Non-blocking event listener using `selectors`.
- `Event` dataclass to represent incoming events.
- `from_env` helper to locate socket paths automatically.

### Fixed
- More precise return types in `send_json` and error chaining in `send`.
- Unicode decode errors are now handled when parsing events.
- Exported `__version__` in `hyprland_ipc.__init__`.
- Corrected project description typo and pytest path configuration.
- Tests use short temporary paths for UNIX sockets to avoid `OSError`.
