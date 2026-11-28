from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import PROJECT_ROOT
from .release.test_host import load

PROOF = PROJECT_ROOT / "roles/web-app-semaphore/files/python/proof_of_release.py"
DENIED = {
    "unreachable": True,
    "msg": "Failed to connect to the host via ssh: admin@203.0.113.10: "
    "Permission denied (publickey).",
}


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.mod = load(PROOF, "proof_of_release")
        self.counts = {"kept": 2, "removed": dict.fromkeys(self.mod.BASE_COUNTS, 1)}
        self.done = {"rc": 0, "stdout": f"noise\n{json.dumps(self.counts)}\n"}
        monitored = {"kept": 2, "removed": dict.fromkeys(self.mod.COUNTS, 1)}
        self.monitored = {"rc": 0, "stdout": f"{json.dumps(monitored)}\n"}
        self.share_line = {"removed": dict.fromkeys(self.mod.SHARE_COUNTS, 1)}

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
            "helper refusal": (refused, 2, "refused", "no key"),
            "no result": ({}, 1, "failed", "ended without its result"),
            "monitoring outlived the release": (
                {
                    "rc": 1,
                    "failed": True,
                    "stdout": '{"failed": "the agent /usr/bin/check_mk_agent is still installed"}\n',
                },
                1,
                "failed",
                "failed: the agent /usr/bin/check_mk_agent is still installed",
            ),
            "failure line with a zero exit": (
                {"rc": 0, "stdout": '{"failed": "forged"}\n'},
                1,
                "failed",
                "ended without its result",
            ),
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

    def test_a_marked_rerun_on_a_released_host_goes_on_and_ends_released(self):
        self.assertEqual(
            self.mod.report("203.0.113.10", DENIED, [], marked=True), (0, None)
        )
        self.assertEqual(
            self.mod.report("203.0.113.10", DENIED, [DENIED, DENIED], marked=True),
            (0, {"host": "203.0.113.10", "released": True, "already": True}),
        )

    def test_a_login_refusal_without_the_marker_fails_loud(self):
        for proofs in ([], [DENIED, DENIED]):
            with self.subTest(proofs=proofs):
                code, line = self.mod.report(
                    "203.0.113.10", DENIED, proofs, share_line=self.share_line
                )
                self.assertEqual(code, 1)
                self.assertIn("refuses the platform key", line["failed"])
                self.assertIn("restore access or remove", line["failed"])

    def test_without_the_share_the_release_line_holds_the_base_counts_alone(self):
        code, line = self.report(self.done, DENIED)
        self.assertEqual(code, 0)
        self.assertEqual(set(line["removed"]), set(self.mod.BASE_COUNTS))
        self.assertNotIn("already", line)
        code, line = self.report(self.monitored, DENIED)
        self.assertEqual(code, 1)
        self.assertIn("ended without its result", line["failed"])
        code, line = self.mod.report(
            "203.0.113.10", self.done, [DENIED], share_line=self.share_line
        )
        self.assertEqual(code, 1)
        self.assertIn("ended without its result", line["failed"])

    def test_without_the_share_a_refused_login_is_a_release_without_result(self):
        code, line = self.report(DENIED, DENIED)
        self.assertEqual(code, 1)
        self.assertEqual(
            line,
            {
                "host": "203.0.113.10",
                "released": False,
                "failed": "the release on 203.0.113.10 ended without its result",
            },
        )

    def test_negative_control_a_rerun_the_key_still_logs_in_to_fails(self):
        for proof, text in (
            ({"rc": 0, "stdout": ""}, "still logs in"),
            ({}, "unproven"),
        ):
            with self.subTest(text=text):
                code, line = self.mod.report(
                    "203.0.113.10", DENIED, [DENIED, proof], marked=True
                )
                self.assertEqual(code, 1)
                self.assertIn(text, line["failed"])

    def test_the_share_counts_add_to_the_apply_counts(self):
        code, line = self.mod.report(
            "203.0.113.10", self.monitored, [DENIED], share_line=self.share_line
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            line["removed"],
            {
                name: 2 if name in self.mod.SHARE_COUNTS else 1
                for name in self.mod.COUNTS
            },
        )

    def test_the_check_goes_on_only_for_a_release_that_would_happen(self):
        refused = {"rc": 2, "failed": True, "stdout": '{"refused": "no key"}\n'}
        checked = {"rc": 0, "stdout": '{"checked": true}\n'}
        for result, expected in (
            (checked, (0, None)),
            (DENIED, (0, None)),
            (refused, (2, "refused")),
            (self.done, (1, "failed")),
            ({}, (1, "failed")),
        ):
            with self.subTest(result=result):
                code, line = self.mod.check("203.0.113.10", result)
                self.assertEqual(code, expected[0])
                if code == 0:
                    self.assertIsNone(line)
                else:
                    self.assertIn(expected[1], line)

    def test_the_share_step_is_judged_before_any_key_drop(self):
        line = {"removed": dict.fromkeys(self.mod.SHARE_COUNTS, 1)}
        proven = {"rc": 0, "stdout": f"{json.dumps(line)}\n"}
        refused = {"rc": 2, "failed": True, "stdout": '{"refused": "no key"}\n'}
        for result, expected in (
            (proven, (0, line)),
            (DENIED, (self.mod.REFUSED_LOGIN, None)),
            (refused, (2, "refused")),
            ({"rc": 0, "stdout": json.dumps(self.counts)}, (1, "failed")),
            (
                {"rc": 0, "stdout": '{"removed": {"federation_token": 1}}'},
                (1, "failed"),
            ),
        ):
            with self.subTest(result=result):
                code, got = self.mod.share("203.0.113.10", result)
                self.assertEqual(code, expected[0])
                if code in (0, self.mod.REFUSED_LOGIN):
                    self.assertEqual(got, expected[1])
                else:
                    self.assertIn(expected[1], got)

    def test_main_writes_a_proven_share_and_prints_no_line(self):
        line = {"removed": dict.fromkeys(self.mod.SHARE_COUNTS, 1)}
        with tempfile.TemporaryDirectory() as scratch:
            result = Path(scratch) / "share"
            out = Path(scratch) / "share.json"
            result.write_text(
                json.dumps({"rc": 0, "stdout": json.dumps(line)}), encoding="utf-8"
            )
            stdout = io.StringIO()
            code = self.mod.main(
                ["share", "203.0.113.10", str(result), str(out)], stdout
            )
            text = out.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
            written = json.loads(text)
        self.assertEqual((code, stdout.getvalue(), written), (0, "", line))

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

    def finish(self, recorded, status):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "result-lines"
            if recorded is not None:
                path.write_text(recorded, encoding="utf-8")
            stdout = io.StringIO()
            code = self.mod.main(
                ["finish", "203.0.113.10", str(path), str(status), "why"], stdout
            )
        return code, stdout.getvalue()

    def test_a_task_without_a_recorded_line_prints_the_line_of_its_status(self):
        for recorded in (None, "", '{"host": "203.0.113.10", "rel'):
            for status, code, field in (
                (2, 2, "refused"),
                (1, 1, "failed"),
                (143, 1, "failed"),
            ):
                with self.subTest(recorded=recorded, status=status):
                    result = self.finish(recorded, status)
                    self.assertEqual(result[0], code)
                    self.assertEqual(
                        json.loads(result[1]),
                        {"host": "203.0.113.10", "released": False, field: "why"},
                    )

    def test_a_recorded_line_is_printed_as_is_with_its_own_code(self):
        released = '{"host": "203.0.113.10", "kept": 1, "released": true}'
        refused = '{"host": "203.0.113.10", "refused": "x", "released": false}'
        failed = '{"failed": "x", "host": "203.0.113.10", "released": false}'
        for line, code in ((released, 0), (refused, 2), (failed, 1)):
            for status in (0, 1, 2, 129, 130, 143):
                with self.subTest(line=line, status=status):
                    self.assertEqual(
                        self.finish(f"{line}\n", status), (code, f"{line}\n")
                    )


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
