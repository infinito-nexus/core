from __future__ import annotations

import io
import json
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from unittest import mock

from tests.utils.openbao_stub import OpenBaoStub

from . import PROJECT_ROOT
from ._semaphore_fake import WORKSPACE_ID

HELPER = PROJECT_ROOT / "roles/web-app-semaphore/files/python/workspace_ssh_key.py"
ROLE = f"ws-{WORKSPACE_ID}"
JWT = "task-jwt"
TOKEN = "bao-token"
KEY = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE=\n-----END OPENSSH PRIVATE KEY-----"
OWN = {"openbao": f"tenant/ws-{WORKSPACE_ID}/ssh#private_key"}


def load_helper():
    """Returns:
    The module ``files/python/workspace_ssh_key.py``.
    """
    spec = spec_from_file_location("workspace_ssh_key", str(HELPER))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WorkspaceSshKeyTests(unittest.TestCase):
    def setUp(self):
        self.helper = load_helper()
        self.bao = OpenBaoStub(
            {TOKEN: [f"tenant/ws-{WORKSPACE_ID}/"]}, {(ROLE, JWT): TOKEN}
        )
        self.addCleanup(self.bao.close)
        self.bao.put(f"tenant/ws-{WORKSPACE_ID}/ssh", {"private_key": KEY})
        self.env = {
            "WORKSPACE": WORKSPACE_ID,
            "BAO_ADDR": self.bao.addr,
            "BAO_CACERT": self.bao.cafile,
            "BAO_ROLE": ROLE,
            "SEMAPHORE_JWT": JWT,
        }

    def run_helper(self, reference):
        stdout = io.StringIO()
        stdin = io.StringIO(json.dumps({"WORKSPACE_SSH_KEY": reference}))
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = self.helper.main(stdin, stdout, self.env)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_the_key_of_the_workspace_goes_to_stdout_only(self):
        code, stdout, stderr = self.run_helper(OWN)
        self.assertEqual((code, stdout, stderr), (0, f"{KEY}\n", ""))

    def test_a_reference_outside_the_workspace_is_refused_before_any_read(self):
        cases = {
            "another workspace": {
                "openbao": "tenant/ws-11111111-2222-4333-8444-555555555555/ssh#private_key"
            },
            "another mount": {"openbao": f"platform/ws-{WORKSPACE_ID}/ssh#private_key"},
            "a prefix twin": {"openbao": f"tenant/ws-{WORKSPACE_ID}x/ssh#private_key"},
            "a plain key": KEY,
            "no key": None,
        }
        for name, reference in cases.items():
            with self.subTest(name):
                self.bao.requests.clear()
                code, stdout, stderr = self.run_helper(reference)
                self.assertEqual((code, stdout), (1, ""))
                self.assertTrue(stderr.startswith("workspace_ssh_key.py: "), stderr)
                self.assertNotIn("PRIVATE KEY", stderr)
                self.assertEqual(self.bao.requests, [])

    def test_negative_control_without_the_path_check_a_foreign_key_is_read(self):
        foreign = "11111111-2222-4333-8444-555555555555"
        self.bao.tokens[TOKEN].append(f"tenant/ws-{foreign}/")
        self.bao.put(f"tenant/ws-{foreign}/ssh", {"private_key": KEY})
        self.helper.key_reference = lambda host_vars, workspace: (
            self.helper.parse_reference(
                host_vars["WORKSPACE_SSH_KEY"], "WORKSPACE_SSH_KEY"
            )
        )
        code, stdout, _ = self.run_helper(
            {"openbao": f"tenant/ws-{foreign}/ssh#private_key"}
        )
        self.assertEqual((code, stdout), (0, f"{KEY}\n"))


if __name__ == "__main__":
    unittest.main()
