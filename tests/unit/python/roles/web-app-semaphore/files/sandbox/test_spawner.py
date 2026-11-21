from __future__ import annotations

import ast
import contextlib
import errno
import importlib
import io
import json
import os
import queue
import shutil
import signal
import socket
import stat
import sys
import threading
import types
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

FAKES = importlib.import_module("..provision._fake_provision", __package__)
PROCESSES = importlib.import_module("..provision._fake_spawner", __package__)
ROLE = FAKES.ROLE
harness_directory = FAKES.harness_directory
load = FAKES.load
held = PROCESSES.held
inode = PROCESSES.inode
spawner = load("sandbox.spawner")
admission = spawner.admission
hardening = spawner.hardening
privileged = spawner.privileged
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
VARIABLES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
SERVICE = "provision-runner"
RUNNER = VOLUMES["semaphore_provision_runner_token"]["uid"]
FIRST = VARIABLES["SEMAPHORE_SANDBOX_UID_BASE"]
FAKE_SPAWNER = Path(FAKES.__file__).with_name("_fake_spawner.py")
PYTHON = FAKES.FILES / "python"
PACKAGE = "provision"
SIGNAL = "signal"
SIGNAL_RECEIVERS = {"signal", "pause", "sigwait", "sigwaitinfo", "set_wakeup_fd"}
SPAWNER = "sandbox.spawner"
PRIVILEGED = "provision.privileged"
ADMISSION = "provision.admission"
THREAD_ROOTS = (
    (SPAWNER, "Spawner"),
    (SPAWNER, "Run"),
    (SPAWNER, "accept"),
    (SPAWNER, "vital"),
    (PRIVILEGED, "Privileges"),
)
THREAD_REACH = {
    *THREAD_ROOTS,
    (PRIVILEGED, "reap"),
    (PRIVILEGED, "reap_round"),
    (ADMISSION, "admitted"),
    (ADMISSION, "value_admitted"),
    ("provision.opentofu", "admitted_arguments"),
    ("provision.session", "is_encryption"),
    ("provision.sandbox", "Channel"),
    ("provision.sandbox", "task_relative"),
}
TOFU = spawner.sandbox.TOFU
TOFU_PATH = Path(VARIABLES["SEMAPHORE_SANDBOX_TOFU"])
JOIN_SECONDS = 30
NO_THREAD = "can't start new thread"


def target_of(volume):
    (mount,) = [m for m in VOLUMES[volume]["mounts"] if m["service"] == SERVICE]
    return str(mount["target"])


LAYOUT_ENV = {
    hardening.RUNNER_UID: str(RUNNER),
    hardening.UID_BASE: str(VARIABLES["SEMAPHORE_SANDBOX_UID_BASE"]),
    hardening.UID_COUNT: str(VARIABLES["SEMAPHORE_SANDBOX_UID_COUNT"]),
    hardening.ROOT: target_of("semaphore_provision_sandboxes"),
    hardening.TMP: target_of("semaphore_runner_tmp"),
    hardening.SHARED: ":".join(VARIABLES["SEMAPHORE_SANDBOX_SHARED"]),
    hardening.TOFU_BINARY: VARIABLES["SEMAPHORE_SANDBOX_TOFU"],
    hardening.CA_FILE: "",
    hardening.BAO_ADDRESS: "https://openbao.example.org",
}
SELF_SIGNED_CA = Path("/etc/infinito/ca.crt")
CLI_CONFIG = spawner.session.OPENTOFU / "tofurc"
BAO = LAYOUT_ENV[hardening.BAO_ADDRESS]
WORKSPACE = "ws-4f1c2a3e"
SECRET_NAME = "OS_APPLICATION_CREDENTIAL_SECRET"
LOCAL_REMOTES = ("local", "LOCAL", " Local", "local:")
HOST_REMOTES = ("target", "local-site")
PINNED = admission.pinned_values({}, CLI_CONFIG, SELF_SIGNED_CA, BAO)


def source_of(module):
    """Args:
        module: a dotted module of ``files/python``, e.g. ``sandbox.spawner``.

    Returns:
        Its source.
    """
    return read_text(str(PYTHON / f"{module.replace('.', '/')}.py"))


def imported(tree):
    """Args:
        tree: a parsed module.

    Returns:
        ``{"modules": {alias: module}, "names": {alias: (module, name)},
        "signal": {alias}, "receivers": {alias}}``: the modules and names it
        imports from the ``provision`` package, the aliases of the ``signal``
        module, and the aliases of a function of :data:`SIGNAL_RECEIVERS`
        imported from it, ``from signal import signal`` among them.
    """
    found = {"modules": {}, "names": {}, "signal": set(), "receivers": set()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found["signal"] |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name == SIGNAL
            }
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            bound = alias.asname or alias.name
            if node.module == SIGNAL and alias.name in SIGNAL_RECEIVERS:
                found["receivers"].add(bound)
            elif node.module == PACKAGE:
                found["modules"][bound] = f"{PACKAGE}.{alias.name}"
            elif str(node.module).startswith(f"{PACKAGE}."):
                found["names"][bound] = (node.module, alias.name)
    return found


def signal_receivers(node, imports):
    """Args:
        node: a parsed class or function.
        imports: :func:`imported` of its module.

    Returns:
        The line of every call in it that installs or awaits a signal; Python
        runs a handler in the main thread alone, so a spawner thread must make
        none.
    """
    lines = []
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        function = call.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in imports["signal"]
            and function.attr in SIGNAL_RECEIVERS
        ) or (isinstance(function, ast.Name) and function.id in imports["receivers"]):
            lines.append(call.lineno)
    return lines


def threaded_nodes(planted):
    """Args:
        planted: ``{module: source}`` that replaces the source of a module of
            ``files/python``, as a negative control plants it.

    Returns:
        ``{(module, name): (node, imports)}`` of every class and function a
        thread of the spawner runs: the classes and the ``accept`` loop of
        :data:`THREAD_ROOTS`, every function of ``privileged`` and
        ``admission``, and transitively every class and function of the
        ``provision`` package any of them names, such as
        :func:`opentofu.admitted_arguments`, :func:`session.is_encryption` and
        the functions of ``sandbox``; ``serve`` and ``main`` themselves run in
        the main thread.
    """
    trees, imports = {}, {}

    def tree(module):
        if module not in trees:
            trees[module] = ast.parse(planted.get(module) or source_of(module))
            imports[module] = imported(trees[module])
        return trees[module]

    def definition(module, name):
        kinds = (ast.FunctionDef, ast.ClassDef)
        found = [
            n for n in tree(module).body if isinstance(n, kinds) and n.name == name
        ]
        return found[0] if found else None

    def named(module, node):
        for item in ast.walk(node):
            if isinstance(item, ast.Attribute) and isinstance(item.value, ast.Name):
                target = imports[module]["modules"].get(item.value.id)
                if target is not None:
                    yield target, item.attr
            elif isinstance(item, ast.Name):
                yield imports[module]["names"].get(item.id, (module, item.id))

    pending = [
        (module, name, definition(module, name)) for module, name in THREAD_ROOTS
    ]
    pending += [
        (module, node.name, node)
        for module in (PRIVILEGED, ADMISSION)
        for node in tree(module).body
        if isinstance(node, ast.FunctionDef)
    ]
    reached = {}
    while pending:
        module, name, node = pending.pop()
        if node is None or (module, name) in reached:
            continue
        reached[(module, name)] = (node, imports[module])
        pending += [
            (target, attribute, definition(target, attribute))
            for target, attribute in named(module, node)
        ]
    return reached


def signal_findings(planted):
    """Args:
        planted: see :func:`threaded_nodes`.

    Returns:
        ``{module.name: [line]}`` of every threaded class or function that
        installs or awaits a signal.
    """
    found = {
        f"{module}.{name}": signal_receivers(node, module_imports)
        for (module, name), (node, module_imports) in threaded_nodes(planted).items()
    }
    return {name: lines for name, lines in found.items() if lines}


class TestThreadedSpawner(unittest.TestCase):
    def plant(self, module, *replacements):
        """Args:
            module: a dotted module of ``files/python``.
            replacements: ``(old, new)`` pairs, each ``old`` in its source.

        Returns:
            ``{module: planted source}``.
        """
        source = source_of(module)
        for old, new in replacements:
            self.assertIn(old, source)
            source = source.replace(old, new, 1)
        return {module: source}

    def test_the_threaded_spawner_never_installs_or_awaits_a_signal(self):
        self.assertLessEqual(THREAD_REACH, set(threaded_nodes({})))
        self.assertEqual(signal_findings({}), {})
        fake = ast.parse(read_text(str(FAKE_SPAWNER)))
        self.assertEqual(signal_receivers(fake, imported(fake)), [])

    def test_negative_control_a_handler_in_the_spawner_is_found(self):
        planted = self.plant(
            SPAWNER,
            (
                "    def finish(self, process):\n",
                "    def finish(self, process):\n        signal.signal(2, None)\n",
            ),
        )
        self.assertEqual(set(signal_findings(planted)), {f"{SPAWNER}.Run"})

    def test_negative_control_a_handler_in_a_privileged_function_is_found(self):
        planted = self.plant(
            PRIVILEGED,
            ("import time\n", "import time\nimport signal\n"),
            (
                "def waited(process):\n",
                "def waited(process):\n    signal.signal(17, None)\n",
            ),
        )
        self.assertEqual(set(signal_findings(planted)), {f"{PRIVILEGED}.waited"})

    def test_negative_control_a_handler_imported_by_name_is_found(self):
        planted = self.plant(
            PRIVILEGED,
            ("import time\n", "import time\nfrom signal import signal as install\n"),
            ("def reap():\n", "def reap():\n    install(17, None)\n"),
        )
        self.assertEqual(set(signal_findings(planted)), {f"{PRIVILEGED}.reap"})

    def test_negative_control_a_handler_reached_only_transitively_is_found(self):
        session = self.plant(
            "provision.session",
            ("import sys\n", "import signal\nimport sys\n"),
            (
                "    try:\n        document = json.loads(value)\n",
                "    signal.sigwait({2})\n    try:\n        document = json.loads(value)\n",
            ),
        )
        sandbox = self.plant(
            "provision.sandbox",
            ("import socket\n", "import signal\nimport socket\n"),
            (
                "    path = Path(value)\n",
                "    signal.set_wakeup_fd(-1)\n    path = Path(value)\n",
            ),
        )
        self.assertEqual(
            set(signal_findings(session | sandbox)),
            {"provision.session.is_encryption", "provision.sandbox.task_relative"},
        )


class TestLayout(unittest.TestCase):
    def test_the_spawner_reads_the_container_layout_from_the_role(self):
        container = hardening.layout(LAYOUT_ENV)
        self.assertEqual(container["runner"], RUNNER)
        self.assertEqual(str(container["root"]), LAYOUT_ENV[hardening.ROOT])
        self.assertEqual(str(container["tmp"]), LAYOUT_ENV[hardening.TMP])
        self.assertNotIn(RUNNER, container["uids"])
        shared = {str(path) for path in container["shared"]}
        self.assertEqual(shared, set(VARIABLES["SEMAPHORE_SANDBOX_SHARED"]))
        self.assertFalse(hardening.closed_mode(0o1777) & (stat.S_IWOTH | stat.S_ISVTX))

    def test_the_ca_is_optional_in_either_tls_mode(self):
        for ca, pinned in (("", None), (str(SELF_SIGNED_CA), str(SELF_SIGNED_CA))):
            with self.subTest(ca=ca):
                container = hardening.layout(LAYOUT_ENV | {hardening.CA_FILE: ca})
                values = admission.pinned_values(
                    {}, CLI_CONFIG, container["ca"], container["bao"]
                )
                self.assertEqual(values[admission.CA_NAME], pinned)
                entry = admission.programs(TOFU_PATH, admission.credentials(), values)
                admitted = admission.value_admitted(
                    admission.CA_NAME, str(SELF_SIGNED_CA), entry[TOFU], Path("/t")
                )
                self.assertEqual(admitted, bool(ca))

    def test_negative_control_a_required_ca_stops_the_default_tls_mode(self):
        with (
            mock.patch.object(
                hardening, "LAYOUT", (*hardening.LAYOUT, hardening.CA_FILE)
            ),
            self.assertRaisesRegex(SystemExit, "the role sets no SEMAPHORE_SANDBOX_CA"),
        ):
            hardening.layout(LAYOUT_ENV)

    def test_negative_control_a_layout_the_role_left_out_is_refused(self):
        for name in hardening.LAYOUT:
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(SystemExit, f"the role sets no {name}"),
            ):
                hardening.layout({k: v for k, v in LAYOUT_ENV.items() if k != name})


class FakeKernel:
    """Args:
    proc: the directory standing in for ``/proc``; each process is a
        ``<pid>/status`` file there, each IPC table a ``sysvipc`` file.
    """

    def __init__(self, proc):
        self.proc = proc
        self.groups = {}
        self.immortal = set()
        self.signals = []
        self.caller = None
        (proc / "sysvipc").mkdir(parents=True)
        for kind, column in spawner.sandbox.IPC_KINDS.items():
            (proc / "sysvipc" / kind).write_text(f"key {column} perms uid cuid\n")

    def spawn(self, pid, uid, group, immortal=False):
        entry = self.proc / str(pid)
        entry.mkdir()
        (entry / "status").write_text(
            f"Name:\tfake\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n"
        )
        self.groups[pid] = group
        if immortal:
            self.immortal.add(pid)

    def living(self):
        return [int(e.name) for e in self.proc.iterdir() if e.name.isdigit()]

    def end(self, pid):
        if pid not in self.immortal:
            shutil.rmtree(self.proc / str(pid))

    def kill(self, pid, signum):
        self.signals.append((self.caller, pid, signum))
        if pid == -1:
            targets = privileged.holders(self.caller, self.proc)
        elif pid < -1:
            targets = [p for p in self.living() if self.groups[p] == -pid]
        else:
            targets = [pid]
        for target in targets:
            self.end(target)

    def killpg(self, group, signum):
        self.signals.append((self.caller, -group, signum))
        for pid in self.living():
            if self.groups[pid] == group:
                self.end(pid)

    def ipc(self, kind, identifier, uid):
        with (self.proc / "sysvipc" / kind).open("a") as table:
            table.write(f"0 {identifier} 600 {uid} {uid}\n")

    def ipc_remover(self, kind):
        def remove(identifier, *_arguments):
            table = self.proc / "sysvipc" / kind
            raw = table.read_bytes()  # nocheck: cache-read tempdir
            lines = raw.decode().splitlines()
            kept = [lines[0]] + [
                line for line in lines[1:] if line.split()[1] != str(identifier)
            ]
            table.write_text("\n".join(kept) + "\n")
            return 0

        return remove


def kernel_privileges(kernel, libc):
    """Args:
        kernel: the :class:`FakeKernel` the helpers act on.
        libc: the C library the ``ipc`` helper removes objects with.

    Returns:
        The real :class:`privileged.Privileges`; only its helper processes run
        in this process, as their uid, against ``kernel``, a helper that
        raises ending non-zero as its process would, and only ``chown`` is
        left out of ``prepare``.
    """

    class KernelPrivileges(privileged.Privileges):
        def helper(self, uid, *argv, group=None):
            kernel.caller = uid
            with (
                mock.patch.object(spawner.os, "kill", kernel.kill),
                mock.patch.object(spawner.os, "killpg", kernel.killpg),
                mock.patch.object(spawner.os, "getuid", return_value=uid),
                mock.patch.object(spawner.ctypes, "CDLL", return_value=libc),
                mock.patch.object(spawner, "PROC", kernel.proc),
            ):
                try:
                    code = spawner.main([str(privileged.ENTRY), *argv])
                except OSError:
                    code = 1
            if code != 0:
                raise spawner.sandbox.SandboxError(f"the {argv[0]} helper ended {code}")

        def prepare(self, entries):
            for path, _owner, _group, mode in entries:
                path.mkdir(mode=0o700)
                path.chmod(mode)

    return KernelPrivileges(RUNNER, kernel.proc, kernel.proc.parent, ())


def chowned(owners):
    """Args:
        owners: ``{path: uid}`` of the planted entries, as a ``chown`` by
            root would leave them.

    Returns:
        :func:`sandbox.owner` that answers from ``owners`` by inode, so it
        holds for an entry reached by a directory descriptor too, and from
        the real file system for every other entry.
    """
    by_inode = {}
    for path, uid in owners.items():
        info = os.lstat(path)
        by_inode[(info.st_dev, info.st_ino)] = uid
    return lambda info: by_inode.get((info.st_dev, info.st_ino), info.st_uid)


def following(*tops):
    """Args:
    tops: as for :func:`privileged.remove_owned`, which it plants: it removes
        what a link of the uid points to.
    """
    for top in tops:
        for directory, _names, files in os.walk(top):  # nocheck: project-walk
            for name in files:
                target = (Path(directory) / name).resolve()
                if privileged.owner(os.lstat(target)) == spawner.os.getuid():
                    target.unlink()


def chmod_through_links(*tops):
    """Args:
    tops: as for :func:`privileged.remove_owned`, which it plants: it opens up
        every directory a name below ``tops`` reaches, through a link too.
    """
    for top in tops:
        for directory, names, _files in os.walk(top):  # nocheck: project-walk
            for name in names:
                path = Path(directory) / name
                if privileged.owner(path.stat()) == spawner.os.getuid():
                    path.chmod(0o700)


def ignoring_owner(*tops):
    """Args:
    tops: as for :func:`privileged.remove_owned`, which it plants: it removes
        every entry, whoever owns it.
    """
    for top in tops:
        for entry in Path(top).iterdir():
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()


def leftover_findings(opened, owners):
    """Args:
        opened: the uids :meth:`Spawner.open` handed out.
        owners: ``{path: uid}`` of the planted entries.

    Returns:
        One finding per uid handed out while it owns a planted entry.
    """
    return [
        f"uid {uid} was handed out owning {path}"
        for uid in opened
        for path, owner in owners.items()
        if owner == uid
    ]


def kill_findings(spawner_, kernel, uid):
    """Args:
        spawner_: the :class:`spawner.Spawner` whose kill runs.
        kernel: the :class:`FakeKernel` holding a process of ``uid`` in a
            session of its own and one in the group of the run.
        uid: the uid of the sandbox.

    Returns:
        One finding per process of ``uid`` the kill left alive.
    """
    with (
        mock.patch.object(spawner, "KILL_ROUNDS", 2),
        contextlib.suppress(spawner.sandbox.SandboxError),
    ):
        spawner_.kill(uid)
    return [f"{pid} outlived the kill" for pid in privileged.holders(uid, kernel.proc)]


def purge_findings(remove, base):
    """Args:
        remove: :func:`privileged.remove_owned`, possibly planted.
        base: an empty directory.

    Returns:
        One finding per entry of the sandbox uid it left below the purged
        directory, per entry of another uid it removed there, per entry
        outside it that it reached through a link, and per directory outside
        whose mode it changed through a link.
    """
    top, outside = base / "task", base / "outside"
    locked = outside / "locked"
    own = [
        top / "own.json",
        top / "plugins",
        top / "plugins" / "state",
        top / "link",
        top / "dirlink",
    ]
    for path in (top, outside, top / "plugins", locked):
        path.mkdir()
    for path in (top / "own.json", top / "plugins" / "state", outside / "victim"):
        path.write_text("x", encoding="utf-8")
    (top / "foreign.json").write_text("x", encoding="utf-8")
    (top / "link").symlink_to(outside / "victim")
    (top / "dirlink").symlink_to(locked)
    locked.chmod(0o500)
    owners = dict.fromkeys([*own, outside / "victim", locked], FIRST)
    owners[top / "foreign.json"] = RUNNER
    with (
        mock.patch.object(privileged, "owner", chowned(owners)),
        mock.patch.object(spawner.os, "getuid", return_value=FIRST),
    ):
        remove(str(top))
    findings = [f"{p.name} of the uid survived" for p in own if os.path.lexists(p)]
    if not (top / "foreign.json").exists():
        findings.append("foreign.json of another uid was removed")
    if not (outside / "victim").exists():
        findings.append("the purge followed a link out of the directory")
    if stat.S_IMODE(locked.stat().st_mode) != 0o500:
        findings.append("the purge opened up a directory behind a link")
    locked.chmod(0o700)
    return findings


def reuse_findings(opened, kernel):
    """Args:
        opened: the uids :meth:`Spawner.open` handed out, in order.
        kernel: the :class:`FakeKernel` whose processes really run.

    Returns:
        One finding per uid handed out while a process still holds it.
    """
    return [
        f"uid {uid} was handed out while held"
        for uid in opened
        if privileged.holders(uid, kernel.proc)
    ]


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)
        self.root = self.base / "sandboxes"
        self.root.mkdir()
        self.kernel = FakeKernel(self.base / "proc")
        self.libc = mock.Mock(
            **{
                f"{name}.side_effect": self.kernel.ipc_remover(kind)
                for kind, name in privileged.IPC_REMOVERS.items()
            }
        )
        self.privileges = kernel_privileges(self.kernel, self.libc)
        known = admission.programs(TOFU_PATH, admission.credentials(), PINNED)
        uids = range(FIRST, FIRST + 4)
        self.spawner = spawner.Spawner(self.privileges, self.root, uids, known)


class TestUidPerRun(KernelCase):
    def test_overlapping_runs_never_share_a_sandbox(self):
        first, first_task = self.spawner.open()
        self.kernel.spawn(100, first, 100)
        second, _ = self.spawner.open()
        self.assertNotEqual(first, second)
        self.spawner.close(first)
        self.assertIn((first, -1, signal.SIGKILL), self.kernel.signals)
        self.assertFalse(first_task.parent.exists())
        third, _ = self.spawner.open()
        self.assertEqual(third, first)
        self.assertEqual(reuse_findings([first, second, third], self.kernel), [])

    def test_a_surviving_holder_keeps_its_uid_out_of_the_range(self):
        first, _ = self.spawner.open()
        self.kernel.spawn(100, first, 100, immortal=True)
        with (
            mock.patch.object(spawner, "KILL_ROUNDS", 2),
            self.assertRaises(spawner.sandbox.SandboxError),
        ):
            self.spawner.close(first)
        self.assertIn(first, self.spawner.quarantined)
        opened = [self.spawner.open()[0] for _ in range(3)]
        self.assertNotIn(first, opened)
        self.assertEqual(reuse_findings(opened, self.kernel), [])

    def test_negative_control_a_uid_released_while_held_is_reused(self):
        first, _ = self.spawner.open()
        self.kernel.spawn(100, first, 100, immortal=True)
        with mock.patch.object(self.privileges, "holders", return_value=[]):
            self.spawner.close(first)
            opened = [self.spawner.open()[0] for _ in range(3)]
        self.assertEqual(
            reuse_findings(opened, self.kernel),
            [f"uid {first} was handed out while held"],
        )

    def test_a_uid_with_files_left_stays_out_of_the_range(self):
        first, _ = self.spawner.open()
        with (
            mock.patch.object(self.privileges, "purge", side_effect=OSError("busy")),
            self.assertRaises(OSError),
        ):
            self.spawner.close(first)
        self.assertIn(first, self.spawner.quarantined)
        self.assertNotEqual(self.spawner.open()[0], first)


class TestUidKill(KernelCase):
    def setUp(self):
        super().setUp()
        self.uid, _ = self.spawner.open()
        self.kernel.spawn(200, self.uid, 200)
        self.kernel.spawn(201, self.uid, 201)

    def test_the_uid_kill_ends_a_child_in_a_new_session(self):
        self.assertEqual(kill_findings(self.spawner, self.kernel, self.uid), [])
        self.assertEqual(self.kernel.signals[0], (self.uid, -1, signal.SIGKILL))

    def test_negative_control_a_new_session_escapes_the_group_kill(self):
        helper = self.privileges.helper

        def group_kill(uid, signum):
            helper(uid, "signal", str(int(signum)), "-200")

        with mock.patch.object(self.privileges, "signal_all", group_kill):
            findings = kill_findings(self.spawner, self.kernel, self.uid)
        self.assertEqual(findings, ["201 outlived the kill"])


class TestPurge(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)

    def test_the_purge_removes_every_entry_of_its_uid_alone(self):
        self.assertEqual(purge_findings(privileged.remove_owned, self.base), [])

    def test_negative_control_a_purge_that_skips_deletes_leaves_them(self):
        findings = purge_findings(lambda *_tops: None, self.base)
        self.assertIn("own.json of the uid survived", findings)

    def test_negative_control_a_purge_that_follows_a_link_reaches_outside(self):
        findings = purge_findings(following, self.base)
        self.assertIn("the purge followed a link out of the directory", findings)

    def test_negative_control_a_purge_that_ignores_the_owner_removes_others(self):
        findings = purge_findings(ignoring_owner, self.base)
        self.assertIn("foreign.json of another uid was removed", findings)

    def test_negative_control_a_chmod_through_a_link_opens_up_outside(self):
        findings = purge_findings(chmod_through_links, self.base)
        self.assertIn("the purge opened up a directory behind a link", findings)


class TestClosePurge(KernelCase):
    def test_the_close_removes_every_file_the_uid_and_the_runner_left(self):
        uid, task = self.spawner.open()
        home = spawner.sandbox.home_of(task)
        planted = [task / ".terraform.lock.hcl", home / "cache"]
        backend = task / "backend.tfbackend"
        for path in (*planted, backend):
            path.write_text("x", encoding="utf-8")
        owners = dict.fromkeys(planted, uid) | {backend: RUNNER}
        with mock.patch.object(privileged, "owner", chowned(owners)):
            self.spawner.close(uid)
        self.assertFalse(task.parent.exists())
        self.assertNotIn(uid, self.spawner.quarantined)

    def test_negative_control_a_file_of_a_third_uid_keeps_the_uid_out(self):
        uid, task = self.spawner.open()
        stray = task / "stray"
        stray.write_text("x", encoding="utf-8")
        with (
            mock.patch.object(privileged, "owner", chowned({stray: RUNNER + 1})),
            self.assertRaises(OSError),
        ):
            self.spawner.close(uid)
        self.assertIn(uid, self.spawner.quarantined)


class TestLeftovers(KernelCase):
    def setUp(self):
        super().setUp()
        self.stray = self.base / "stray"
        self.stray.write_text("x", encoding="utf-8")
        self.owners = {self.stray: FIRST}

    def test_a_uid_that_owns_an_entry_anywhere_stays_out_of_the_range(self):
        with mock.patch.object(privileged, "owner", chowned(self.owners)):
            opened = [self.spawner.open()[0] for _ in range(2)]
        self.assertEqual(leftover_findings(opened, self.owners), [])

    def test_negative_control_an_allocation_without_the_walk_hands_it_out(self):
        with (
            mock.patch.object(privileged, "owner", chowned(self.owners)),
            mock.patch.object(self.privileges, "leftovers", return_value=[]),
        ):
            opened = [self.spawner.open()[0] for _ in range(2)]
        self.assertEqual(
            leftover_findings(opened, self.owners),
            [f"uid {FIRST} was handed out owning {self.stray}"],
        )


class FakeChannel:
    def __init__(self):
        self.sent = []

    def send(self, message, descriptors=()):
        self.sent.append(message)


def quarantine_findings(spawner_, stderr):
    """Args:
        spawner_: the :class:`spawner.Spawner` whose uids left the range.
        stderr: what it wrote to stderr.

    Returns:
        One finding per quarantined uid stderr does not name, as the operator
        then never learns why the range shrinks.
    """
    return [
        f"the uid {uid} left the range silently"
        for uid in sorted(spawner_.quarantined)
        if f"the uid {uid} stays out of the range" not in stderr
    ]


def silenced(spawner_):
    """Args:
        spawner_: the :class:`spawner.Spawner` it plants into.

    Returns:
        :meth:`spawner.Spawner.quarantine` without its stderr line.
    """

    def quarantine(uid, _reason):
        with spawner_.lock:
            spawner_.active.discard(uid)
            spawner_.quarantined.add(uid)

    return quarantine


class TestRun(KernelCase):
    def setUp(self):
        super().setUp()
        self.uid, self.task = self.spawner.open()
        self.channel = FakeChannel()
        self.run = spawner.Run(self.spawner, self.channel, self.uid, self.task)
        self.started = []
        start = mock.patch.object(
            self.privileges,
            "start",
            lambda *arguments: self.started.append(arguments) or mock.Mock(),
        )
        start.start()
        self.addCleanup(start.stop)
        wait = mock.patch.object(self.privileges, "wait", return_value=0)
        wait.start()
        self.addCleanup(wait.stop)

    def request(self, program, arguments, environment):
        message = {"op": "run", "program": program, "argv": arguments}
        self.run.run(message | {"env": environment}, [0, 1, 2])
        if self.run.waiter is not None:
            self.run.waiter.join()

    def test_a_client_that_sends_a_shell_is_refused(self):
        for program, environment in (
            ("/bin/sh", {}),
            (TOFU, {"LD_PRELOAD": "/tmp/evil.so"}),
            ([TOFU], {}),
        ):
            with self.subTest(program=program, environment=environment):
                self.channel.sent.clear()
                self.request(program, ["-c", "id"], environment)
                self.assertEqual(self.started, [])
                self.assertIn("error", self.channel.sent[-1])

    def test_negative_control_the_tofu_of_the_layout_is_run(self):
        self.request(TOFU, ["init"], {"PATH": "/usr/bin"})
        (call,) = self.started
        self.assertEqual(call[2], [str(TOFU_PATH), "init"])
        self.assertEqual(self.channel.sent, [{"exit": 0}])

    def survived(self, quarantine):
        """Args:
            quarantine: the :meth:`spawner.Spawner.quarantine` the run uses,
                possibly planted.

        Returns:
            What the spawner wrote to stderr while a call of the run left a
            process alive.
        """
        self.kernel.spawn(300, self.uid, 300, immortal=True)
        stderr = io.StringIO()
        with (
            mock.patch.object(spawner, "KILL_ROUNDS", 2),
            mock.patch.object(self.spawner, "quarantine", quarantine),
            contextlib.redirect_stderr(stderr),
        ):
            self.request(TOFU, ["apply"], {})
        return stderr.getvalue()

    def test_a_surviving_holder_fails_the_call_and_every_later_one(self):
        stderr = self.survived(self.spawner.quarantine)
        self.assertIn("survived", self.channel.sent[-1]["error"])
        self.assertIn(self.uid, self.spawner.quarantined)
        self.assertEqual(quarantine_findings(self.spawner, stderr), [])
        self.request(TOFU, ["apply"], {})
        self.assertEqual(len(self.started), 1)
        self.assertIn("runs nothing more", self.channel.sent[-1]["error"])

    def test_negative_control_a_silent_quarantine_is_found(self):
        stderr = self.survived(silenced(self.spawner))
        self.assertIn(self.uid, self.spawner.quarantined)
        self.assertEqual(
            quarantine_findings(self.spawner, stderr),
            [f"the uid {self.uid} left the range silently"],
        )

    def test_negative_control_a_call_without_survivor_reports_its_exit(self):
        self.request(TOFU, ["apply"], {})
        self.assertEqual(self.channel.sent, [{"exit": 0}])
        self.assertNotIn(self.uid, self.spawner.quarantined)

    def outside_the_run(self):
        """Returns:
        ``{what: (arguments, environment)}`` of requests that reach beyond
        the run's own directories or the layout's settings.
        """
        other = self.root / str(FIRST + 3) / spawner.sandbox.TASK
        foreign = json.loads(spawner.session.encryption(WORKSPACE))
        foreign["key_provider"]["openbao"]["workspace"]["address"] = "https://evil"
        return {
            "a CLI configuration of its own": (
                ["init"],
                {admission.CLI_CONFIG: "/tmp/evil.tfrc"},
            ),
            "a HOME in another run": (["init"], {"HOME": str(other)}),
            "a CA of its own": (["init"], {admission.CA_NAME: "/tmp/evil.pem"}),
            "a proxy of its own": (["init"], {"HTTPS_PROXY": "http://evil:3128"}),
            "an OpenBao of its own": (["init"], {admission.BAO_NAME: "https://evil"}),
            "an encryption with a key provider of its own": (
                ["init"],
                {admission.ENCRYPTION: json.dumps(foreign)},
            ),
            "a line break in a value": (["init"], {"OS_REGION_NAME": "a\nb"}),
            "an endpoint that is a local socket": (
                ["init"],
                {"INCUS_ADDR": "unix:/var/lib/incus/unix.socket"},
            ),
            "an endpoint that is a local socket in upper case": (
                ["init"],
                {"INCUS_ADDR": "UNIX:/var/lib/incus/unix.socket"},
            ),
            "a remote that is a local socket": (
                ["init"],
                {"INCUS_REMOTE": "unix:/var/lib/incus/unix.socket"},
            ),
            "a credential file in another run": (
                ["init"],
                {"INCUS_CONF": str(other / "credentials")},
            ),
            "-chdir": (["init", "-chdir=/"], {}),
            "-plugin-dir": (["init", "-plugin-dir=/tmp/plugins"], {}),
            "a backend setting instead of a file": (
                ["init", "-backend-config=path=/tmp/state"],
                {},
            ),
            "a var file in another run": (
                ["apply", f"-var-file={other / 'values.tfvars.json'}"],
                {},
            ),
            "a var file climbing out": (["apply", "-var-file=link/../../x"], {}),
            "a command provision never runs": (["console"], {}),
        }

    def started_of(self, cases):
        started = []
        for what, (arguments, environment) in cases.items():
            self.started.clear()
            self.request(TOFU, arguments, environment)
            if self.started:
                started.append(what)
        return started

    def test_a_value_or_flag_outside_the_run_is_refused(self):
        self.assertEqual(self.started_of(self.outside_the_run()), [])
        home = spawner.sandbox.home_of(self.task)
        self.request(
            TOFU,
            [
                "init",
                "-input=false",
                f"-backend-config={self.task / 'backend.tfbackend'}",
            ],
            {
                admission.CLI_CONFIG: PINNED[admission.CLI_CONFIG],
                admission.CA_NAME: str(SELF_SIGNED_CA),
                admission.BAO_NAME: BAO,
                admission.ENCRYPTION: spawner.session.encryption(WORKSPACE),
                "INCUS_CONF": str(self.task / "credentials"),
                "INCUS_ADDR": "https://incus.example.org:8443",
                "HOME": str(home),
                "TMPDIR": str(home),
                "PATH": "/tmp/evil",
            },
        )
        (call,) = self.started
        self.assertEqual(call[3]["PATH"], admission.SANDBOX_PATH)
        self.assertEqual(sorted(call[5]), ["backend.tfbackend", "credentials"])

    def test_negative_control_a_check_of_names_alone_admits_them(self):
        cases = self.outside_the_run()
        tofu = self.spawner.known[TOFU]
        self.spawner.known = {TOFU: tofu._replace(arguments=None)}
        with mock.patch.object(admission, "value_admitted", return_value=True):
            self.assertEqual(sorted(self.started_of(cases)), sorted(cases))

    def secret_case(self):
        return {
            "a secret that starts with a slash": (
                ["apply"],
                {SECRET_NAME: "/q8+Zm9v=="},
            )
        }

    def test_a_secret_that_starts_with_a_slash_is_admitted(self):
        self.assertEqual(self.started_of(self.secret_case()), list(self.secret_case()))

    def test_negative_control_a_path_guess_on_every_value_refuses_it(self):
        def guessing(_name, value, _entry, task):
            if value.startswith(("/", ".")):
                return spawner.sandbox.task_relative(task, value) is not None
            return True

        with mock.patch.object(admission, "value_admitted", guessing):
            self.assertEqual(self.started_of(self.secret_case()), [])

    @staticmethod
    def remote_cases(remotes):
        return {remote: (["init"], {"INCUS_REMOTE": remote}) for remote in remotes}

    def test_the_built_in_local_remote_is_refused(self):
        self.assertEqual(self.started_of(self.remote_cases(LOCAL_REMOTES)), [])
        hosts = self.remote_cases(HOST_REMOTES)
        self.assertEqual(self.started_of(hosts), list(hosts))

    def test_negative_control_a_check_blind_to_the_local_remote_admits_it(self):
        cases = self.remote_cases(LOCAL_REMOTES)
        with mock.patch.object(admission, "LOCAL_REMOTES", frozenset()):
            self.assertEqual(self.started_of(cases), list(cases))


class TestIpcPurge(KernelCase):
    def test_the_purge_removes_the_ipc_objects_of_the_uid(self):
        uid, _ = self.spawner.open()
        self.kernel.ipc("shm", 7, uid)
        self.kernel.ipc("msg", 8, uid)
        self.kernel.ipc("shm", 9, RUNNER)
        self.spawner.close(uid)
        self.assertEqual(spawner.sandbox.ipc_objects(uid, self.kernel.proc), [])
        self.assertEqual(
            spawner.sandbox.ipc_objects(RUNNER, self.kernel.proc), [("shm", "9")]
        )
        self.assertNotIn(uid, self.spawner.quarantined)

    def ipc_findings(self, opened):
        return [
            f"uid {uid} was handed out owning an IPC object"
            for uid in opened
            if spawner.sandbox.ipc_objects(uid, self.kernel.proc)
        ]

    def test_a_uid_owning_an_ipc_object_stays_out_of_the_range(self):
        self.kernel.ipc("shm", 5, FIRST)
        opened = [self.spawner.open()[0] for _ in range(2)]
        self.assertEqual(self.ipc_findings(opened), [])

    def test_negative_control_an_allocation_blind_to_ipc_hands_it_out(self):
        self.kernel.ipc("shm", 5, FIRST)
        with mock.patch.object(self.privileges, "ipc_left", return_value=[]):
            opened = [self.spawner.open()[0] for _ in range(2)]
        self.assertEqual(
            self.ipc_findings(opened),
            [f"uid {FIRST} was handed out owning an IPC object"],
        )

    def test_a_failed_file_purge_still_removes_the_ipc_objects(self):
        uid, _ = self.spawner.open()
        self.kernel.ipc("shm", 7, uid)
        stderr = io.StringIO()
        with (
            mock.patch.object(privileged, "remove_owned", side_effect=OSError("long")),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(spawner.sandbox.SandboxError),
        ):
            self.spawner.close(uid)
        self.assertEqual(spawner.sandbox.ipc_objects(uid, self.kernel.proc), [])
        self.assertIn(uid, self.spawner.quarantined)
        self.assertEqual(quarantine_findings(self.spawner, stderr.getvalue()), [])

    def test_negative_control_a_purge_that_stops_at_the_first_failure_keeps_them(self):
        uid, _ = self.spawner.open()
        self.kernel.ipc("shm", 7, uid)
        privileges = self.privileges

        def stopping(uid_, task_, home):
            privileges.helper(uid_, "purge", str(task_), str(home))
            privileges.helper(uid_, "ipc")

        with (
            mock.patch.object(privileged, "remove_owned", side_effect=OSError("long")),
            mock.patch.object(self.privileges, "purge", stopping),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(spawner.sandbox.SandboxError),
        ):
            self.spawner.close(uid)
        self.assertEqual(
            spawner.sandbox.ipc_objects(uid, self.kernel.proc), [("shm", "7")]
        )

    def test_negative_control_an_ipc_object_left_quarantines_the_uid(self):
        uid, _ = self.spawner.open()
        self.kernel.ipc("shm", 7, uid)
        self.libc.shmctl.side_effect = lambda *_arguments: -1
        with self.assertRaisesRegex(spawner.sandbox.SandboxError, "IPC objects"):
            self.spawner.close(uid)
        self.assertIn(uid, self.spawner.quarantined)


class TestNoNewPrivileges(unittest.TestCase):
    def test_the_spawner_sets_no_new_privs_before_it_serves(self):
        libc = mock.Mock(**{"prctl.return_value": 0})
        hardening.no_new_privileges(libc)
        libc.prctl.assert_called_once_with(hardening.PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
        with (
            mock.patch.dict(os.environ, LAYOUT_ENV),
            mock.patch.object(spawner.os, "geteuid", return_value=0),
            mock.patch.object(
                hardening, "no_new_privileges", side_effect=SystemExit("no_new_privs")
            ),
            mock.patch.object(hardening, "harden") as harden,
            self.assertRaisesRegex(SystemExit, "no_new_privs"),
        ):
            spawner.serve(["semaphore"])
        harden.assert_not_called()

    def test_negative_control_a_refused_prctl_stops_the_start(self):
        libc = mock.Mock(**{"prctl.return_value": -1})
        with self.assertRaisesRegex(SystemExit, "refused no_new_privs"):
            hardening.no_new_privileges(libc)


class TestServe(unittest.TestCase):
    def served(self, code):
        """Args:
            code: the exit status ``waited`` reports for the Semaphore runner.

        Returns:
            ``{"code", "harden", "spawned", "threads", "targets",
            "forwarded", "handled"}`` of one :func:`spawner.serve` as root,
            its threads recorded instead of started, ``targets`` what each
            of them runs by name, ``forwarded`` the helper calls a
            ``SIGTERM`` makes.
        """
        account = mock.Mock(pw_gid=RUNNER, pw_dir="/home/runner", pw_name="runner")
        process = mock.Mock(pid=4242)
        handlers, threads, helpers, targets = {}, [], [], {}

        def thread(target, **options):
            threads.append((target.__name__, options.get("daemon")))
            targets[target.__name__] = target
            return mock.Mock()

        with (
            mock.patch.dict(os.environ, LAYOUT_ENV),
            mock.patch.object(spawner.os, "geteuid", return_value=0),
            mock.patch.object(hardening, "no_new_privileges"),
            mock.patch.object(hardening, "harden") as harden,
            mock.patch.object(spawner.pwd, "getpwuid", return_value=account),
            mock.patch.object(privileged, "spawned", return_value=process) as spawned,
            mock.patch.object(privileged, "waited", return_value=code),
            mock.patch.object(spawner.signal, "signal", handlers.__setitem__),
            mock.patch.object(spawner.threading, "Thread", thread),
            mock.patch.object(
                privileged.Privileges,
                "helper",
                lambda _self, *argv, group=None: helpers.append(argv),
            ),
        ):
            result = spawner.serve(["semaphore", "runner"])
            handlers[signal.SIGTERM](int(signal.SIGTERM), None)
        return {
            "code": result,
            "harden": harden.call_args.args,
            "spawned": spawned.call_args,
            "threads": threads,
            "targets": targets,
            "forwarded": helpers,
            "handled": sorted(handlers),
        }

    def test_serve_starts_the_runner_dropped_and_forwards_its_stop(self):
        served = self.served(0)
        container = hardening.layout(LAYOUT_ENV)
        self.assertEqual(served["code"], 0)
        self.assertEqual(
            served["harden"],
            (
                RUNNER,
                RUNNER,
                container["root"],
                container["tmp"],
                container["shared"],
                spawner.sandbox.FILESYSTEM,
            ),
        )
        argv = spawner.sandbox.dropped(RUNNER, ["semaphore", "runner"])
        self.assertEqual(served["spawned"].args, (argv,))
        self.assertEqual(served["spawned"].kwargs["env"]["HOME"], "/home/runner")
        self.assertEqual(served["threads"], [("accept", True), ("reap", True)])
        self.assertEqual(served["handled"], sorted([signal.SIGINT, signal.SIGTERM]))
        self.assertEqual(
            served["forwarded"], [(RUNNER, "signal", str(int(signal.SIGTERM)), "4242")]
        )

    def test_a_runner_killed_by_a_signal_ends_serve_with_its_shell_code(self):
        self.assertEqual(self.served(-signal.SIGTERM)["code"], 128 + signal.SIGTERM)

    def accept_ended(self, *plants):
        """Args:
            plants: patchers active for :func:`spawner.serve`, an accept
                thread without :func:`spawner.vital` for a control.

        Returns:
            The ``(pid, signal)`` the target :func:`spawner.serve` gives its
            accept thread sent, recorded instead of sent, once a programming
            error in the accept ended the loop and still propagated.
        """
        with contextlib.ExitStack() as stack:
            for plant in plants:
                stack.enter_context(plant)
            accept = self.served(0)["targets"]["accept"]
        sent = []
        with (
            mock.patch.object(spawner.os, "kill", lambda *target: sent.append(target)),
            self.assertRaises(ValueError),
        ):
            accept(ScriptedListener([ValueError("a bug")]), mock.Mock())
        return sent

    def test_the_end_of_the_accept_loop_sends_the_spawner_sigterm(self):
        self.assertEqual(self.accept_ended(), [(os.getpid(), signal.SIGTERM)])

    def test_negative_control_an_unwrapped_accept_thread_sends_nothing(self):
        plant = mock.patch.object(spawner, "vital", lambda target: target)
        self.assertEqual(self.accept_ended(plant), [])

    def stopped(self, lock):
        """Args:
            lock: the ``CHILDREN_LOCK`` of the run, the real one or a planted
                :class:`NonReentrantLock`.

        Returns:
            ``(code, started)``: what :func:`spawner.serve` returned and the
            argv of every process it started, once the ``SIGINT`` handler it
            registered ran in the main thread while that thread held ``lock``
            waiting for the Semaphore runner.
        """
        account = mock.Mock(pw_gid=RUNNER, pw_dir="/home/runner", pw_name="runner")
        handlers, started = {}, []

        def interrupted():
            with privileged.CHILDREN_LOCK:
                handlers[signal.SIGINT](int(signal.SIGINT), None)
            return 0

        def popen(argv, **_options):
            started.append(argv)
            wait = interrupted if len(started) == 1 else mock.Mock(return_value=0)
            return mock.Mock(pid=4242, wait=wait)

        with (
            mock.patch.dict(os.environ, LAYOUT_ENV),
            mock.patch.object(spawner.os, "geteuid", return_value=0),
            mock.patch.object(hardening, "no_new_privileges"),
            mock.patch.object(hardening, "harden"),
            mock.patch.object(spawner.pwd, "getpwuid", return_value=account),
            mock.patch.object(privileged, "CHILDREN", set()),
            mock.patch.object(privileged, "CHILDREN_LOCK", lock),
            mock.patch.object(privileged.subprocess, "Popen", popen),
            mock.patch.object(spawner.signal, "signal", handlers.__setitem__),
            mock.patch.object(spawner.threading, "Thread", mock.Mock()),
        ):
            code = spawner.serve(["semaphore", "runner"])
        return code, started

    def test_a_sigint_while_the_main_thread_holds_the_lock_reaches_the_runner(self):
        code, started = self.stopped(privileged.CHILDREN_LOCK)
        self.assertEqual(code, 0)
        self.assertEqual(len(started), 2)
        helper = started[1]
        dropped = spawner.sandbox.dropped(RUNNER, [])[:-1]
        self.assertEqual(helper[: helper.index("--")], dropped)
        self.assertEqual(helper[-3:], ["signal", str(int(signal.SIGINT)), "4242"])

    def test_negative_control_a_non_reentrant_lock_deadlocks_the_sigint(self):
        with self.assertRaisesRegex(RuntimeError, "takes it again"):
            self.stopped(NonReentrantLock())


class NonReentrantLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.owner = None

    def __enter__(self):
        if self.owner == threading.get_ident():
            raise RuntimeError("the thread that holds the lock takes it again")
        self.lock.acquire()
        self.owner = threading.get_ident()
        return self

    def __exit__(self, *_failure):
        self.owner = None
        self.lock.release()


class TestOpenMessage(KernelCase):
    def kept(self, serving):
        """Args:
            serving: the context :meth:`spawner.Spawner.serve` runs in, a
                planted ``os.close`` for a control.

        Returns:
            Every descriptor of this process that still holds the read end
            of a pipe a peer other than the runner sent on its open message,
            once the spawner refused it.
        """
        self.privileges.runner = os.getuid() + 1
        client, server = socket.socketpair()
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = inode(reader)
        spawner.sandbox.Channel(client).send({"op": "open"}, [reader])
        os.close(reader)
        client.close()
        with serving:
            self.spawner.serve(server)
        return held(pipe, writer)

    def test_the_spawner_closes_the_descriptors_of_a_refused_open(self):
        self.assertEqual(self.kept(contextlib.nullcontext()), [])

    def test_negative_control_a_spawner_that_keeps_them_leaks_the_pipe(self):
        found = self.kept(mock.patch.object(spawner.os, "close", lambda _fd: None))
        spawner.sandbox.close_all(found)
        self.assertEqual(len(found), 1)


class ScriptedChannel(FakeChannel):
    """Args:
    lines: the ``(message, descriptors)`` it receives, or the exception it
        raises, in turn before the peer closes the connection.
    """

    def __init__(self, lines):
        super().__init__()
        self.lines = list(lines)

    def receive(self):
        line = self.lines.pop(0) if self.lines else (None, [])
        if isinstance(line, BaseException):
            raise line
        return line


def unguarded_serve(run):
    """Args:
    run: the :class:`spawner.Run` it serves, as a loop that closes the
        descriptors of a message only after it handled the message and did
        not break off.
    """
    while True:
        message, descriptors = run.channel.receive()
        if message is None or message.get("op") == "close":
            break
        run.handle(message, descriptors)
        spawner.sandbox.close_all(descriptors)


RUN_REQUEST = {
    "op": "run",
    "program": TOFU,
    "argv": ["init"],
    "env": {"PATH": "/usr/bin"},
}
RUN_PID = 400
LEAKING = {
    "a close": {"op": "close"},
    "a run whose start fails": RUN_REQUEST,
}


class TestRunDescriptors(KernelCase):
    def leaked(self, message, serve):
        """Args:
            message: what the runner sends with a read end of one pipe as
                each of the three streams.
            serve: :meth:`spawner.Run.serve`, possibly planted.

        Returns:
            Every descriptor of this process that still holds that pipe once
            ``serve`` returned, or raised as the start of the run failed.
        """
        uid, task = self.spawner.open()
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = inode(reader)
        streams = [os.dup(reader) for _ in range(spawner.sandbox.STREAMS)]
        os.close(reader)
        channel = ScriptedChannel([(message, streams)])
        run = spawner.Run(self.spawner, channel, uid, task)
        failure = OSError(errno.EMFILE, "Too many open files")
        with (
            mock.patch.object(self.privileges, "start", side_effect=failure),
            contextlib.suppress(OSError),
        ):
            serve(run)
        return held(pipe, writer)

    def test_the_run_closes_the_descriptors_on_every_path(self):
        for what, message in LEAKING.items():
            with self.subTest(what):
                self.assertEqual(self.leaked(message, spawner.Run.serve), [])

    def test_negative_control_a_loop_closing_after_the_handling_leaks_them(self):
        for what, message in LEAKING.items():
            with self.subTest(what):
                found = self.leaked(message, unguarded_serve)
                spawner.sandbox.close_all(found)
                self.assertEqual(len(found), spawner.sandbox.STREAMS)


def unjoined_serve(run):
    """Args:
    run: the :class:`spawner.Run` it serves, as a loop that kills the uid
        and joins the waiter only when no receive raised.
    """
    while True:
        message, descriptors = run.channel.receive()
        try:
            if message is None or message.get("op") == "close":
                break
            run.handle(message, descriptors)
        finally:
            spawner.sandbox.close_all(descriptors)
    run.spawner.kill(run.uid)
    if run.waiter is not None:
        run.waiter.join()


class TestRunRaise(KernelCase):
    def left(self, serve):
        """Args:
            serve: :meth:`spawner.Run.serve`, possibly planted.

        Returns:
            ``(waiting, holders)`` as :meth:`spawner.Spawner.close` would
            find them once ``serve`` raised on a line that is no JSON after
            a run started: whether the waiter of that run still lives, its
            process unkilled, and the processes of the uid.
        """
        uid, task = self.spawner.open()
        killed = threading.Event()
        signal_all = self.privileges.signal_all

        def killing(target, signum):
            signal_all(target, signum)
            killed.set()

        def started(*_arguments):
            self.kernel.spawn(RUN_PID, uid, RUN_PID)
            return mock.Mock()

        streams = [
            os.open(os.devnull, os.O_RDONLY) for _ in range(spawner.sandbox.STREAMS)
        ]
        channel = ScriptedChannel([(RUN_REQUEST, streams), ValueError("no JSON")])
        run = spawner.Run(self.spawner, channel, uid, task)
        with (
            mock.patch.object(self.privileges, "start", started),
            mock.patch.object(
                self.privileges,
                "wait",
                lambda _process: killed.wait(JOIN_SECONDS) and -signal.SIGKILL,
            ),
            mock.patch.object(self.privileges, "signal_all", killing),
        ):
            with self.assertRaises(ValueError):
                serve(run)
            left = (run.waiter.is_alive(), self.privileges.holders(uid))
            self.spawner.close(uid)
            run.waiter.join(JOIN_SECONDS)
        self.assertFalse(run.waiter.is_alive())
        return left

    def test_a_receive_that_raises_kills_the_uid_and_joins_the_waiter(self):
        self.assertEqual(self.left(spawner.Run.serve), (False, []))

    def test_negative_control_a_kill_after_the_loop_alone_leaves_both(self):
        self.assertEqual(self.left(unjoined_serve), (True, [RUN_PID]))


def unwaited_run(run, message, descriptors):
    """Args:
    run: the :class:`spawner.Run` it plants into, as a run that keeps its
        waiter before the waiter started and leaves the process to it.
    message: see :meth:`spawner.Run.run`.
    descriptors: see :meth:`spawner.Run.run`.
    """
    argv, environment, files = admission.admitted(message, run.spawner.known, run.task)
    process = run.spawner.privileges.start(
        run.uid, run.task, argv, environment, descriptors, files
    )
    run.waiter = spawner.threading.Thread(target=run.finish, args=(process,))
    run.waiter.start()


class TestRunStart(KernelCase):
    def left(self, run_once):
        """Args:
            run_once: :meth:`spawner.Run.run`, possibly planted.

        Returns:
            ``(children, holders, replies, waiter)`` once the waiter thread
            of a started run failed to start: the pids
            :data:`privileged.CHILDREN` hides from the reaper, the processes
            of the uid, what the run replied and the waiter it keeps.
        """
        uid, task = self.spawner.open()
        run = spawner.Run(self.spawner, FakeChannel(), uid, task)
        children = set()

        def started(*_arguments):
            self.kernel.spawn(RUN_PID, uid, RUN_PID)
            children.add(RUN_PID)
            return mock.Mock(pid=RUN_PID, **{"wait.return_value": -signal.SIGKILL})

        threads = types.SimpleNamespace(
            Thread=failing_once(threading.Thread, RuntimeError(NO_THREAD))
        )
        with (
            mock.patch.object(privileged, "CHILDREN", children),
            mock.patch.object(self.privileges, "start", started),
            mock.patch.object(spawner, "threading", threads),
            contextlib.suppress(RuntimeError),
        ):
            run_once(run, RUN_REQUEST, [0, 1, 2])
        return children, self.privileges.holders(uid), run.channel.sent, run.waiter

    def test_a_waiter_that_cannot_start_leaves_no_process_behind(self):
        reply = {"error": f"no waiter of the run started: {NO_THREAD}"}
        self.assertEqual(self.left(spawner.Run.run), (set(), [], [reply], None))

    def test_negative_control_a_waiter_kept_before_its_start_leaves_the_pid(self):
        children, holders, replies, _waiter = self.left(unwaited_run)
        self.assertEqual((children, holders, replies), ({RUN_PID}, [RUN_PID], []))


class ClosedError(BaseException):
    pass


class ScriptedListener:
    """Args:
    steps: what each ``accept`` raises, or returns as its connection, in
        turn.
    """

    def __init__(self, steps):
        self.steps = list(steps)

    def accept(self):
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step, None


def unguarded_accept(listener, serve_connection):
    """Args:
    listener: see :func:`spawner.accept`, which it plants as a loop that
        the first failed accept ends.
    serve_connection: see :func:`spawner.accept`.
    """
    while True:
        connection, _address = listener.accept()
        threading.Thread(
            target=serve_connection, args=(connection,), daemon=True
        ).start()


def exception_accept(listener, serve_connection):
    """Args:
    listener: see :func:`spawner.accept`, which it plants as a loop that
        sends every ``Exception`` of the accept to :func:`spawner.refused`.
    serve_connection: see :func:`spawner.accept`.
    """
    while True:
        try:
            connection, _address = listener.accept()
        except Exception as failure:
            spawner.refused("no connection accepted", failure)
            continue
        threading.Thread(
            target=serve_connection, args=(connection,), daemon=True
        ).start()


class TestAccept(unittest.TestCase):
    def served(self, loop):
        """Args:
            loop: :func:`spawner.accept`, possibly planted.

        Returns:
            ``(served, stderr)``: the connections ``loop`` served after its
            first accept failed with ``EMFILE``, and what it wrote to stderr.
        """
        connection = object()
        failure = OSError(errno.EMFILE, "Too many open files")
        listener = ScriptedListener([failure, connection, ClosedError()])
        connections = queue.Queue()
        stderr = io.StringIO()
        with (
            mock.patch.object(spawner, "ACCEPT_PAUSE", 0),
            contextlib.redirect_stderr(stderr),
            contextlib.suppress(ClosedError, OSError),
        ):
            loop(listener, connections.put)
        taken = connection not in listener.steps
        served = [connections.get(timeout=JOIN_SECONDS)] if taken else []
        return served, stderr.getvalue()

    def test_a_failed_accept_leaves_the_loop_serving(self):
        connection, stderr = self.served(spawner.accept)
        self.assertEqual(len(connection), 1)
        self.assertIn("no connection accepted: OSError: [Errno 24]", stderr)

    def test_negative_control_a_loop_without_the_guard_stops_at_emfile(self):
        self.assertEqual(self.served(unguarded_accept), ([], ""))

    def raised(self, loop):
        """Args:
            loop: :func:`spawner.accept`, possibly planted.

        Returns:
            ``(raised, stderr)``: the type of what ended ``loop`` once its
            first accept raised a ``ValueError``, a programming error, and
            its second a :class:`ClosedError`, and what it wrote to stderr.
        """
        listener = ScriptedListener([ValueError("a bug"), ClosedError()])
        stderr = io.StringIO()
        with (
            mock.patch.object(spawner, "ACCEPT_PAUSE", 0),
            contextlib.redirect_stderr(stderr),
        ):
            try:
                loop(listener, mock.Mock())
            except BaseException as failure:
                return type(failure), stderr.getvalue()
        return None, stderr.getvalue()

    def test_a_programming_error_in_the_accept_ends_the_loop(self):
        self.assertEqual(self.raised(spawner.accept), (ValueError, ""))

    def test_negative_control_a_loop_catching_every_exception_hides_it(self):
        raised, stderr = self.raised(exception_accept)
        self.assertEqual(raised, ClosedError)
        self.assertIn("no connection accepted: ValueError: a bug", stderr)


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class BrokenStream(io.StringIO):
    def write(self, _text):
        raise OSError(errno.EIO, "Input/output error")


def failing_once(real, failure):
    """Args:
        real: :class:`threading.Thread`.
        failure: what the start of its first thread raises, the
            ``RuntimeError`` of a container out of pids or a programming
            error.

    Returns:
        A stand-in for it whose first thread fails to start with
        ``failure``, every later one a real thread.
    """
    made = []

    def thread(*arguments, **options):
        made.append(arguments)
        if len(made) == 1:
            return mock.Mock(**{"start.side_effect": failure})
        return real(*arguments, **options)

    return thread


def oserror_accept(listener, serve_connection):
    """Args:
    listener: see :func:`spawner.accept`, which it plants as a loop that
        guards the accept and the start of its thread against an
        ``OSError`` alone.
    serve_connection: see :func:`spawner.accept`.
    """
    while True:
        try:
            connection, _address = listener.accept()
            spawner.threading.Thread(
                target=serve_connection, args=(connection,), daemon=True
            ).start()
        except OSError as failure:
            spawner.refused("no connection accepted", failure)


def unguarded_refused(what, failure):
    """Args:
    what: see :func:`spawner.refused`, which it plants as a refusal that
        prints its line without guarding against a stderr that is closed.
    failure: see :func:`spawner.refused`.
    """
    print(f"sandbox/spawner.py: {what}: {failure}", file=sys.stderr)


def exception_start_accept(listener, serve_connection):
    """Args:
    listener: see :func:`spawner.accept`, which it plants as a loop that
        sends every ``Exception`` of the start of a serve thread to
        :func:`spawner.refused`.
    serve_connection: see :func:`spawner.accept`.
    """
    while True:
        try:
            connection, _address = listener.accept()
        except OSError as failure:
            spawner.refused("no connection accepted", failure)
            continue
        try:
            spawner.threading.Thread(
                target=serve_connection, args=(connection,), daemon=True
            ).start()
        except Exception as failure:
            connection.close()
            spawner.refused("no connection served", failure)


class TestAcceptStart(unittest.TestCase):
    def served(self, loop, stderr, failure, *plants):
        """Args:
            loop: :func:`spawner.accept`, possibly planted.
            stderr: the stream stderr writes to.
            failure: see :func:`failing_once`.
            plants: patchers active for the loop, a :func:`spawner.refused`
                without its guard for a control.

        Returns:
            ``(served, closed)``: the connections ``loop`` served after the
            thread for its first connection failed to start, and whether it
            closed that first connection.
        """
        first, second = FakeConnection(), FakeConnection()
        listener = ScriptedListener([first, second, ClosedError()])
        connections = queue.Queue()
        threads = types.SimpleNamespace(Thread=failing_once(threading.Thread, failure))
        with contextlib.ExitStack() as stack:
            for plant in (
                mock.patch.object(spawner, "ACCEPT_PAUSE", 0),
                mock.patch.object(spawner, "threading", threads),
                contextlib.redirect_stderr(stderr),
                contextlib.suppress(ClosedError, RuntimeError, OSError),
                *plants,
            ):
                stack.enter_context(plant)
            loop(listener, connections.put)
        taken = second not in listener.steps
        served = [connections.get(timeout=JOIN_SECONDS)] if taken else []
        return served, first.closed

    def test_a_thread_that_cannot_start_leaves_the_loop_serving(self):
        stderr = io.StringIO()
        served, closed = self.served(spawner.accept, stderr, RuntimeError(NO_THREAD))
        self.assertEqual(len(served), 1)
        self.assertTrue(closed)
        self.assertIn(
            f"no connection served: RuntimeError: {NO_THREAD}", stderr.getvalue()
        )
        broken = self.served(spawner.accept, BrokenStream(), RuntimeError(NO_THREAD))
        self.assertEqual(len(broken[0]), 1)

    def test_negative_control_a_loop_guarding_oserror_alone_stops_at_the_start(self):
        served = self.served(oserror_accept, io.StringIO(), RuntimeError(NO_THREAD))
        self.assertEqual(served, ([], False))

    def test_negative_control_a_refusal_printing_unguarded_ends_the_loop(self):
        plant = mock.patch.object(spawner, "refused", unguarded_refused)
        served = self.served(
            spawner.accept, BrokenStream(), RuntimeError(NO_THREAD), plant
        )
        self.assertEqual(served, ([], True))

    def test_a_programming_error_in_the_start_ends_the_loop(self):
        with self.assertRaises(TypeError):
            self.served(spawner.accept, io.StringIO(), TypeError("a bug"))

    def test_negative_control_a_start_catching_every_exception_hides_it(self):
        stderr = io.StringIO()
        served = self.served(exception_start_accept, stderr, TypeError("a bug"))
        self.assertEqual((len(served[0]), served[1]), (1, True))
        self.assertIn("no connection served: TypeError: a bug", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
