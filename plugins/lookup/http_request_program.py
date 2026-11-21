"""Lookup `http_request_program`: the stdin program that runs http_request.py.

    lookup('http_request_program', body)
    lookup('http_request_program', body, headers={'Authorization': '...'})

Args:
    body: request body text; an empty string sends none.
    headers: keyword, mapping of extra request headers; absent sends none.

Returns:
    ``BODY_B64 = "<base64 of body>"`` and ``HEADERS_B64 = "<base64 of the
    headers as JSON>"`` followed by
    ``roles/sys-svc-compose/files/python/http_request.py`` under
    ``playbook_dir``, for ``python3 -`` on stdin. Body and headers ride in the
    program because Ansible renders ``environment:`` onto the remote command
    line.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.files import read_text

SCRIPT = "roles/sys-svc-compose/files/python/http_request.py"


class LookupModule(LookupBase):
    def run(
        self, terms: list[Any], variables: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[str]:
        if len(terms) != 1:
            raise AnsibleError(
                "lookup('http_request_program', body) takes exactly one term"
            )
        base = (variables or {}).get("playbook_dir")
        if not base:
            raise AnsibleError(
                "lookup('http_request_program'): 'playbook_dir' is unavailable."
            )
        headers = kwargs.get("headers", {})
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        ):
            raise AnsibleError(
                "lookup('http_request_program'): headers must map strings to strings"
            )
        body_b64 = base64.b64encode(str(terms[0]).encode()).decode()
        headers_b64 = base64.b64encode(json.dumps(headers).encode()).decode()
        script = read_text(str(Path(str(base)) / SCRIPT))
        return [
            (
                f"BODY_B64 = {json.dumps(body_b64)}\n"
                f"HEADERS_B64 = {json.dumps(headers_b64)}\n{script}"
            )
        ]
