<!--
SPDX-FileCopyrightText: 2025-present peppapig450 <peppapig450@pm.me>

SPDX-License-Identifier: MIT
-->

# hyprland-ipc

[![Test and Coverage](https://github.com/peppapig450/hyprland-ipc/actions/workflows/test-coverage.yml/badge.svg)](https://github.com/peppapig450/hyprland-ipc/actions/workflows/test-coverage.yml)
[![codecov](https://codecov.io/gh/peppapig450/hyprland-ipc/branch/main/graph/badge.svg)](https://codecov.io/gh/peppapig450/hyprland-ipc)
[![PyPI - Version](https://img.shields.io/pypi/v/hyprland-ipc.svg)](https://pypi.org/project/hyprland-ipc)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/hyprland-ipc.svg)](https://pypi.org/project/hyprland-ipc)

-----

## Table of Contents

- [hyprland-ipc](#hyprland-ipc)
  - [Table of Contents](#table-of-contents)
- [Installation](#installation)
  - [Usage](#usage)
  - [License](#license)

## Installation

```console
pip install hyprland-ipc
```

This package requires Python 3.12 or newer.

## Usage

```python
from hyprland_ipc import HyprlandIPC

# Discover socket paths from the environment
ipc = HyprlandIPC.from_env()

# Print two events then exit
for i, event in enumerate(ipc.events()):
    print(event)
    if i == 1:
        break
```

## License

`hyprland-ipc` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
