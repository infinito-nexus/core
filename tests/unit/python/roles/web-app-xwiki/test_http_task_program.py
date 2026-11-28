from __future__ import annotations

import base64
import json
import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from utils import PROJECT_ROOT
from utils.cache.files import read_text

TASKS = PROJECT_ROOT / "roles/web-app-xwiki/tasks/utils/http.yml"
SCRIPT = PROJECT_ROOT / "roles/web-app-xwiki/files/python/http_call.py"
HEADERS = {"Authorization": "Basic c3VwZXJhZG1pbjpzZWNyZXQ=", "Cookie": "a=b"}
BODY = "<page>\n  <title>X</title>\n</page>\n"


class _PathAbsolute(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return [str(PROJECT_ROOT / terms[0])]


def _rendered_stdin(headers: dict, body: str) -> str:
    """Returns the stdin the send task of tasks/utils/http.yml hands to python3."""
    block = DataLoader().load_from_file(str(TASKS), trusted_as_template=True)[0]
    stdin = block["block"][0]["ansible.builtin.command"]["stdin"]
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "path_absolute":
            return _PathAbsolute()
        return real_get(name, *args, **kwargs)

    templar = Templar(
        loader=DataLoader(),
        variables={"xwiki_http_headers": headers, "xwiki_http_body": body},
    )
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return templar.template(stdin)


class TestTheSendTaskHandsPythonARunnableProgram(unittest.TestCase):
    def test_the_rendered_stdin_compiles(self):
        compile(_rendered_stdin(HEADERS, BODY), "<stdin>", "exec")

    def test_the_globals_carry_the_headers_and_the_body(self):
        lines = _rendered_stdin(HEADERS, BODY).splitlines()
        namespace: dict = {}
        exec("\n".join(lines[:2]), namespace)
        self.assertEqual(
            HEADERS, json.loads(base64.b64decode(namespace["HEADERS_B64"]))
        )
        self.assertEqual(BODY, base64.b64decode(namespace["BODY_B64"]).decode())

    def test_the_script_follows_the_globals_unchanged(self):
        program = _rendered_stdin({}, "")
        self.assertEqual(
            read_text(str(SCRIPT)).rstrip("\n"),
            program.split("\n", 2)[2].rstrip("\n"),
        )


if __name__ == "__main__":
    unittest.main()
