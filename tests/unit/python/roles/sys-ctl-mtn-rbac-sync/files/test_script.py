import contextlib
import io
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "sys-ctl-mtn-rbac-sync" / "files" / "python" / "script.py"
)
LDAP_CLIENT_DIR = PROJECT_ROOT / "roles" / "svc-db-openldap" / "files" / "python"
LDAP = {
    "uri": "ldap://127.0.0.1:389",
    "users_dn": "ou=users,dc=example,dc=org",
    "roles_dn": "ou=roles,dc=example,dc=org",
    "attributes": {"id": "uid", "mail": "mail", "name": "cn", "member_of": "memberOf"},
}
ALICE = {"username": "alice", "email": "alice@example.org", "name": "Alice Liddell"}
CONTAINER_BIN = "/usr/bin/container"


def load_module():
    if str(LDAP_CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(LDAP_CLIENT_DIR))
    module = types.ModuleType("rbac_sync_script")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def hook(**overrides):
    base = {
        "application_id": "web-app-weblate",
        "kind": "container",
        "roles": ["administrator", "reviewer"],
        "container": {"name": "weblate"},
        "user": "",
        "argv": ["weblate", "shell"],
        "script": "",
        "env": {"WEBLATE_PROTECTED": "admin"},
        "members_env": [{"name": "RBAC_MEMBERS", "role": "*", "field": ""}],
        "skip_unchanged": False,
    }
    base.update(overrides)
    return base


class FakeRun:
    def __init__(self, containers, exit_codes=None, stdout=b"", stderr=b""):
        self.containers = containers
        self.exit_codes = exit_codes or {}
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[1] == "ps":
            found = self.containers.get(argv[3], "")
            return subprocess.CompletedProcess(argv, 0, stdout=found + "\n", stderr="")
        cid = kwargs["env"].get("RBAC_SYNC_CID") or argv[-3]
        return subprocess.CompletedProcess(
            argv, self.exit_codes.get(cid, 0), stdout=self.stdout, stderr=self.stderr
        )

    def runs(self):
        return [(argv, kwargs) for argv, kwargs in self.calls if argv[1] != "ps"]


class StubDirectory:
    def __init__(self, groups):
        self.groups = groups
        self.closed = False
        self.searches = []

    def search(self, base, scope, search_filter, attributes):
        self.searches.append((base, search_filter, attributes))
        for group_dn, entries in self.groups.items():
            if group_dn.encode() in search_filter:
                return entries
        return []

    def close(self):
        self.closed = True


class Workspace:
    def __init__(self, hooks, ldap, files=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        (self.path / "config.json").write_text(
            json.dumps(
                {
                    "container_bin": CONTAINER_BIN,
                    "timeout_seconds": 5,
                    "refresh_seconds": 100,
                    "ldap": ldap,
                }
            )
        )
        for item in hooks:
            hook_dir = self.path / "hooks" / item["application_id"]
            hook_dir.mkdir(parents=True)
            (hook_dir / "hook.json").write_text(json.dumps(item))
        for (application_id, name), content in (files or {}).items():
            (self.path / "hooks" / application_id / name).write_bytes(content)

    def hook_dir(self, application_id):
        return self.path / "hooks" / application_id

    def close(self):
        self.tmp.cleanup()


class DirectoryMembersTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_members_take_the_first_value_and_are_sorted(self):
        group = "cn=web-app-weblate-reviewer,ou=roles,dc=example,dc=org"
        directory = StubDirectory(
            {
                group: [
                    ("uid=bob", {"uid": ["bob"], "mail": ["bob@example.org"]}),
                    (
                        "uid=alice",
                        {
                            "uid": ["alice", "al"],
                            "mail": [ALICE["email"]],
                            "cn": [ALICE["name"]],
                        },
                    ),
                    ("uid=ghost", {"mail": ["ghost@example.org"]}),
                ]
            }
        )

        members = self.mod.directory_members(
            directory, LDAP, "web-app-weblate", "reviewer"
        )

        self.assertEqual(
            members,
            [ALICE, {"username": "bob", "email": "bob@example.org", "name": ""}],
        )
        self.assertEqual(directory.searches[0][0], LDAP["users_dn"])
        self.assertEqual(directory.searches[0][2], ["uid", "mail", "cn"])

    def test_the_users_role_lists_every_account_with_a_login(self):
        mod = self.mod
        captured = []

        class Directory:
            def search(self, base, scope, search_filter, attributes):
                captured.append(search_filter)
                return [("uid=carol", {"uid": ["carol"]})]

        members = mod.directory_members(
            Directory(), LDAP, "web-app-nextcloud", "@users"
        )

        self.assertEqual(members, [{"username": "carol", "email": "", "name": ""}])
        self.assertEqual(captured, [mod.present("uid")])


class MembersEnvTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
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
        self.mod = load_module()

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


class MainTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, argv, run, connect, now=1000.0):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = self.mod.main(argv, run=run, connect=connect, clock=lambda: now)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_an_unchanged_hook_is_skipped_until_its_refresh_is_due(self):
        group = "cn=web-app-weblate-administrator,ou=roles,dc=example,dc=org"
        directory = StubDirectory({group: [("uid=alice", {"uid": ["alice"]})]})
        workspace = Workspace([hook(skip_unchanged=True)], LDAP)
        run = FakeRun({"name=^/weblate$": "c1"})
        argv = ["--directory", str(workspace.path)]
        try:
            self.run_main(argv, run, lambda uri: directory, now=1000.0)
            _, skipped, _ = self.run_main(argv, run, lambda uri: directory, now=1050.0)
            self.run_main(argv, run, lambda uri: directory, now=1101.0)
        finally:
            workspace.close()

        self.assertIn("SKIPPED inputs unchanged", skipped)
        self.assertEqual(len(run.runs()), 2)

    def test_a_member_change_runs_an_unchanged_hook_at_once(self):
        group = "cn=web-app-weblate-administrator,ou=roles,dc=example,dc=org"
        before = StubDirectory({group: [("uid=alice", {"uid": ["alice"]})]})
        after = StubDirectory({group: [("uid=bob", {"uid": ["bob"]})]})
        workspace = Workspace([hook(skip_unchanged=True)], LDAP)
        run = FakeRun({"name=^/weblate$": "c1"})
        argv = ["--directory", str(workspace.path)]
        try:
            self.run_main(argv, run, lambda uri: before, now=1000.0)
            self.run_main(argv, run, lambda uri: after, now=1010.0)
        finally:
            workspace.close()

        self.assertEqual(len(run.runs()), 2)

    def test_a_failed_run_is_retried_on_the_next_interval(self):
        workspace = Workspace([hook(skip_unchanged=True)], LDAP)
        failing = FakeRun({"name=^/weblate$": "c1"}, exit_codes={"c1": 1})
        argv = ["--directory", str(workspace.path)]
        try:
            self.run_main(argv, failing, lambda uri: StubDirectory({}), now=1000.0)
            self.run_main(argv, failing, lambda uri: StubDirectory({}), now=1010.0)
        finally:
            workspace.close()

        self.assertEqual(len(failing.runs()), 2)

    def test_a_hook_without_skip_runs_every_interval(self):
        workspace = Workspace([hook(skip_unchanged=False)], LDAP)
        run = FakeRun({"name=^/weblate$": "c1"})
        argv = ["--directory", str(workspace.path)]
        try:
            self.run_main(argv, run, lambda uri: StubDirectory({}), now=1000.0)
            self.run_main(argv, run, lambda uri: StubDirectory({}), now=1010.0)
        finally:
            workspace.close()

        self.assertEqual(len(run.runs()), 2)

    def test_the_timer_pipes_a_container_hook_with_the_directory_members(self):
        group = "cn=web-app-weblate-administrator,ou=roles,dc=example,dc=org"
        directory = StubDirectory({group: [("uid=alice", {"uid": ["alice"]})]})
        workspace = Workspace(
            [hook(script="script")],
            LDAP,
            {("web-app-weblate", "script"): b"print('CHANGED')"},
        )
        run = FakeRun({"name=^/weblate$": "c1"}, stdout=b"CHANGED alice\n")
        try:
            code, stdout, _ = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: directory
            )
        finally:
            workspace.close()

        self.assertEqual(code, 0)
        self.assertIn("[web-app-weblate] CHANGED alice", stdout)
        argv, kwargs = run.runs()[0]
        self.assertEqual(argv[:3], [CONTAINER_BIN, "exec", "-i"])
        self.assertEqual(kwargs["input"], b"print('CHANGED')")
        self.assertEqual(kwargs["env"]["WEBLATE_PROTECTED"], "admin")
        self.assertEqual(
            json.loads(kwargs["env"]["RBAC_MEMBERS"])["administrator"][0]["username"],
            "alice",
        )
        self.assertNotIn("admin", " ".join(argv))
        self.assertTrue(directory.closed)

    def test_a_host_hook_runs_its_script_beside_its_modules_with_the_container_id(self):
        host_hook = hook(
            application_id="web-app-mattermost",
            kind="host",
            argv=[],
            script="main.py",
            container={"name": "mattermost"},
        )
        workspace = Workspace([host_hook], LDAP)
        run = FakeRun({"name=^/mattermost$": "c9"})
        try:
            code, _, _ = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: StubDirectory({})
            )
            hook_dir = workspace.hook_dir("web-app-mattermost")
        finally:
            workspace.close()

        self.assertEqual(code, 0)
        argv, kwargs = run.runs()[0]
        self.assertEqual(argv, [sys.executable, str(hook_dir / "main.py")])
        self.assertEqual(kwargs["cwd"], str(hook_dir))
        self.assertEqual(kwargs["input"], b"")
        self.assertEqual(kwargs["env"]["RBAC_SYNC_CID"], "c9")
        self.assertEqual(kwargs["env"]["RBAC_SYNC_CONTAINER_BIN"], CONTAINER_BIN)
        self.assertEqual(json.loads(kwargs["env"]["RBAC_SYNC_LDAP"]), LDAP)
        self.assertIn("RBAC_MEMBERS", kwargs["env"])

    def test_a_hook_without_a_local_container_is_skipped(self):
        workspace = Workspace([hook()], LDAP)
        run = FakeRun({})
        try:
            code, stdout, _ = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: StubDirectory({})
            )
        finally:
            workspace.close()

        self.assertEqual(code, 0)
        self.assertIn("SKIPPED", stdout)
        self.assertEqual(run.runs(), [])

    def test_the_timer_skips_a_hook_whose_application_is_paused(self):
        with tempfile.TemporaryDirectory() as instance:
            marker = Path(instance) / ".app-control-state"
            marker.write_text("stopped\n")
            workspace = Workspace([hook(paused_marker=str(marker))], LDAP)
            run = FakeRun({"name=^/weblate$": "c1"})
            try:
                code, stdout, _ = self.run_main(
                    ["--directory", str(workspace.path)],
                    run,
                    lambda uri: StubDirectory({}),
                )
            finally:
                workspace.close()

        self.assertEqual(code, 0)
        self.assertIn("[web-app-weblate] SKIPPED paused by app-control", stdout)
        self.assertEqual(run.calls, [])

    def test_a_started_application_keeps_its_hook_running(self):
        with tempfile.TemporaryDirectory() as instance:
            marker = Path(instance) / ".app-control-state"
            marker.write_text("started\n")
            workspace = Workspace([hook(paused_marker=str(marker))], LDAP)
            run = FakeRun({"name=^/weblate$": "c1"})
            try:
                self.run_main(
                    ["--directory", str(workspace.path)],
                    run,
                    lambda uri: StubDirectory({}),
                )
            finally:
                workspace.close()

        self.assertEqual(len(run.runs()), 1)

    def test_a_hook_without_a_marker_is_not_paused(self):
        self.assertFalse(self.mod.paused(hook()))
        self.assertFalse(self.mod.paused(hook(paused_marker="")))

    def test_one_failing_hook_fails_the_run_but_not_the_others(self):
        other = hook(application_id="web-app-zammad", container={"name": "zammad"})
        workspace = Workspace([hook(), other], LDAP)
        run = FakeRun(
            {"name=^/weblate$": "c1", "name=^/zammad$": "c2"}, exit_codes={"c1": 3}
        )
        try:
            code, _, stderr = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: StubDirectory({})
            )
        finally:
            workspace.close()

        self.assertEqual(code, 1)
        self.assertEqual(len(run.runs()), 2)
        self.assertIn("FAILED hooks: web-app-weblate", stderr)

    def test_a_hook_that_times_out_does_not_stop_the_others(self):
        other = hook(application_id="web-app-zammad", container={"name": "zammad"})
        workspace = Workspace([hook(), other], LDAP)
        base = FakeRun({"name=^/weblate$": "c1", "name=^/zammad$": "c2"})

        def run(argv, **kwargs):
            if argv[1] == "exec" and "c1" in argv:
                raise subprocess.TimeoutExpired(argv, 5)
            return base(argv, **kwargs)

        try:
            code, _, stderr = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: StubDirectory({})
            )
        finally:
            workspace.close()

        self.assertEqual(code, 1)
        self.assertEqual(len(base.runs()), 1)
        self.assertIn("TimeoutExpired", stderr)

    def test_without_a_directory_the_timer_does_nothing(self):
        workspace = Workspace([hook()], None)
        run = FakeRun({"name=^/weblate$": "c1"})
        try:
            code, stdout, _ = self.run_main(
                ["--directory", str(workspace.path)], run, None
            )
        finally:
            workspace.close()

        self.assertEqual(code, 0)
        self.assertIn("SKIPPED no directory", stdout)
        self.assertEqual(run.calls, [])

    def test_the_deploy_passes_its_own_members_and_needs_the_container(self):
        members = {"administrator": [ALICE], "reviewer": []}
        workspace = Workspace([hook()], None)
        members_file = workspace.path / "members.json"
        members_file.write_text(json.dumps(members))
        found = FakeRun({"name=^/weblate$": "c1"})
        missing = FakeRun({})
        try:
            argv = [
                "--directory",
                str(workspace.path),
                "--only",
                "web-app-weblate",
                "--members-file",
                str(members_file),
            ]
            ok_code, _, _ = self.run_main(argv, found, None)
            missing_code, _, missing_err = self.run_main(argv, missing, None)
        finally:
            workspace.close()

        self.assertEqual(ok_code, 0)
        self.assertEqual(json.loads(found.runs()[0][1]["env"]["RBAC_MEMBERS"]), members)
        self.assertEqual(missing_code, 1)
        self.assertIn("no running container", missing_err)

    def test_an_unknown_application_is_an_error(self):
        workspace = Workspace([hook()], LDAP)
        try:
            code, _, stderr = self.run_main(
                ["--directory", str(workspace.path), "--only", "web-app-absent"],
                FakeRun({}),
                None,
            )
        finally:
            workspace.close()

        self.assertEqual(code, 1)
        self.assertIn("no hook registered for web-app-absent", stderr)

    def test_members_file_without_only_is_refused(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            self.mod.main(["--directory", "/x", "--members-file", "/y"])


if __name__ == "__main__":
    unittest.main()
