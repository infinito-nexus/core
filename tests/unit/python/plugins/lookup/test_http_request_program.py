"""Unit tests for the http_request_program lookup plugin."""

from __future__ import annotations

import base64
import json
import unittest

from ansible.errors import AnsibleError

from plugins.lookup.http_request_program import SCRIPT, LookupModule
from utils.cache.files import read_text

from . import PROJECT_ROOT

BODY = json.dumps({"password": "s3cr\"et'\n"})


def _program(body: str, **kwargs) -> str:
    return LookupModule().run(
        [body], variables={"playbook_dir": str(PROJECT_ROOT)}, **kwargs
    )[0]


def _preamble(program: str) -> dict:
    namespace: dict = {}
    exec("\n".join(program.split("\n", 2)[:2]), namespace)
    return namespace


class TestHttpRequestProgram(unittest.TestCase):
    def test_program_carries_the_body_and_the_script(self):
        program = _program(BODY)

        namespace = _preamble(program)
        self.assertEqual(base64.b64decode(namespace["BODY_B64"]).decode(), BODY)
        self.assertEqual(
            json.loads(base64.b64decode(namespace["HEADERS_B64"]).decode()), {}
        )
        self.assertEqual(
            program.split("\n", 2)[2], read_text(str(PROJECT_ROOT / SCRIPT))
        )
        compile(program, "<stdin>", "exec")

    def test_headers_ride_in_the_program(self):
        headers = {"Authorization": "Basic YWRtaW46czNjcg=="}

        namespace = _preamble(_program("", headers=headers))

        self.assertEqual(
            json.loads(base64.b64decode(namespace["HEADERS_B64"]).decode()), headers
        )

    def test_headers_must_map_strings_to_strings(self):
        with self.assertRaises(AnsibleError):
            _program("", headers={"X-Retry": 3})

    def test_empty_body_encodes_to_an_empty_string(self):
        preamble = _program("").split("\n", 1)[0]
        self.assertEqual(preamble, 'BODY_B64 = ""')

    def test_exactly_one_term_is_required(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables={"playbook_dir": str(PROJECT_ROOT)})

    def test_playbook_dir_is_required(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([BODY], variables={})


if __name__ == "__main__":
    unittest.main()
