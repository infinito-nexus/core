"""Lookup `http_request_program`: the stdin program that runs http_request.py.

    lookup('http_request_program', body)

Args:
    body: request body text; an empty string sends none.

Returns:
    ``BODY_B64 = "<base64 of body>"`` followed by
    ``roles/sys-svc-compose/files/python/http_request.py`` under
    ``playbook_dir``, for ``python3 -`` on stdin. The body rides in the program
    because Ansible renders ``environment:`` onto the remote command line.
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
        encoded = base64.b64encode(str(terms[0]).encode()).decode()
        script = read_text(str(Path(str(base)) / SCRIPT))
        return [f"BODY_B64 = {json.dumps(encoded)}\n{script}"]
