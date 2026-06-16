"""Compatibility utilities for different Python versions."""

from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Compatibility shim for StrEnum in Python < 3.11."""

        pass
