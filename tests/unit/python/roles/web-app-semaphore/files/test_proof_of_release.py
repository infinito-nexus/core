from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT
from .test_release_host import load

PROOF = PROJECT_ROOT / "roles/web-app-semaphore/files/python/proof_of_release.py"
DENIED = {
    "unreachable": True,
    "msg": "Failed to connect to the host via ssh: admin@203.0.113.10: "
    "Permission denied (publickey).",
}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(PROOF, "proof_of_release")
        self.counts = {"kept": 2, "removed": dict.fromkeys(self.mod.COUNTS, 1)}
        self.done = {"rc": 0, "stdout": f"noise\n{json.dumps(self.counts)}\n"}

    def report(self, release, proof=None):
        return self.mod.report(
            "203.0.113.10", release, [] if proof is None else [proof]
        )

    def test_every_proof_login_has_to_be_refused(self):
        let_in = {"rc": 0, "stdout": ""}
        code, line = self.mod.report("203.0.113.10", self.done, [DENIED, let_in])
        self.assertEqual(code, 1)
        self.assertIn("still logs in", line["failed"])
        code, line = self.mod.report("203.0.113.10", self.done, [DENIED, {}])
        self.assertEqual(code, 1)
        self.assertIn("unproven", line["failed"])
        self.assertEqual(
            self.mod.report("203.0.113.10", self.done, [DENIED, DENIED])[0], 0
        )

    def test_a_proven_release_ends_with_its_counts(self):
        self.assertEqual(self.report(self.done), (0, None))
        self.assertEqual(
            self.report(self.done, DENIED),
            (0, {"host": "203.0.113.10", "released": True, **self.counts}),
        )

    def test_a_login_after_the_release_fails_it(self):
        for proof in ({"rc": 0, "stdout": ""}, {"rc": 1, "failed": True}):
            with self.subTest(proof=proof):
                code, line = self.report(self.done, proof)
                self.assertEqual(code, 1)
                self.assertFalse(line["released"])
                self.assertIn("still logs in", line["failed"])

    def test_an_unproven_release_fails(self):
        for proof in ({}, {"unreachable": True, "msg": "Connection timed out"}):
            with self.subTest(proof=proof):
                code, line = self.report(self.done, proof)
                self.assertEqual(code, 1)
                self.assertIn("unproven", line["failed"])

    def test_refusals_and_failures_of_the_release_call(self):
        refused = {"rc": 2, "failed": True, "stdout": '{"refused": "no key"}\n'}
        cases = {
            "released already": (DENIED, 2, "refused", "refuses the task agent key"),
            "helper refusal": (refused, 2, "refused", "no key"),
            "no result": ({}, 1, "failed", "ended without its result"),
            "forged counts": (
                {"rc": 0, "stdout": '{"kept": -1, "removed": {}}\n'},
                1,
                "failed",
                "ended without its result",
            ),
        }
        for case, (release, code, kind, text) in cases.items():
            with self.subTest(case):
                got, line = self.report(release, DENIED)
                self.assertEqual(got, code)
                self.assertEqual(set(line), {"host", "released", kind}, line)
                self.assertIn(text, line[kind])

    def test_main_reads_the_tree_files(self):
        with tempfile.TemporaryDirectory() as scratch:
            release = Path(scratch) / "release"
            proof = Path(scratch) / "proof"
            release.write_text(json.dumps(self.done), encoding="utf-8")
            proof.write_text(json.dumps(DENIED), encoding="utf-8")
            stdout = io.StringIO()
            code = self.mod.main(
                ["report", "203.0.113.10", str(release), str(proof)], stdout
            )
        self.assertEqual(code, 0)
        (line,) = stdout.getvalue().splitlines()
        self.assertTrue(json.loads(line)["released"])


INVENTORY_SSH = {
    "ansible_ssh_args": "-o ControlMaster=auto -o ControlPath=/tmp/cp",
    "ansible_ssh_private_key_file": "/nonexistent/inventory_key",
    "ansible_ssh_common_args": "-i /nonexistent/common_key",
    "ansible_ssh_extra_args": "-i /nonexistent/extra_key",
    "ansible_password": "inventory-password",
    "ansible_connection": "local",
}
SEEN = [*sorted(INVENTORY_SSH), "ansible_user"]


class ProofVarsTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(PROOF, "proof_of_release")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        host_vars = " ".join(f"{k}='{v}'" for k, v in INVENTORY_SSH.items())
        (self.root / "inventory").write_text(
            f"[all]\n203.0.113.10 ansible_user=admin {host_vars}\n", encoding="utf-8"
        )

    def resolved(self, user, extra):
        """Args:
        user: the ``--user`` of ``proof-vars``.
        extra: whether the proof vars go in as extra vars.

        Returns:
            The value of every name of ``SEEN`` as ansible resolves it for the host.
        """
        vars_file = self.root / f"proof-{user}.json"
        stdout = io.StringIO()
        argv = ["proof-vars", str(self.root)] + (
            [] if user is None else ["--user", user]
        )
        self.assertEqual(self.mod.main(argv, stdout), 0)
        vars_file.write_text(stdout.getvalue(), encoding="utf-8")
        tree = self.root / f"tree-{user}-{extra}"
        command = [
            str(Path(sys.executable).with_name("ansible")),
            "203.0.113.10",
            "-i",
            str(self.root / "inventory"),
            "-t",
            str(tree),
            "-m",
            "ansible.builtin.debug",
            "-a",
            "msg={{ [" + ", ".join(SEEN) + "] }}",
        ] + (["-e", f"@{vars_file}"] if extra else [])
        subprocess.run(command, check=True, capture_output=True, cwd=self.root)
        result = tree / "203.0.113.10"
        shown = json.loads(
            result.read_text(  # nocheck: cache-read tempdir
                encoding="utf-8"
            )
        )["msg"]
        return dict(zip(SEEN, shown, strict=True))

    def test_the_proof_vars_outrank_every_inventory_ssh_setting(self):
        for user, login in ((None, "admin"), ("root", "root")):
            with self.subTest(user=user):
                seen = self.resolved(user, extra=True)
                self.assertEqual(seen["ansible_user"], login)
                self.assertEqual(seen["ansible_connection"], "ssh")
                self.assertEqual(
                    seen["ansible_ssh_private_key_file"], str(self.root / "agent.pub")
                )
                for name in (
                    "ansible_ssh_common_args",
                    "ansible_ssh_extra_args",
                    "ansible_password",
                ):
                    self.assertEqual(seen[name], "", name)
                args = seen["ansible_ssh_args"]
                for option in (
                    "ControlPath=none",
                    "IdentitiesOnly=yes",
                    "BatchMode=yes",
                    "PasswordAuthentication=no",
                    f"UserKnownHostsFile={self.root / 'known_hosts'}",
                ):
                    self.assertIn(option, args)
                self.assertNotIn("ControlMaster=auto", args)

    def test_negative_control_without_the_extra_vars_the_inventory_wins(self):
        seen = self.resolved(None, extra=False)
        self.assertEqual({k: seen[k] for k in INVENTORY_SSH}, INVENTORY_SSH)


if __name__ == "__main__":
    unittest.main()
