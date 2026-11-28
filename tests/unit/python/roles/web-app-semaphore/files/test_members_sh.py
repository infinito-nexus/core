from __future__ import annotations

import shutil
import sys
import unittest
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location

from utils.cache.files import PROJECT_ROOT, read_text

from ._script_shims import ScriptRunner
from ._semaphore_fake import (
    PYTHON_DIR,
    SCRIPTS_DIR,
    SUSPENSION_REFUSALS,
    WORKSPACE_ID,
    FakeSemaphore,
)

KEYCLOAK_TESTS = "tests.unit.python.roles.web-app-keycloak.files.workspace"
STATE_LIB = """import itertools
import os
import pickle
import sys
from importlib import import_module
from pathlib import Path

FAKES = (
    "tests.unit.python.roles.web-app-keycloak.files.workspace._workspace_fake",
    "tests.unit.python.roles.web-app-semaphore.files._semaphore_fake",
)
REAL = ("", "/roles/web-app-keycloak/files/python", "/roles/web-app-keycloak/files/python/workspace")


def fakes():
    for path in REAL:
        sys.path.insert(0, os.environ["STUB_ROOT"] + path)
    return import_module(FAKES[0]).FakeKeycloak, import_module(FAKES[1]).FakeSemaphore


def dump(path, fake):
    state = {k: v for k, v in vars(fake).items() if k != "error"}
    if "_ids" in state:
        state["_ids"] = next(fake._ids)
    Path(path).write_bytes(pickle.dumps(state))


def restore(path, cls, **attrs):
    state = pickle.loads(Path(path).read_bytes())
    if "_ids" in state:
        state["_ids"] = itertools.count(state["_ids"])
    fake = cls.__new__(cls)
    vars(fake).update(state, **attrs)
    return fake


def fail(step):
    if os.environ.get("STUB_FAIL") == step:
        print("stub failure at the " + step + " step", file=sys.stderr)
        raise SystemExit(1)
"""
KEYCLOAK_WRAPPER = """import os
import sys

sys.path.insert(0, os.environ["STUB_LIB"])
import stub_state

keycloak_fake, _ = stub_state.fakes()
import members

if sys.argv[1] == "settle":
    stub_state.fail("membership")
kc = stub_state.restore(os.environ["STUB_KEYCLOAK"], keycloak_fake)
members.service_account = lambda env: kc
try:
    code = members.main(sys.argv)
finally:
    stub_state.dump(os.environ["STUB_KEYCLOAK"], kc)
raise SystemExit(code)
"""
SEMAPHORE_WRAPPER = """import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from types import SimpleNamespace

sys.path.insert(0, os.environ["STUB_LIB"])
import stub_state

keycloak_fake, semaphore_fake = stub_state.fakes()
spec = spec_from_file_location("semaphore_members", os.environ["STUB_SEMAPHORE_MEMBERS"])
real = module_from_spec(spec)
spec.loader.exec_module(real)
stub_state.fail("role" if sys.argv[1] == "remove" else "sync")
api = stub_state.restore(os.environ["STUB_SEMAPHORE"], semaphore_fake, error=real.SyncError)
kc = stub_state.restore(os.environ["STUB_KEYCLOAK"], keycloak_fake)
import workspaces

workspaces.service_account = lambda env: kc
real.connect = lambda env: SimpleNamespace(close=lambda: None)
real.mint = lambda connection, env: "stub"
real.revoke = lambda connection, token: None
real.workspace_project = lambda connection, workspace: int(os.environ["STUB_PROJECT"])
real.Api = lambda root, token: api
try:
    code = real.main(sys.argv[1:], dict(os.environ))
finally:
    stub_state.dump(os.environ["STUB_SEMAPHORE"], api)
raise SystemExit(code)
"""
FAILS_AFTER = {"group": "role", "role": "membership", "membership": "sync"}

MEMBER = "11111111-2222-4333-8444-555555555555"
KEY = "66666666-7777-4888-8999-000000000000"
REFUSAL = f'{{"workspace":"{WORKSPACE_ID}","refused":"absent"}}'
KEYCLOAK_STUB = """import os, sys
if sys.argv[1] == "prepare" and os.environ.get("STUB_PREPARE_EXIT") == "3":
    print(os.environ["STUB_REFUSAL"])
    sys.exit(3)
print("stub " + sys.argv[1])
"""
SEMAPHORE_STUB = """import os, sys
print("semaphore " + sys.argv[1] + " suspended=" + os.environ["WORKSPACE_SUSPENDED"])
"""
SUSPENSION_CHECK = "require WORKSPACE_SUSPENDED '^(true|false)$'\n"
ACTION_INPUTS = {
    "sync": {},
    "list": {},
    "add": {"WORKSPACE_MEMBER": MEMBER},
    "remove": {"WORKSPACE_MEMBER": MEMBER},
    "invite": {"INVITE_KEY": KEY},
    "uninvite": {"INVITE_KEY": KEY},
    "role": {"WORKSPACE_MEMBER": MEMBER, "WORKSPACE_ROLE": "Viewer"},
}


class MembersScriptTests(unittest.TestCase):
    def setUp(self):
        self.runner = self.new_runner()

    def new_runner(self):
        """Returns:
        A script runner whose core tree holds the Keycloak member stub.
        """
        runner = ScriptRunner()
        self.addCleanup(runner.cleanup)
        stub = (
            runner.src / "roles" / "web-app-keycloak" / "files" / "python" / "workspace"
        )
        stub.mkdir(parents=True)
        (stub / "members.py").write_text(KEYCLOAK_STUB, encoding="utf-8")
        return runner

    def run_members(self, env, args=(), script="members.sh"):
        merged = {
            "WORKSPACE": WORKSPACE_ID,
            "WORKSPACE_SUSPENDED": "false",
            "KC_CLIENT_SECRET": "clientsecret",
            "STUB_REFUSAL": REFUSAL,
            **env,
        }
        return self.runner.run(
            script, {k: v for k, v in merged.items() if v is not None}, args
        )

    def plant(self, members_sh):
        """Args:
        members_sh: the text of the members.sh to run.

        Returns:
            Its path in a planted ``files`` tree, beside lib.sh, with a
            ``python/semaphore_members.py`` stub that prints its action and
            WORKSPACE_SUSPENDED.
        """
        files = self.runner.tmp / "planted"
        directory = files / "shell" / "repository"
        directory.mkdir(parents=True)
        python = files / "python"
        python.mkdir()
        shutil.copy(SCRIPTS_DIR / "lib.sh", directory / "lib.sh")
        (python / "semaphore_members.py").write_text(SEMAPHORE_STUB, encoding="utf-8")
        script = directory / "members.sh"
        script.write_text(members_sh, encoding="utf-8")
        return str(script)

    def test_members_sh_refuses_each_malformed_input(self):
        cases = [
            ({"MEMBERS_ACTION": "promote"}, (), "MEMBERS_ACTION is malformed"),
            (
                {"MEMBERS_ACTION": "sync", "WORKSPACE_MEMBER": MEMBER},
                (),
                "WORKSPACE_MEMBER is not taken",
            ),
            ({"MEMBERS_ACTION": "add"}, (), "WORKSPACE_MEMBER is missing"),
            (
                {"MEMBERS_ACTION": "sync", "WORKSPACE": "WS-1"},
                (),
                "WORKSPACE is malformed",
            ),
            (
                {"MEMBERS_ACTION": "remove", "WORKSPACE_MEMBER": "alice"},
                (),
                "WORKSPACE_MEMBER is malformed",
            ),
            (
                {"MEMBERS_ACTION": "invite", "INVITE_KEY": "alice@example.org"},
                (),
                "INVITE_KEY is malformed",
            ),
            (
                {
                    "MEMBERS_ACTION": "invite",
                    "INVITE_KEY": KEY,
                    "WORKSPACE_ROLE": "Owner",
                },
                (),
                "WORKSPACE_ROLE is not taken",
            ),
            (
                {
                    "MEMBERS_ACTION": "role",
                    "WORKSPACE_MEMBER": MEMBER,
                    "WORKSPACE_ROLE": "Root",
                },
                (),
                "WORKSPACE_ROLE is malformed",
            ),
            (
                {"MEMBERS_ACTION": "sync", "WORKSPACE_SUSPENDED": None},
                (),
                "WORKSPACE_SUSPENDED is missing",
            ),
            (
                {"MEMBERS_ACTION": "sync", "WORKSPACE_SUSPENDED": "yes"},
                (),
                "WORKSPACE_SUSPENDED is malformed",
            ),
            ({"MEMBERS_ACTION": "sync"}, ("extra",), "unexpected argument 'extra'"),
        ]
        for env, args, message in cases:
            with self.subTest(f"{env} {args}"):
                run = self.run_members(env, args)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(f"members.sh: {message}", run.stderr)

    def test_a_missing_or_malformed_suspension_refuses_before_any_call(self):
        for action, inputs in ACTION_INPUTS.items():
            for value, reason in SUSPENSION_REFUSALS:
                with self.subTest(action=action, value=value):
                    run = self.run_members(
                        {
                            "MEMBERS_ACTION": action,
                            **inputs,
                            "WORKSPACE_SUSPENDED": value,
                        }
                    )
                    self.assertEqual(run.returncode, 2, run.stderr)
                    self.assertIn(
                        f"members.sh: WORKSPACE_SUSPENDED is {reason}", run.stderr
                    )
                    self.assertEqual(run.stdout, "")

    def test_negative_control_without_the_check_keycloak_runs(self):
        text = read_text(str(SCRIPTS_DIR / "members.sh"))
        self.assertIn(SUSPENSION_CHECK, text)
        script = self.plant(text.replace(SUSPENSION_CHECK, ""))
        run = self.run_members(
            {"MEMBERS_ACTION": "list", "WORKSPACE_SUSPENDED": "yes"}, script=script
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, "stub list\n")

    def test_members_sh_hands_the_flag_to_the_semaphore_sync(self):
        script = self.plant(read_text(str(SCRIPTS_DIR / "members.sh")))
        for value in ("true", "false"):
            with self.subTest(value=value):
                run = self.run_members(
                    {"MEMBERS_ACTION": "sync", "WORKSPACE_SUSPENDED": value},
                    script=script,
                )
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(
                    f"semaphore sync suspended={value}", run.stdout.splitlines()
                )

    def list_leftovers(self, script=None):
        """Args:
        script: the members.sh to run, the role's own by default.

        Returns:
            What ``list`` leaves in its temporary directory.
        """
        scratch = self.runner.tmp / "list-tmp"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir()
        env = {"MEMBERS_ACTION": "list", "TMPDIR": str(scratch)}
        run = self.run_members(env, script=script) if script else self.run_members(env)
        self.assertEqual(run.returncode, 0, run.stderr)
        return sorted(path.name for path in scratch.rglob("*"))  # nocheck: project-walk

    def test_list_leaves_no_client_secret_behind(self):
        self.assertEqual(self.list_leftovers(), [])

    def test_negative_control_an_exec_list_keeps_the_client_secret(self):
        text = read_text(str(SCRIPTS_DIR / "members.sh"))
        call = 'python3 "${keycloak}/workspace/members.py" list\n\texit 0'
        self.assertIn(call, text)
        script = self.plant(
            text.replace(call, 'exec python3 "${keycloak}/workspace/members.py" list')
        )
        self.assertIn("client-secret", self.list_leftovers(script))

    def test_a_refused_prepare_stops_with_its_line_last(self):
        run = self.run_members(
            {
                "MEMBERS_ACTION": "remove",
                "WORKSPACE_MEMBER": MEMBER,
                "STUB_PREPARE_EXIT": "3",
            }
        )
        self.assertEqual(run.returncode, 3)
        self.assertEqual(run.stdout.splitlines()[-1], REFUSAL)

    def remove_world(self):
        """Returns:
        ``run``, which runs members.sh remove of a member against the real
        Keycloak and Semaphore member scripts over pickled fakes and takes the
        step that fails, and ``state``, which reads the fakes back.
        """
        keycloak = import_module(f"{KEYCLOAK_TESTS}.test_members")
        fake_keycloak = import_module(f"{KEYCLOAK_TESTS}._workspace_fake")
        lib = self.runner.tmp / "lib"
        lib.mkdir()
        (lib / "stub_state.py").write_text(STATE_LIB, encoding="utf-8")
        spec = spec_from_file_location("stub_state", lib / "stub_state.py")
        stub_state = module_from_spec(spec)
        spec.loader.exec_module(stub_state)
        python = self.runner.bin / "python3"
        python.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8"
        )
        python.chmod(0o755)
        workspace = self.runner.src.joinpath(
            "roles", "web-app-keycloak", "files", "python", "workspace", "members.py"
        )
        workspace.write_text(KEYCLOAK_WRAPPER, encoding="utf-8")
        script = self.plant(read_text(str(SCRIPTS_DIR / "members.sh")))
        (self.runner.tmp / "planted" / "python" / "semaphore_members.py").write_text(
            SEMAPHORE_WRAPPER, encoding="utf-8"
        )
        harness = keycloak.Harness()
        self.addCleanup(harness.dir.cleanup)
        harness.task("add", WORKSPACE_MEMBER=keycloak.ALICE)
        harness.member(keycloak.BOB, "Operator")
        harness.kc.users[keycloak.BOB]["groups"] = [fake_keycloak.SIGN_IN]
        api = FakeSemaphore(Exception)
        project_id = api.add_project(f"ws-{keycloak.WS}")["id"]
        for username in ("store", "alice", "bob"):
            api.call("POST", "/users", {"username": username, "admin": False})
        ids = {user["username"]: user["id"] for user in api.users}
        api.members[project_id].update(
            {
                ids["store"]: "manager",
                ids["alice"]: "task_runner",
                ids["bob"]: "task_runner",
            }
        )
        paths = {
            "STUB_KEYCLOAK": str(self.runner.tmp / "keycloak.pickle"),
            "STUB_SEMAPHORE": str(self.runner.tmp / "semaphore.pickle"),
        }
        stub_state.dump(paths["STUB_KEYCLOAK"], harness.kc)
        stub_state.dump(paths["STUB_SEMAPHORE"], api)
        env = {
            **{
                k: v
                for k, v in harness.env("remove", keycloak.WS).items()
                if k.startswith("KC_") and not k.endswith("_FILE")
            },
            **paths,
            "MEMBERS_ACTION": "remove",
            "WORKSPACE": keycloak.WS,
            "WORKSPACE_MEMBER": keycloak.BOB,
            "SEMAPHORE_API_URL": "http://semaphore.invalid/api",
            "SEMAPHORE_STORE_USERNAME": "store",
            "STUB_ROOT": str(PROJECT_ROOT),
            "STUB_LIB": str(lib),
            "STUB_PROJECT": str(project_id),
            "STUB_SEMAPHORE_MEMBERS": str(PYTHON_DIR / "semaphore_members.py"),
        }

        def run(failing=None):
            return self.run_members({**env, "STUB_FAIL": failing}, script=script)

        def state():
            kc = stub_state.restore(paths["STUB_KEYCLOAK"], fake_keycloak.FakeKeycloak)
            semaphore = stub_state.restore(paths["STUB_SEMAPHORE"], FakeSemaphore)
            harness.kc = kc
            return {
                "groups": harness.roles(keycloak.BOB)
                + kc.users[keycloak.BOB]["groups"],
                "role": semaphore.members[project_id].get(ids["bob"]),
                "member": keycloak.BOB in kc.memberships[harness.org],
                "owner": (
                    harness.roles(keycloak.ALICE),
                    semaphore.members[project_id][ids["alice"]],
                ),
                "writes": len(kc.writes) + len(semaphore.writes),
            }

        return run, state

    def test_remove_finishes_after_a_failure_at_each_step(self):
        left = {
            "group": {"groups": [], "role": "task_runner", "member": True},
            "role": {"groups": [], "role": None, "member": True},
            "membership": {"groups": [], "role": None, "member": False},
        }
        done = {"groups": [], "role": None, "member": False}
        for after, failing in FAILS_AFTER.items():
            with self.subTest(after=after):
                self.runner = self.new_runner()
                run, state = self.remove_world()
                failed = run(failing)
                self.assertEqual(failed.returncode, 1, failed.stderr)
                self.assertIn(f"stub failure at the {failing} step", failed.stderr)
                partial = state()
                self.assertEqual(
                    {k: partial[k] for k in left[after]}, left[after], failed.stdout
                )
                second = run()
                self.assertEqual(second.returncode, 0, second.stderr)
                finished = state()
                self.assertEqual({k: finished[k] for k in done}, done, second.stdout)
                self.assertEqual(finished["owner"], (["Owner"], "task_runner"))
                third = run()
                self.assertEqual(third.returncode, 0, third.stderr)
                self.assertEqual(state()["writes"], finished["writes"], third.stdout)


if __name__ == "__main__":
    unittest.main()
