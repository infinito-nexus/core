import contextlib
import io
import json
import sys
import unittest
from itertools import product
from pathlib import Path

from .test_script import (
    ALICE,
    CONTAINER_BIN,
    LDAP,
    FakeRun,
    StubDirectory,
    Workspace,
    hook,
    load_module,
)

SLOT_TWO_ONLY = {"label=com.docker.swarm.service.name=s_w": "c3 s_w.2.taskid"}
ADMINISTRATORS = "cn=web-app-weblate-administrator,ou=roles,dc=example,dc=org"


def runner_module():
    """Returns:
    the ``hook_runner`` module, loaded the way the RBAC sync script imports it.
    """
    load_module()
    return sys.modules["hook_runner"]


def base_extra(config, hook, cid):
    """Return the extra environment the runner of the previous release gave a hook.

    Args:
        config: the parsed ``config.json``.
        hook: the parsed hook.
        cid: the container id.
    """
    if hook["kind"] != "host":
        return {}
    return {
        "RBAC_SYNC_CID": cid,
        "RBAC_SYNC_CONTAINER_BIN": config["container_bin"],
        "RBAC_SYNC_LDAP": json.dumps(config["ldap"]),
    }


class MembersEnvTests(unittest.TestCase):
    def setUp(self):
        self.mod = runner_module()
        self.members = {"administrator": [ALICE], "reviewer": []}

    def test_the_wildcard_passes_every_role(self):
        env = self.mod.members_env(hook(), self.members)
        self.assertEqual(json.loads(env["RBAC_MEMBERS"]), self.members)

    def test_a_field_passes_that_field_of_one_role(self):
        entries = [
            {"name": "ADMINS", "role": "administrator", "field": "username"},
            {"name": "REVIEWERS", "role": "reviewer", "field": ""},
        ]
        env = self.mod.members_env(hook(members_env=entries), self.members)
        self.assertEqual(json.loads(env["ADMINS"]), ["alice"])
        self.assertEqual(json.loads(env["REVIEWERS"]), [])


class ExecTests(unittest.TestCase):
    def setUp(self):
        self.mod = runner_module()

    def test_values_never_reach_argv(self):
        argv = self.mod.exec_argv(
            CONTAINER_BIN, hook(user="weblate"), "abc", {"SECRET": "s3cr3t"}
        )
        self.assertEqual(
            argv,
            [
                CONTAINER_BIN,
                "exec",
                "-i",
                "--user",
                "weblate",
                "-e",
                "SECRET",
                "abc",
                "weblate",
                "shell",
            ],
        )
        self.assertNotIn("s3cr3t", " ".join(argv))

    def test_compose_and_swarm_select_the_container_differently(self):
        run = FakeRun(
            {
                "name=^/weblate$": "c1",
                "label=com.docker.swarm.service.name=s_w": "c2 s_w.1.taskid",
            }
        )
        swarm = hook(container={"swarm_service": "s_w"})
        self.assertEqual(self.mod.local_container("/c", hook(), run, False), "c1")
        self.assertEqual(self.mod.local_container("/c", swarm, run, False), "c2")
        self.assertEqual(
            self.mod.local_container(
                "/c", hook(container={"name": "absent"}), run, False
            ),
            "",
        )

    def test_the_timer_only_runs_on_the_node_of_task_slot_one(self):
        run = FakeRun(SLOT_TWO_ONLY)

        for declared in ({}, {"any_slot": False}):
            swarm = hook(container={"swarm_service": "s_w"}, **declared)
            with self.subTest(declared=declared):
                self.assertEqual(self.mod.local_container("/c", swarm, run, False), "")
                self.assertEqual(self.mod.local_container("/c", swarm, run, True), "c3")

    def test_a_hook_that_declares_any_slot_runs_through_a_local_task_of_slot_two(self):
        swarm = hook(container={"swarm_service": "s_w"}, any_slot=True)

        self.assertEqual(
            self.mod.local_container("/c", swarm, FakeRun(SLOT_TWO_ONLY), False),
            "c3",
            "a hook registered with any_slot must run through the task of slot 2 on the timer's node",
        )


class TimerSlotTests(unittest.TestCase):
    def setUp(self):
        self.script = load_module()

    def timer_run(self, declared):
        """Run the timer on a node whose only task of ``s_w`` holds slot 2.

        Args:
            declared: the hook's ``any_slot`` entry, empty for a hook registered
                before the key existed.

        Returns:
            ``(exit code, stdout, ids of the containers the hook ran in)``.
        """
        directory = StubDirectory({ADMINISTRATORS: [("uid=alice", {"uid": ["alice"]})]})
        workspace = Workspace(
            [hook(container={"swarm_service": "s_w"}, **declared)], LDAP
        )
        run = FakeRun(SLOT_TWO_ONLY)
        stdout = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = self.script.main(
                    ["--directory", str(workspace.path)],
                    run=run,
                    connect=lambda uri: directory,
                    clock=lambda: 1000.0,
                )
        finally:
            workspace.close()
        return code, stdout.getvalue(), [argv[-3] for argv, _ in run.runs()]

    def test_the_timer_runs_a_hook_that_declares_any_slot_through_slot_two(self):
        code, stdout, ran = self.timer_run({"any_slot": True})

        self.assertEqual((code, ran), (0, ["c3"]))
        self.assertNotIn("SKIPPED", stdout)

    def test_the_timer_skips_slot_two_for_every_hook_without_the_opt_in(self):
        for declared in ({}, {"any_slot": False}):
            with self.subTest(declared=declared):
                code, stdout, ran = self.timer_run(declared)

                self.assertEqual((code, ran), (0, []))
                self.assertIn(
                    "[web-app-weblate] SKIPPED no running container on this node",
                    stdout,
                )


class HandoverTests(unittest.TestCase):
    def setUp(self):
        self.mod = runner_module()

    def test_every_hook_shape_gets_the_base_environment_or_only_its_members_file(self):
        for ldap, kind, attributes in product(
            (LDAP, None), ("host", "container"), (None, [], ["street"])
        ):
            shaped = hook(kind=kind, script="main.py" if kind == "host" else "")
            if attributes is not None:
                shaped["attributes"] = attributes
            config = {"container_bin": CONTAINER_BIN, "ldap": ldap}
            base = base_extra(config, shaped, "c1")
            expected = (
                {
                    **{n: v for n, v in base.items() if n != "RBAC_SYNC_LDAP"},
                    "RBAC_SYNC_MEMBERS_FILE": "members.json",
                }
                if kind == "host" and attributes is not None
                else base
            )
            with self.subTest(ldap=bool(ldap), kind=kind, attributes=attributes):
                _, _, extra = self.mod.invocation(
                    config, Path("hooks"), shaped, "c1", {}, "members.json"
                )
                self.assertEqual(extra, expected)


if __name__ == "__main__":
    unittest.main()
