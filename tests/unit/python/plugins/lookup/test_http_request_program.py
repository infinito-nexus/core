"""Unit tests for the http_request_program lookup plugin."""

from __future__ import annotations

import base64
import json
import unittest

from ansible.errors import AnsibleError

from plugins.lookup.http_request_program import SCRIPT, LookupModule

from . import PROJECT_ROOT

BODY = json.dumps({"password": "s3cr\"et'\n"})


def _program(body: str) -> str:
    return LookupModule().run([body], variables={"playbook_dir": str(PROJECT_ROOT)})[0]


class TestHttpRequestProgram(unittest.TestCase):
    def test_program_carries_the_body_and_the_script(self):
        program = _program(BODY)

        preamble, script = program.split("\n", 1)
        namespace: dict = {}
        exec(preamble, namespace)
        self.assertEqual(base64.b64decode(namespace["BODY_B64"]).decode(), BODY)
        self.assertEqual(script, (PROJECT_ROOT / SCRIPT).read_text())
        compile(program, "<stdin>", "exec")

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
