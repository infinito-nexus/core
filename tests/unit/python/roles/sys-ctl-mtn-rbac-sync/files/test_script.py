import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from itertools import product
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

SCRIPT = (
    PROJECT_ROOT / "roles" / "sys-ctl-mtn-rbac-sync" / "files" / "python" / "script.py"
)
LDAP_MODULES_DIR = (
    PROJECT_ROOT / "roles" / "svc-db-openldap" / "files" / "python" / "ldap"
)
DEPLOYED_MODULES = {
    "ldap_client": LDAP_MODULES_DIR / "client.py",
    "ldap_mailbox": LDAP_MODULES_DIR / "mailbox.py",
    "backup_maintenance": PROJECT_ROOT
    / "roles/svc-bkp-volume-2-local/files/python/baudolo/maintenance.py",
    "mailbox_seed": SCRIPT.parent / "mailbox_seed.py",
}
LDAP = {
    "uri": "ldap://127.0.0.1:389",
    "users_dn": "ou=users,dc=example,dc=org",
    "roles_dn": "ou=roles,dc=example,dc=org",
    "attributes": {
        "id": "uid",
        "mail": "mail",
        "name": "cn",
        "member_of": "memberOf",
        "uuid": "entryUUID",
    },
}
ALICE_UUID = "7f9c1a2e-3b4d-4e5f-8a9b-0c1d2e3f4a5b"
ALICE = {
    "username": "alice",
    "email": "alice@example.org",
    "name": "Alice Liddell",
    "uuid": ALICE_UUID,
}
CONTAINER_BIN = "/usr/bin/container"
DIRECTORY = "svc-db-openldap"
BACKUP_UNTIL = "1970-01-01T01:00:00+00:00"
MAILBOX = {
    "bind_dn": "cn=administrator,dc=example,dc=org",
    "bind_password": "s3cr3t-bind",
    "domain": "example.org",
    "object_class": "infinitoMailboxUser",
}


def load_module():
    for name, path in DEPLOYED_MODULES.items():
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
            exec(
                compile(read_text(str(path)), str(path), "exec"),
                sys.modules[name].__dict__,
            )
    module = types.ModuleType("rbac_sync_script")
    exec(compile(read_text(str(SCRIPT)), str(SCRIPT), "exec"), module.__dict__)
    return module


def backup_window(applications, until):
    """Return a maintenance document of svc-bkp-volume-2-local that started at the epoch.

    Args:
        applications: the application ids the backup stops.
        until: the RFC 3339 end of the window; the tests run at 1000 s past the epoch.
    """
    return {
        "applications": applications,
        "started": "1970-01-01T00:00:00+00:00",
        "until": until,
    }


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


class MailboxDirectory:
    def __init__(self, entries, bind_code=0, add_codes=None):
        self.entries = entries
        self.bind_code = bind_code
        self.add_codes = add_codes or {}
        self.binds = []
        self.searches = []
        self.added = []
        self.closed = False

    def bind(self, dn, password):
        self.binds.append((dn, password))
        return self.bind_code

    def search(self, base, scope, search_filter, attributes):
        self.searches.append((base, search_filter, attributes))
        return self.entries

    def add_values(self, dn, additions):
        self.added.append((dn, additions))
        return self.add_codes.get(dn, 0)

    def close(self):
        self.closed = True


def connections(*directories):
    remaining = list(directories)
    return lambda uri: remaining.pop(0)


class Workspace:
    def __init__(self, hooks, ldap, files=None, mailbox=None, config_extra=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        (self.path / "config.json").write_text(
            json.dumps(
                {
                    "container_bin": CONTAINER_BIN,
                    "directory_host": True,
                    "maintenance_file": str(self.path / "backup.json"),
                    "timeout_seconds": 5,
                    "refresh_seconds": 100,
                    "ldap": ldap,
                    **(config_extra or {}),
                }
            )
        )
        if mailbox is not None:
            (self.path / "mailbox.json").write_text(json.dumps(mailbox))
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
                            "entryuuid": [ALICE_UUID],
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
            [
                ALICE,
                {"username": "bob", "email": "bob@example.org", "name": "", "uuid": ""},
            ],
        )
        self.assertEqual(directory.searches[0][0], LDAP["users_dn"])
        self.assertEqual(directory.searches[0][2], ["uid", "mail", "cn", "entryUUID"])

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

        self.assertEqual(
            members, [{"username": "carol", "email": "", "name": "", "uuid": ""}]
        )
        self.assertEqual(captured, [mod.present("uid")])


class RoleGroupTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_a_role_name_is_a_role_of_the_hooks_application(self):
        self.assertEqual(
            self.mod.role_group("web-app-erpnext", "manager"),
            ("web-app-erpnext", "manager"),
        )

    def test_a_group_path_names_a_role_of_another_application(self):
        for path in (
            "/roles/web-app-consumer/auditor",
            "roles/web-app-consumer/auditor/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.mod.role_group("web-app-erpnext", path),
                    ("web-app-consumer", "auditor"),
                )

    def test_a_group_path_searches_the_group_of_its_application(self):
        group = "cn=web-app-consumer-auditor,ou=roles,dc=example,dc=org"
        directory = StubDirectory(
            {group: [("uid=alice", {"uid": ["alice"], "mail": [ALICE["email"]]})]}
        )

        members = self.mod.directory_members(
            directory,
            LDAP,
            *self.mod.role_group("web-app-erpnext", "/roles/web-app-consumer/auditor"),
        )

        self.assertEqual(
            members,
            [{"username": "alice", "email": ALICE["email"], "name": "", "uuid": ""}],
        )

    def test_a_path_of_another_shape_fails(self):
        for path in (
            "/roles/web-app-consumer",
            "/roles/web-app-consumer/t.example/auditor",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.mod.role_group("web-app-erpnext", path)


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

    def test_a_hook_value_that_is_no_string_reaches_the_process_as_text(self):
        workspace = Workspace(
            [hook(env={"WEBLATE_PORT": 8080, "WEBLATE_LDAP_SYNC": True})], LDAP
        )
        run = FakeRun({"name=^/weblate$": "c1"})
        try:
            code, _, _ = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: StubDirectory({})
            )
        finally:
            workspace.close()

        self.assertEqual(code, 0)
        env = run.runs()[0][1]["env"]
        self.assertEqual(
            (env["WEBLATE_PORT"], env["WEBLATE_LDAP_SYNC"]),
            ("8080", "true"),
            "hook.json keeps the native type of a templated value such as a port, "
            "and subprocess refuses any environment value that is not a string",
        )

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

    def run_against_socket(self, path, mailbox, directory_host=True, backup=None):
        """Run the timer against a real ``ldapi`` URI with a hook and its container.

        Args:
            path: the socket path the URI names.
            mailbox: the content of ``mailbox.json``, or None for none.
            directory_host: whether the node is a host of svc-db-openldap.
            backup: the backup's maintenance document, or None for none.

        Returns:
            The exit code, stdout, stderr and the stand-in for ``subprocess.run``.
        """
        uri = "ldapi://" + str(path).replace("/", "%2F")
        workspace = Workspace(
            [hook()],
            {**LDAP, "uri": uri},
            mailbox=mailbox,
            config_extra={"directory_host": directory_host},
        )
        if backup is not None:
            (workspace.path / "backup.json").write_text(json.dumps(backup))
        run = FakeRun({"name=^/weblate$": "c1"})
        try:
            code, stdout, stderr = self.run_main(
                ["--directory", str(workspace.path)], run, self.mod.Connection
            )
        finally:
            workspace.close()
        return code, stdout, stderr, run

    def missing_socket(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name, "run", "ldapi")

    def test_a_node_outside_svc_db_openldap_skips_in_one_line(self):
        path = self.missing_socket()

        code, stdout, stderr, run = self.run_against_socket(
            path, None, directory_host=False
        )

        self.assertEqual((code, stderr, run.calls), (0, "", []))
        self.assertEqual(
            stdout.splitlines(),
            [
                (
                    f"SKIPPED no directory socket at {path} on this node: "
                    "OpenLDAP runs on another node, no hook runs here"
                )
            ],
        )

    def test_a_host_of_svc_db_openldap_without_the_socket_fails_in_one_line(self):
        path = self.missing_socket()
        uri = "ldapi://" + str(path).replace("/", "%2F")
        other = backup_window(["web-app-openbao"], until=BACKUP_UNTIL)
        expired = backup_window([DIRECTORY], until="1970-01-01T00:10:00+00:00")
        for mailbox, backup in product((None, MAILBOX), (None, other, expired)):
            with self.subTest(mailbox=mailbox is not None, backup=backup):
                code, stdout, stderr, run = self.run_against_socket(
                    path, mailbox, backup=backup
                )

                self.assertEqual((code, stdout, run.calls), (1, "", []))
                self.assertEqual(
                    stderr.splitlines(),
                    [
                        (
                            f"FAILED directory {uri} unreachable: SocketMissingError: "
                            f"no directory socket at {path} on this node"
                        )
                    ],
                )

    def test_a_host_of_svc_db_openldap_skips_while_the_backup_holds_it(self):
        path = self.missing_socket()
        backup = backup_window([DIRECTORY, "web-app-openbao"], until=BACKUP_UNTIL)
        for mailbox in (None, MAILBOX):
            with self.subTest(mailbox=mailbox is not None):
                code, stdout, stderr, run = self.run_against_socket(
                    path, mailbox, backup=backup
                )

                self.assertEqual((code, stderr, run.calls), (0, "", []))
                self.assertEqual(
                    stdout.splitlines(),
                    [
                        (
                            f"SKIPPED no directory socket at {path} on this node: "
                            f"the backup stopped {DIRECTORY}, no hook runs here"
                        )
                    ],
                )

    def test_an_unreadable_mailbox_seed_is_one_line_and_the_hooks_still_run(self):
        group = "cn=web-app-weblate-administrator,ou=roles,dc=example,dc=org"
        directory = StubDirectory({group: [("uid=alice", {"uid": ["alice"]})]})
        workspace = Workspace([hook()], LDAP)
        (workspace.path / "mailbox.json").write_text("{not json")
        run = FakeRun({"name=^/weblate$": "c1"})
        try:
            code, _, stderr = self.run_main(
                ["--directory", str(workspace.path)], run, lambda uri: directory
            )
        finally:
            workspace.close()

        self.assertEqual(code, 1)
        self.assertEqual(len(stderr.splitlines()), 1)
        self.assertTrue(stderr.startswith("[mailbox] FAILED JSONDecodeError"))
        self.assertEqual(len(run.runs()), 1)

    def test_a_socket_that_does_not_answer_fails_the_run_in_one_line(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name, "ldapi")
        stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        stale.bind(str(path))
        stale.close()
        for mailbox in (None, MAILBOX):
            with self.subTest(mailbox=mailbox is not None):
                code, stdout, stderr, run = self.run_against_socket(path, mailbox)

                self.assertEqual((code, stdout, run.calls), (1, "", []))
                self.assertEqual(len(stderr.splitlines()), 1)
                self.assertIn("unreachable: ConnectionRefusedError", stderr)

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


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def run_main(self, argv, connect, mailbox=MAILBOX, hooks=(), config_extra=None):
        workspace = Workspace(
            list(hooks), LDAP, mailbox=mailbox, config_extra=config_extra
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.mod.main(
                    ["--directory", str(workspace.path), *argv],
                    run=FakeRun({}),
                    connect=connect,
                    clock=lambda: 1000.0,
                )
        finally:
            workspace.close()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_an_account_without_mail_gets_its_mailbox_and_the_class(self):
        seeder = MailboxDirectory(
            [
                ("uid=alice,ou=users", {"uid": ["alice"], "objectclass": ["person"]}),
                (
                    "uid=bob,ou=users",
                    {"uid": ["bob"], "mail": ["bob@elsewhere.org"], "objectclass": []},
                ),
                (
                    "uid=carol,ou=users",
                    {
                        "uid": ["carol"],
                        "mail": [],
                        "objectclass": ["person", "InfinitoMailboxUser"],
                    },
                ),
            ]
        )

        code, stdout, stderr = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 0)
        self.assertEqual(
            seeder.added,
            [
                (
                    "uid=alice,ou=users",
                    {
                        "objectClass": ["infinitoMailboxUser"],
                        "mail": ["alice@example.org"],
                    },
                ),
                ("uid=carol,ou=users", {"mail": ["carol@example.org"]}),
            ],
        )
        self.assertEqual(seeder.binds, [(MAILBOX["bind_dn"], MAILBOX["bind_password"])])
        self.assertEqual(seeder.searches[0][0], LDAP["users_dn"])
        self.assertEqual(seeder.searches[0][2], ["uid", "mail", "objectClass"])
        self.assertIn(
            "[mailbox] CHANGED uid=alice,ou=users mail=alice@example.org", stdout
        )
        self.assertNotIn(MAILBOX["bind_password"], stdout + stderr)
        self.assertTrue(seeder.closed)

    def test_the_seed_runs_before_the_hooks_read_the_members(self):
        order = []
        seeder = MailboxDirectory([("uid=alice,ou=users", {"uid": ["alice"]})])
        hooks_directory = StubDirectory({})
        seeder.add_values = lambda dn, additions: order.append("seed") or 0
        hooks_directory.search = lambda *args: order.append("members") or []

        self.run_main([], connections(seeder, hooks_directory), hooks=[hook()])

        self.assertEqual(order[0], "seed")
        self.assertIn("members", order)

    def test_an_entry_whose_rdn_key_sits_beside_its_username_seeds_the_username(self):
        seeder = MailboxDirectory([("uid=dave,ou=users", {"uid": ["dave", "david"]})])

        code, _, _ = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 0)
        self.assertEqual(
            seeder.added,
            [
                (
                    "uid=dave,ou=users",
                    {
                        "objectClass": ["infinitoMailboxUser"],
                        "mail": ["david@example.org"],
                    },
                )
            ],
        )

    def test_an_entry_without_one_login_fails_the_run_but_not_the_others(self):
        seeder = MailboxDirectory(
            [
                ("uid=dave,ou=users", {"uid": ["david", "davy"]}),
                ("uid=alice,ou=users", {"uid": ["alice"]}),
            ]
        )

        code, _, stderr = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 1)
        self.assertIn("holds 2 values of uid", stderr)
        self.assertEqual([dn for dn, _ in seeder.added], ["uid=alice,ou=users"])

    def test_a_refused_bind_fails_the_run_and_writes_nothing(self):
        seeder = MailboxDirectory([("uid=alice,ou=users", {"uid": ["alice"]})], 49)

        code, _, stderr = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 1)
        self.assertIn("bind answered result code 49", stderr)
        self.assertEqual(seeder.added, [])
        self.assertTrue(seeder.closed)

    def test_an_unreachable_directory_fails_the_run_in_one_line(self):
        attempts = []

        def connect(uri):
            attempts.append(uri)
            raise ConnectionRefusedError("refused")

        code, stdout, stderr = self.run_main([], connect, hooks=[hook()])

        self.assertEqual((code, stdout, attempts), (1, "", [LDAP["uri"]]))
        self.assertEqual(
            stderr.splitlines(),
            [
                f"FAILED directory {LDAP['uri']} unreachable: ConnectionRefusedError: refused"
            ],
        )

    def test_a_concurrent_seed_is_no_failure(self):
        seeder = MailboxDirectory(
            [("uid=alice,ou=users", {"uid": ["alice"]})],
            add_codes={"uid=alice,ou=users": 20},
        )

        code, stdout, _ = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 0)
        self.assertIn("[mailbox] SKIPPED uid=alice,ou=users", stdout)

    def test_any_other_modify_result_fails_the_run(self):
        seeder = MailboxDirectory(
            [("uid=alice,ou=users", {"uid": ["alice"]})],
            add_codes={"uid=alice,ou=users": 50},
        )

        code, _, stderr = self.run_main([], connections(seeder, StubDirectory({})))

        self.assertEqual(code, 1)
        self.assertIn("modify answered result code 50", stderr)

    def test_without_the_mailbox_policy_the_timer_never_binds(self):
        hooks_directory = MailboxDirectory([("uid=alice,ou=users", {"uid": ["alice"]})])

        code, _, _ = self.run_main([], connections(hooks_directory), mailbox=None)

        self.assertEqual(code, 0)
        self.assertEqual(hooks_directory.binds, [])
        self.assertEqual(hooks_directory.added, [])

    def test_only_the_mailbox_file_of_the_applied_layout_enables_the_seed(self):
        hooks_directory = MailboxDirectory([("uid=alice,ou=users", {"uid": ["alice"]})])

        code, _, _ = self.run_main(
            [],
            connections(hooks_directory),
            mailbox=None,
            config_extra={"mailbox": MAILBOX},
        )

        self.assertEqual(code, 0)
        self.assertEqual(hooks_directory.binds, [])
        self.assertEqual(hooks_directory.added, [])

    def test_a_run_of_one_hook_never_seeds(self):
        hooks_directory = MailboxDirectory([])

        self.run_main(
            ["--only", "web-app-weblate"], connections(hooks_directory), hooks=[hook()]
        )

        self.assertEqual(hooks_directory.binds, [])


if __name__ == "__main__":
    unittest.main()
