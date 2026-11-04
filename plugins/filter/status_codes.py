"""Expose the status codes that prove a domain is served to templates."""

from __future__ import annotations

import sys
from pathlib import Path

# nocheck: project-root-import
_BASE_DIR = str(Path(__file__).resolve().parents[2])
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from utils.roles.applications.status_codes import (  # noqa: E402
    accepted_status_codes,
)


class FilterModule:
    def filters(self):
        return {"accepted_status_codes": accepted_status_codes}
