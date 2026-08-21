"""Lookup `container_mail_marker`: path of the msmtp_curl delivery marker.

Single SPOT for the file the ``msmtp_curl`` healthcheck touches after msmtp
exits 0. A deploy-time assertion that the relay accepted the startup mail has
to name the same path the probe writes, and a second literal would drift the
moment the probe moves it.

Usage:
    {{ lookup('container_mail_marker') }}   -> /tmp/email_sent
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.docker.healthcheck.prefixes import MAIL_MARKER


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("lookup('container_mail_marker') expects no terms.")
        return [MAIL_MARKER]
