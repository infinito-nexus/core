"""Expose the status codes that prove a domain is served to templates."""

from __future__ import annotations

import sys
from pathlib import Path

# nocheck: project-root-import
_BASE_DIR = str(Path(__file__).resolve().parents[2])
_MODULE_UTILS_DIR = str(Path(_BASE_DIR) / "utils")
for _p in (_BASE_DIR, _MODULE_UTILS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from utils.roles.applications.status_codes import (  # noqa: E402
    accepted_status_codes,
)


class FilterModule:
    def filters(self):
        return {"accepted_status_codes": accepted_status_codes}
