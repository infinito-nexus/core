from __future__ import annotations

import io
import json
import runpy
import unittest
import urllib.error
from unittest.mock import patch

from . import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "roles/web-app-wazuh/files/python/api_administrators.py"
ENV = {
    "API_USERNAME": "wazuh-wui",
    "API_PASSWORD": "s3cret",
    "WAZUH_RBAC_RULE_NAME": "infinito_administrators",
    "WAZUH_RBAC_BACKEND_ROLES": json.dumps(["admin"]),
    "WAZUH_RBAC_API_ROLE": "administrator",
}
NOT_READY = {
    "title": "Wazuh Internal Error",
    "detail": "Some Wazuh daemons are not ready yet (wazuh-modulesd->failed)",
    "error": 1017,
}


def _refuse(request, context=None):
    raise urllib.error.HTTPError(
        request.full_url,
        500,
        "Internal Server Error",
        None,
        io.BytesIO(json.dumps(NOT_READY).encode()),
    )


class TestApiAdministratorsErrors(unittest.TestCase):
    def test_an_api_error_carries_the_wazuh_error_body(self):
        with (
            patch("urllib.request.urlopen", _refuse),
            patch.dict("os.environ", ENV),
            self.assertRaises(RuntimeError) as raised,
        ):
            runpy.run_path(str(SCRIPT_PATH), run_name="__main__")
        message = str(raised.exception)
        self.assertIn("POST /security/user/authenticate answered HTTP 500", message)
        self.assertIn("wazuh-modulesd->failed", message)


if __name__ == "__main__":
    unittest.main()
