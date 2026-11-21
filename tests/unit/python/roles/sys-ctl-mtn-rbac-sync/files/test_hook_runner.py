import json
import sys
import unittest
from itertools import product
from pathlib import Path

from .test_script import ALICE, CONTAINER_BIN, LDAP, FakeRun, hook, load_module


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
        run = FakeRun({"label=com.docker.swarm.service.name=s_w": "c3 s_w.2.taskid"})
        swarm = hook(container={"swarm_service": "s_w"})

        self.assertEqual(self.mod.local_container("/c", swarm, run, False), "")
        self.assertEqual(self.mod.local_container("/c", swarm, run, True), "c3")


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
