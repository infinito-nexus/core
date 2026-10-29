"""Expose the response security headers of one application to templates."""

from __future__ import annotations

from utils.roles.applications.security_headers import security_headers


class FilterModule:
    def filters(self):
        return {"security_headers": security_headers}
