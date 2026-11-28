from __future__ import annotations

import contextlib
import datetime as dt
import errno
import json
import os
import shutil
import signal
import socket
import stat
import sys
import threading
import unittest
import unittest.mock as mock
from pathlib import Path, PurePosixPath

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

from ._fake_provision import ROLE, harness_directory, load
from ._fake_spawner import FakeSpawner, held, inode
from ._tofu_case import READY_BOUND, TofuCase, provision, sandbox

spawner = load("sandbox.spawner")
hardening = spawner.hardening
privileged = spawner.privileged
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
VARIABLES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
SERVICE = "provision-runner"
RUNNER = VOLUMES["semaphore_provision_runner_token"]["uid"]
FIRST, SECOND = 63800, 63801
UNIX_PATH_LIMIT = 108
OPEN_BOUND = 0.05
STILL_WAITING = 0.5
JOIN_SECONDS = 30
BURST = 4
BURST_BOUND = 2.0
OPEN_REFUSAL = "the spawner opened no sandbox: "
RESETS = {os.strerror(errno.ECONNRESET), os.strerror(errno.EPIPE)}
BROKEN_OFF = {"error": "no waiter of the run started: can't start new thread"}


def mount_of(volume):
    (mount,) = [m for m in VOLUMES[volume]["mounts"] if m["service"] == SERVICE]
    return mount


def mount_mode(volume):
    return int(str(mount_of(volume)["mode"]), 8)


TOKEN = PurePosixPath(mount_of("semaphore_provision_runner_token")["target"])
SECRETS = TOKEN.parent
TMP = PurePosixPath(mount_of("semaphore_runner_tmp")["target"])
ROOT = PurePosixPath(mount_of("semaphore_provision_sandboxes")["target"])
SEMAPHORE_TMP = PurePosixPath(mount_of("semaphore_runner_work")["target"])
LOCKS = TMP / sandbox.LOCKS
IMAGE = (
    PurePosixPath("/usr/local/bin/tofu"),
    PurePosixPath("/usr/local/share/opentofu/providers"),
    PurePosixPath(str(provision.OPENTOFU / "tofurc")),
    PurePosixPath("/etc/ssl/certs"),
)
READ, WRITE, SEARCH = 4, 2, 1
SHARED = {PurePosixPath(path) for path in VARIABLES["SEMAPHORE_SANDBOX_SHARED"]}
EXPECTED_SHARED = {"/var/tmp", "/dev/shm", "/dev/mqueue"}


def tree(tmp_mode=hardening.TMP_MODE, task_mode=None, locks_mode=None):
    """Args:
        tmp_mode: the mode the spawner gives ``/tmp``.
        task_mode: the mode of each task directory, the layout's for None.
        locks_mode: the mode of the lock directory, ``provision.LOCKS_MODE``
            for None.

    Returns:
        ``{path: (owner, group, mode)}`` of the provision runner with two
        sandboxes open: the token, ``/tmp`` with Semaphore's work directory,
        the locks and the spawner's socket, the sandbox root with both runs,
        the shared writable directories and the read-only image paths.
    """
    token_mode = int(VOLUMES["semaphore_provision_runner_token"]["mode"], 8)
    locks = provision.LOCKS_MODE if locks_mode is None else locks_mode
    entries = {
        SECRETS: (0, 0, 0o755),
        TOKEN: (RUNNER, RUNNER, token_mode),
        TMP: (RUNNER, RUNNER, tmp_mode),
        SEMAPHORE_TMP: (0, 0, mount_mode("semaphore_runner_work")),
        LOCKS: (RUNNER, RUNNER, locks),
        TMP / sandbox.SOCKET_NAME: (RUNNER, RUNNER, hardening.SOCKET_MODE),
        ROOT: (0, 0, sandbox.ROOT_MODE),
    }
    for uid in (FIRST, SECOND):
        for path, owner, group, mode in sandbox.layout(ROOT, uid, RUNNER):
            changed = task_mode if path.name == sandbox.TASK and task_mode else mode
            entries[PurePosixPath(str(path))] = (owner, group, changed)
    entries |= dict.fromkeys(SHARED, (0, 0, hardening.closed_mode(0o1777)))
    entries |= dict.fromkeys(IMAGE, (0, 0, 0o755))
    return entries


def credentials(argv):
    """Args:
        argv: the ``setpriv`` argv a sandbox starts with.

    Returns:
        ``(uid, {gid and supplementary groups})`` it runs with.
    """
    options = dict(
        part.split("=", 1) for part in argv[1 : argv.index("--")] if "=" in part
    )
    groups = {int(group) for group in options["--groups"].split(",")}
    return int(options["--reuid"]), groups | {int(options["--regid"])}


def access(entry, uid, groups):
    owner, group, mode = entry
    if uid == owner:
        return (mode >> 6) & 7
    if group in groups:
        return (mode >> 3) & 7
    return mode & 7


def reach(entries, path, uid, groups):
    """Returns:
    The ``READ``/``WRITE`` bits ``uid`` holds on ``path``, ``0`` when an
    ancestor refuses the search; a path outside ``entries`` belongs to root
    with mode ``0755``.
    """
    for ancestor in reversed(path.parents):
        entry = entries.get(ancestor, (0, 0, 0o755))
        if not access(entry, uid, groups) & SEARCH:
            return 0
    return access(entries.get(path, (0, 0, 0o755)), uid, groups) & (READ | WRITE)


def reach_findings(entries, argv):
    """Args:
        entries: :func:`tree`, possibly planted.
        argv: the ``setpriv`` argv of the sandbox of :data:`FIRST`.

    Returns:
        Every path the sandbox reaches beyond its own task directory and
        ``HOME`` read-write, and the image, the shared directories and the
        listing of ``/run/secrets`` read-only.
    """
    uid, groups = credentials(argv)
    own = {
        PurePosixPath(str(path))
        for path, *_ in sandbox.layout(ROOT, FIRST, RUNNER)
        if path.name in (sandbox.TASK, sandbox.HOME)
    }
    readable = {*IMAGE, *SHARED, SECRETS}
    findings = []
    for path in sorted(entries):
        held = reach(entries, path, uid, groups)
        expected = READ | WRITE if path in own else READ if path in readable else 0
        if held != expected:
            findings.append(f"the sandbox reaches {path} with {held}, not {expected}")
    return findings


def rename_findings(task_mode):
    """Args:
        task_mode: the mode of the task directory.

    Returns:
        A finding when the sandbox of :data:`FIRST` may not rename a new file
        over ``.terraform.lock.hcl`` that 64101 staged in its task directory,
        as ``tofu init`` does: in a sticky directory only the owner of the
        entry or of the directory may replace it.
    """
    (task,) = [
        entry
        for entry in sandbox.layout(ROOT, FIRST, RUNNER)
        if entry[0].name == sandbox.TASK
    ]
    _path, owner, group, _mode = task
    uid, groups = FIRST, {FIRST}
    writable = access((owner, group, task_mode), uid, groups) & (WRITE | SEARCH)
    sticky = task_mode & stat.S_ISVTX and uid not in (owner, RUNNER)
    if writable != WRITE | SEARCH or sticky:
        return [f"tofu init may not replace the lock file in a {task_mode:o} task"]
    return []


def started_plan(environment):
    """Args:
        environment: the environment of a run.

    Returns:
        ``(argv, Popen options, plan)`` the spawner starts the run with, the
        plan as the exec helper reads it.
    """
    captured = {}

    def spawned(argv, **options):
        captured["argv"] = argv
        captured["options"] = options
        captured["reader"] = os.dup(options["pass_fds"][0])
        return mock.Mock(pid=4242)

    privileges = privileged.Privileges(RUNNER, sandbox.PROC, sandbox.FILESYSTEM, ())
    task = Path(ROOT) / str(FIRST) / sandbox.TASK
    with mock.patch.object(privileged, "spawned", spawned):
        privileges.start(FIRST, task, ["tofu", "plan"], environment, [0, 1, 2], [])
    with os.fdopen(captured["reader"], encoding="utf-8") as handle:
        plan = json.load(handle)
    return captured["argv"], captured["options"], plan


def environment_findings(environment, argv, options, plan):
    findings = []
    if plan["env"] != environment:
        added = sorted(set(plan["env"]) - set(environment))
        findings.append(f"the sandbox gets {added} beyond Session.environment")
    if options["env"] != {"PATH": privileged.HELPER_PATH}:
        findings.append("root starts the sandbox with the runner's environment")
    if argv[: argv.index("--")] != sandbox.dropped(FIRST, [])[:-1]:
        findings.append(f"the sandbox starts as {argv[: argv.index('--')]}")
    return findings


class TestTheSandboxReach(unittest.TestCase):
    def setUp(self):
        self.environment = {"PATH": "/usr/bin", "BAO_TOKEN": "transit-child"}
        self.argv, self.options, self.plan = started_plan(self.environment)

    def test_the_sandbox_shows_a_run_its_own_files_only(self):
        self.assertEqual(reach_findings(tree(), self.argv), [])
        self.assertEqual(
            environment_findings(self.environment, self.argv, self.options, self.plan),
            [],
        )
        task = Path(ROOT) / str(FIRST) / sandbox.TASK
        self.assertEqual(self.plan["cwd"], str(task))

    def test_negative_control_the_runner_uid_reaches_the_runner_token(self):
        argv = sandbox.dropped(RUNNER, ["tofu"])
        self.assertIn(
            f"the sandbox reaches {TOKEN} with {READ}, not 0",
            reach_findings(tree(), argv),
        )

    def test_negative_control_a_searchable_tmp_reaches_semaphores_work(self):
        self.assertIn(
            f"the sandbox reaches {SEMAPHORE_TMP} with {READ | WRITE}, not 0",
            reach_findings(tree(tmp_mode=0o711), self.argv),
        )

    def test_negative_control_an_open_lock_directory_is_reached(self):
        findings = reach_findings(tree(tmp_mode=0o711, locks_mode=0o777), self.argv)
        reached = f"the sandbox reaches {LOCKS} with {READ | WRITE}, not 0"
        self.assertIn(reached, findings)

    def test_negative_control_a_second_task_directory_is_reached(self):
        second = ROOT / str(SECOND) / sandbox.TASK
        self.assertIn(
            f"the sandbox reaches {second} with {READ}, not 0",
            reach_findings(tree(task_mode=0o2775), self.argv),
        )

    def test_negative_control_an_added_variable_is_found(self):
        planted = self.plan | {"env": self.plan["env"] | {"EXTRA": "1"}}
        self.assertEqual(
            environment_findings(self.environment, self.argv, self.options, planted),
            ["the sandbox gets ['EXTRA'] beyond Session.environment"],
        )

    def test_tofu_init_may_replace_the_lock_file_the_runner_staged(self):
        self.assertEqual(rename_findings(sandbox.TASK_MODE), [])

    def test_negative_control_a_sticky_task_directory_refuses_the_rename(self):
        self.assertEqual(
            rename_findings(sandbox.TASK_MODE | stat.S_ISVTX),
            ["tofu init may not replace the lock file in a 3770 task"],
        )

    def test_the_role_closes_every_shared_writable_directory(self):
        self.assertEqual({str(path) for path in SHARED}, EXPECTED_SHARED)


class TestSocketPath(unittest.TestCase):
    def test_the_socket_path_fits_the_unix_limit(self):
        harness = harness_directory()
        self.addCleanup(shutil.rmtree, harness)
        for directory in (harness / "tmp", harness, TMP):
            with self.subTest(directory=str(directory)):
                path = sandbox.socket_path(directory)
                self.assertLess(len(os.fsencode(path)), UNIX_PATH_LIMIT)
        self.assertEqual(sandbox.SOCKET_LIMIT, UNIX_PATH_LIMIT)

    def test_negative_control_a_socket_path_beyond_the_limit_is_refused(self):
        deep = TMP / ("d" * UNIX_PATH_LIMIT)
        with self.assertRaisesRegex(sandbox.SandboxError, "exceeds"):
            sandbox.socket_path(deep)


def parsing_last(channel):
    """Args:
        channel: a :class:`sandbox.Channel`.

    Returns:
        What :meth:`sandbox.Channel.receive` returns, planted as a receive
        that takes the descriptors of a line out before it parses the line,
        so a line that is no JSON raises with them still open.
    """
    while b"\n" not in channel.buffer:
        data, descriptors, _flags, _address = socket.recv_fds(
            channel.connection, sandbox.RECEIVE_BYTES, sandbox.STREAMS
        )
        channel.descriptors.extend(descriptors)
        channel.buffer += data
    line, _, channel.buffer = channel.buffer.partition(b"\n")
    descriptors, channel.descriptors = channel.descriptors, []
    return json.loads(line), descriptors


class TestChannel(unittest.TestCase):
    def leaked(self, receive):
        """Args:
            receive: :meth:`sandbox.Channel.receive`, possibly planted.

        Returns:
            Every descriptor of this process that still holds the read end of
            a pipe a peer sent on a line that is no JSON, once ``receive``
            refused the line.
        """
        client, server = socket.socketpair()
        self.addCleanup(server.close)
        reader, writer = os.pipe()
        self.addCleanup(os.close, writer)
        pipe = inode(reader)
        socket.send_fds(client, [b"{no json\n"], [reader])
        os.close(reader)
        client.close()
        with self.assertRaises(ValueError):
            receive(sandbox.Channel(server))
        return held(pipe, writer)

    def test_a_line_that_is_no_json_closes_its_descriptors(self):
        self.assertEqual(self.leaked(sandbox.Channel.receive), [])

    def test_negative_control_a_receive_that_parses_last_leaks_them(self):
        found = self.leaked(parsing_last)
        sandbox.close_all(found)
        self.assertEqual(len(found), 1)


class TestOpenBound(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
        self.listener.bind(str(sandbox.socket_path(self.base)))
        self.listener.listen()
        tempdir = mock.patch.object(sandbox.tempfile, "tempdir", str(self.base))
        tempdir.start()
        self.addCleanup(tempdir.stop)

    def opening(self, bound):
        """Args:
            bound: the seconds the open runs before the listener closes.

        Returns:
            ``(ended, failures)``: whether :func:`sandbox.opened` against the
            listener that never accepts ended within ``bound`` in a daemon
            thread, and what it raised once it ended, at the latest after
            the closed listener reset its connection.
        """
        failures = []

        def attempt():
            try:
                with sandbox.opened():
                    failures.append("a spawner that never answers opened one")
            except BaseException as failure:
                failures.append(failure)

        opener = threading.Thread(target=attempt, daemon=True)
        opener.start()
        opener.join(bound)
        ended = not opener.is_alive()
        self.listener.close()
        opener.join(JOIN_SECONDS)
        self.assertFalse(opener.is_alive())
        return ended, failures

    def test_a_spawner_that_never_answers_fails_the_open_within_its_bound(self):
        with mock.patch.object(sandbox, "OPEN_SECONDS", OPEN_BOUND):
            ended, failures = self.opening(JOIN_SECONDS)
        self.assertTrue(ended)
        (failure,) = failures
        self.assertIsInstance(failure, sandbox.SandboxError)
        self.assertIn(f"opened no sandbox within {OPEN_BOUND}", str(failure))

    def test_negative_control_an_unbounded_open_waits_for_the_spawner(self):
        with mock.patch.object(sandbox, "OPEN_SECONDS", None):
            ended, failures = self.opening(STILL_WAITING)
        self.assertFalse(ended)
        self.assertNotIn("within", " ".join(str(f) for f in failures))


def refusal_cause(failure):
    """Args:
        failure: what :func:`sandbox.opened` raised.

    Returns:
        The ``strerror`` a :class:`sandbox.SandboxError` names after
        :data:`OPEN_REFUSAL`, the type name of anything else.
    """
    if not isinstance(failure, sandbox.SandboxError):
        return type(failure).__name__
    return str(failure).removeprefix(OPEN_REFUSAL).split("] ", 1)[-1]


class TestOpenUnreachable(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)
        for plant in (
            mock.patch.object(sandbox.tempfile, "tempdir", str(self.base)),
            mock.patch.object(sandbox, "OPEN_SECONDS", JOIN_SECONDS),
        ):
            plant.start()
            self.addCleanup(plant.stop)
        self.path = sandbox.socket_path(self.base)

    def failed(self):
        """Returns:
        What :func:`sandbox.opened` raised, which the socket timeout of
        :data:`JOIN_SECONDS` bounds.
        """
        try:
            with sandbox.opened():
                return "an unreachable spawner opened a sandbox"
        except Exception as failure:
            return failure

    def reset(self):
        """Returns:
        :func:`refusal_cause` of an open against a listener that accepts the
        connection and closes it without reading the open.
        """
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

        def closing_unread():
            connection, _address = listener.accept()
            connection.close()

        with listener:
            listener.bind(str(self.path))
            listener.listen()
            listener.settimeout(JOIN_SECONDS)
            closing = threading.Thread(target=closing_unread)
            closing.start()
            cause = refusal_cause(self.failed())
            closing.join(JOIN_SECONDS)
        self.path.unlink()
        self.assertFalse(closing.is_alive())
        return cause

    def unreachable(self):
        """Returns:
        ``{"missing": cause, "refused": cause}``: :func:`refusal_cause` of an
        open against a socket path nothing is bound to and against a socket
        that listens no more.
        """
        causes = {"missing": refusal_cause(self.failed())}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
            stale.bind(str(self.path))
        causes["refused"] = refusal_cause(self.failed())
        self.path.unlink()
        return causes

    def test_a_spawner_closing_the_open_unread_fails_it(self):
        self.assertIn(self.reset(), RESETS)

    def test_a_missing_or_refusing_socket_fails_the_open(self):
        self.assertEqual(
            self.unreachable(),
            {
                "missing": os.strerror(errno.ENOENT),
                "refused": os.strerror(errno.ECONNREFUSED),
            },
        )

    def test_negative_control_a_handshake_catching_timeouts_alone_lets_both_out(self):
        with mock.patch.object(sandbox, "OSError", TimeoutError, create=True):
            reset, unreachable = self.reset(), self.unreachable()
        self.assertIn(reset, {"ConnectionResetError", "BrokenPipeError"})
        self.assertEqual(
            unreachable,
            {"missing": "FileNotFoundError", "refused": "ConnectionRefusedError"},
        )


class NeverRaisedError(Exception):
    pass


def breaking_off(listener, reply, closed):
    """Args:
    listener: the listening socket of a scripted spawner that opens one
        sandbox, reads its run request and closes the connection mid-run.
    reply: the line it answers the run request with first, ``None`` for
        none.
    closed: the event it sets once the connection is closed.
    """
    connection, _address = listener.accept()
    with connection:
        channel = sandbox.Channel(connection)
        channel.receive()
        channel.send(sandbox.QUEUED)
        channel.send({"uid": FIRST, "task": str(ROOT / str(FIRST) / sandbox.TASK)})
        _request, descriptors = channel.receive()
        sandbox.close_all(descriptors)
        if reply is not None:
            channel.send(reply)
    closed.set()


class TestCloseBrokenOff(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base)
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.listener.close)
        self.listener.bind(str(sandbox.socket_path(self.base)))
        self.listener.listen()
        self.listener.settimeout(JOIN_SECONDS)
        self.sink = os.open(os.devnull, os.O_WRONLY)
        self.addCleanup(os.close, self.sink)
        for plant in (
            mock.patch.object(sandbox.tempfile, "tempdir", str(self.base)),
            mock.patch.object(sandbox, "OPEN_SECONDS", JOIN_SECONDS),
        ):
            plant.start()
            self.addCleanup(plant.stop)

    def broken_off(self, reply):
        """Args:
            reply: see :func:`breaking_off`; with a reply, the run waits for
                its end, which raises first.

        Returns:
            ``(failure, caught)``: what :func:`sandbox.opened` raised once
            the spawner closed the connection of a started run, and whether
            ``provision.FAILURES`` catches it, so the run ends with its
            ``failed:`` line.
        """
        closed = threading.Event()
        scripted = threading.Thread(
            target=breaking_off, args=(self.listener, reply, closed)
        )
        scripted.start()
        failure = None
        try:
            with sandbox.opened() as task:
                box = sandbox.of(task)
                box.start(sandbox.TOFU, ["init"], {}, self.sink)
                closed.wait(JOIN_SECONDS)
                if reply is not None:
                    box.ended(JOIN_SECONDS)
        except Exception as raised:
            failure = raised
        scripted.join(JOIN_SECONDS)
        self.assertFalse(scripted.is_alive())
        return failure, isinstance(failure, provision.FAILURES)

    def test_a_spawner_breaking_the_connection_off_fails_the_run(self):
        prefix = f"the spawner broke off the sandbox {FIRST}: "
        ended, caught = self.broken_off(BROKEN_OFF)
        self.assertEqual((str(ended), caught), (prefix + BROKEN_OFF["error"], True))
        left, caught = self.broken_off(None)
        pipe = f"[Errno {errno.EPIPE}] {os.strerror(errno.EPIPE)}"
        self.assertEqual((str(left), caught), (prefix + pipe, True))

    def test_negative_control_an_unguarded_close_lets_the_broken_pipe_out(self):
        with mock.patch.object(sandbox, "OSError", NeverRaisedError, create=True):
            outcomes = [self.broken_off(reply) for reply in (BROKEN_OFF, None)]
        self.assertEqual(
            [(type(failure), caught) for failure, caught in outcomes],
            [(BrokenPipeError, False)] * 2,
        )


def expired(seconds):
    """Args:
        seconds: a bound of :func:`sandbox.opened`.

    Returns:
        Once a socket timeout of ``seconds``, the kind that bounds the open,
        fired on a connection no peer writes to, so at least that bound
        passed.
    """
    reader, writer = socket.socketpair()
    with reader, writer:
        reader.settimeout(seconds)
        with contextlib.suppress(TimeoutError):
            reader.recv(1)


def unacknowledged(send):
    """Args:
        send: :meth:`sandbox.Channel.send`.

    Returns:
        It planted as a spawner that never sends :data:`sandbox.QUEUED`.
    """

    def sending(channel, message, descriptors=()):
        if message != sandbox.QUEUED:
            send(channel, message, descriptors)

    return sending


def kept_open(serve, released):
    """Args:
        serve: :meth:`spawner.Spawner.serve` of a fake spawner.
        released: the event that ends the planted serve.

    Returns:
        It planted as a serve that swallows the failure of its open and holds
        a duplicate of its connection until ``released`` is set, so the
        connection stays open after its serve thread died.
    """

    def serving(connection):
        with connection.dup():
            with contextlib.suppress(RuntimeError):
                serve(connection)
            released.wait(JOIN_SECONDS)

    return serving


class TestOpenBurst(unittest.TestCase):
    def setUp(self):
        self.base = harness_directory()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        tempdir = mock.patch.object(sandbox.tempfile, "tempdir", str(self.base))
        tempdir.start()
        self.addCleanup(tempdir.stop)
        self.fake = FakeSpawner(
            spawner,
            self.base / "sandboxes",
            self.base,
            Path(sys.executable),
            provision.OPENTOFU / "tofurc",
        )
        self.addCleanup(self.fake.close)
        self.released = threading.Event()
        self.addCleanup(self.released.set)

    def burst(self, *plants):
        """Args:
            plants: patchers active for the burst, a spawner that sends no
                :data:`sandbox.QUEUED` for a control.

        Returns:
            ``(tasks, failures)`` of :data:`BURST` concurrent
            :func:`sandbox.opened` bounded by :data:`BURST_BOUND`, whose
            allocations wait on a walk for leftovers that returns only once
            every open reached its allocation and the bound passed twice
            over after that; each sandbox stays open until every one of them
            opened, so no two of them can take one uid in turn.
        """
        queued = threading.Barrier(BURST + 1)
        opened = threading.Barrier(BURST)
        allocate = self.fake.spawner.allocate
        leftovers = self.fake.privileges.leftovers
        tasks, failures = [], []

        def allocating():
            queued.wait(JOIN_SECONDS)
            return allocate()

        def walked(uid):
            self.released.wait(JOIN_SECONDS)
            return leftovers(uid)

        def opening():
            try:
                with sandbox.opened() as task:
                    tasks.append(task)
                    opened.wait(JOIN_SECONDS)
            except sandbox.SandboxError as failure:
                failures.append(str(failure))

        openers = [threading.Thread(target=opening, daemon=True) for _ in range(BURST)]
        with contextlib.ExitStack() as stack:
            for plant in (
                mock.patch.object(sandbox, "OPEN_SECONDS", BURST_BOUND),
                mock.patch.object(self.fake.spawner, "allocate", allocating),
                mock.patch.object(self.fake.privileges, "leftovers", walked),
                *plants,
            ):
                stack.enter_context(plant)
            for opener in openers:
                opener.start()
            queued.wait(JOIN_SECONDS)
            expired(2 * BURST_BOUND)
            self.released.set()
            for opener in openers:
                opener.join(JOIN_SECONDS)
        self.assertEqual([o for o in openers if o.is_alive()], [])
        return tasks, failures

    def test_a_burst_of_opens_outlasts_the_bound_while_it_waits_for_a_uid(self):
        tasks, failures = self.burst()
        self.assertEqual(failures, [])
        self.assertEqual(len(set(tasks)), BURST)

    def test_negative_control_without_the_ack_the_burst_fails_its_bound(self):
        plant = mock.patch.object(
            sandbox.Channel, "send", unacknowledged(sandbox.Channel.send)
        )
        tasks, failures = self.burst(plant)
        self.assertEqual(tasks, [])
        within = f"the spawner opened no sandbox within {BURST_BOUND} seconds"
        self.assertEqual(failures, [within] * BURST)

    def died_behind_the_ack(self, *plants):
        """Args:
            plants: patchers active for the open, a serve that swallows the
                failure and keeps its connection open for a control.

        Returns:
            ``(waiting, failures)``: whether :func:`sandbox.opened` bounded
            by :data:`BURST_BOUND` still waited twice that bound after its
            serve thread died behind :data:`sandbox.QUEUED`, and what it
            raised once the connection closed, at the latest after
            :attr:`released`.
        """
        failures = []
        allocating = threading.Event()

        def opening():
            try:
                with sandbox.opened():
                    failures.append("a dead serve thread opened a sandbox")
            except sandbox.SandboxError as failure:
                failures.append(str(failure))

        def dying():
            allocating.set()
            raise RuntimeError("can't start new thread")

        opener = threading.Thread(target=opening, daemon=True)
        with contextlib.ExitStack() as stack:
            for plant in (
                mock.patch.object(sandbox, "OPEN_SECONDS", BURST_BOUND),
                mock.patch.object(self.fake.spawner, "allocate", dying),
                *plants,
            ):
                stack.enter_context(plant)
            opener.start()
            allocating.wait(JOIN_SECONDS)
            opener.join(2 * BURST_BOUND)
            waiting = opener.is_alive()
            self.released.set()
            opener.join(JOIN_SECONDS)
        self.assertFalse(opener.is_alive())
        return waiting, failures

    def test_a_serve_thread_dying_after_the_ack_fails_the_open(self):
        self.assertEqual(
            self.died_behind_the_ack(),
            (False, ["the spawner opened no sandbox: None"]),
        )

    def test_negative_control_a_serve_keeping_its_connection_blocks_the_open(self):
        keeping = kept_open(self.fake.spawner.serve, self.released)
        plant = mock.patch.object(self.fake.spawner, "serve", keeping)
        self.assertEqual(
            self.died_behind_the_ack(plant),
            (True, ["the spawner opened no sandbox: None"]),
        )


ENDINGS = (("return", False, 0), ("fail", False, 1), ("trap", True, 1))


class TestSandboxLifetime(TofuCase):
    def session_child(self, sigint, alarm=False):
        """Args:
            sigint: the SIGINT behaviour of the fake tofu.
            alarm: whether the run budget ends once tofu is ready.

        Returns:
            ``(exit code of the run, pid of the child the fake tofu started
            in a session of its own)``.
        """
        self.plugin = "session"
        if alarm:
            self.when(self.ready, self.send(signal.SIGALRM))
        code, _ = self.run_apply(sigint, dt.timedelta(seconds=READY_BOUND))
        return code, self.tofu_report()["plugin"]

    def assert_gone(self, pid):
        state = self.stat(pid)
        if state is not None and state[0] != "Z":
            os.kill(pid, signal.SIGKILL)
            self.fail(f"the child {pid} in a session of its own outlived its call")

    def test_no_process_of_a_sandbox_outlives_its_call(self):
        for sigint, alarm, expected in ENDINGS:
            with self.subTest(sigint=sigint):
                self.ready.unlink(missing_ok=True)
                self.helpers = []
                code, child = self.session_child(sigint, alarm=alarm)
                self.assertEqual(code, expected)
                self.assertNotEqual(child, 0)
                self.assert_gone(child)

    def test_the_task_directory_is_gone_after_the_run(self):
        code, child = self.session_child("return")
        self.assertEqual(code, 0)
        self.assertIsNotNone(self.task)
        self.assertFalse(self.task.exists())
        self.assertFalse(self.task.parent.exists())
        self.assertEqual(list((self.root / "sandboxes").iterdir()), [])
        self.assert_gone(child)


if __name__ == "__main__":
    unittest.main()
