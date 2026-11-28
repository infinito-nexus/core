from __future__ import annotations

import base64
import importlib.util
import io
import os
import subprocess
import sys
import threading
import time
import unittest
import unittest.mock as mock
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout

from jinja2 import Environment, nodes

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE
from utils.roles.swarm_loopback import in_compose_branch

ROLE_DIR = PROJECT_ROOT / "roles/web-svc-seaweedfs"
PROBE_DIR = ROLE_DIR / "files/test"
TEST_ENV = ROLE_DIR / "templates/test.env.j2"
COMPOSE = ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE
CONTAINER_BASE = "roles/sys-svc-container/templates/base.yml.j2"
sys.path.insert(0, str(PROBE_DIR))

spec = importlib.util.spec_from_file_location(
    "seaweedfs_engine_probe", PROBE_DIR / "probe.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
s3_engine = sys.modules["s3_engine"]
access_checks = sys.modules["access_checks"]
restart_race = sys.modules["restart_race"]

ADMIN = ("ADMINKEY", "adminsecret")
BUCKET = "matrix"
KEY = "infinito-engine-check/0123-restart-race"
WINDOW = 0.05
STALL = 0.2
GIVE_UP = 0.01
TIMING = {"interval": 0.005, "settle": 0.02, "timeout": 0.3}
DOWN = "down"
LOADING = "loading"
LOADED = "loaded"


def update_order_at_container_base(source: str) -> str | None:
    """
    Args:
        source: the text of the role's compose template.

    Returns:
        The ``service_update_order`` an unconditional ``set`` holds where the
        container base is included, or None when none is set there.
    """
    state: dict = {"order": None, "seen": False}

    def walk(node, branched: bool) -> None:
        if state["seen"]:
            return
        if (
            not branched
            and isinstance(node, nodes.Assign)
            and isinstance(node.target, nodes.Name)
            and node.target.name == "service_update_order"
        ):
            state["order"] = node.node.as_const()
        if (
            isinstance(node, nodes.Include)
            and isinstance(node.template, nodes.Const)
            and node.template.value == CONTAINER_BASE
        ):
            state["seen"] = True
            return
        for child in node.iter_child_nodes():
            walk(child, branched or isinstance(node, (nodes.If, nodes.For)))

    walk(Environment(autoescape=True).parse(source), False)
    return state["order"] if state["seen"] else None


class FakeEngine:
    def __init__(
        self,
        *,
        served_while_loading: bool = False,
        stalls: bool = False,
        stalled_writes_land: bool = False,
    ) -> None:
        self.state = LOADED
        self.served_while_loading = served_while_loading
        self.stalls = stalls
        self.stalled_writes_land = stalled_writes_land
        self.anonymous_lost = False
        self.writes: list[str] = []
        self.landed: set[str] = set()

    def request(
        self,
        method,
        path,
        *,
        query=None,
        payload=b"",
        access_key="",
        secret_key="",
        timeout=None,
    ):
        state = self.state
        if state == DOWN:
            if self.stalls and not access_key:
                time.sleep(STALL if timeout is None else min(STALL, timeout))
                if self.stalled_writes_land:
                    self.landed.add(path)
                return 0, b"timed out", {}
            return 0, b"[Errno 111] Connection refused", {}
        if access_key:
            if state != LOADED:
                return 503, b"", {}
            if path == "/" or path in self.landed:
                return 200, b"", {}
            return 404, b"<Error><Code>NoSuchKey</Code></Error>", {}
        if self.anonymous_lost:
            return 0, b"timed out", {}
        self.writes.append(path)
        if state == LOADING and self.served_while_loading:
            return 200, b"", {}
        return 403, b"<Error><Code>AccessDenied</Code></Error>", {}


def restart(
    engine: FakeEngine,
    *,
    goes_down: bool = True,
    loads: bool = True,
    anonymous_lost: bool = False,
):
    def run() -> list[str]:
        if goes_down:
            engine.state = DOWN
            engine.anonymous_lost = anonymous_lost
            time.sleep(WINDOW)
            engine.state = LOADING
            time.sleep(WINDOW)
        if loads:
            engine.state = LOADED
        return []

    return run


def race(engine: FakeEngine, restarter, **timing) -> list[str]:
    with mock.patch.object(restart_race, "RACE_REQUEST_TIMEOUT", GIVE_UP):
        return restart_race.check_restart_serves_no_anonymous_write(
            engine, ADMIN, BUCKET, KEY, restarter, **{**TIMING, **timing}
        )


class TestRestartRace(unittest.TestCase):
    def test_no_anonymous_write_is_served_across_a_restart(self) -> None:
        engine = FakeEngine()
        self.assertEqual(race(engine, restart(engine)), [])
        self.assertEqual(set(engine.writes), {f"/{BUCKET}/{KEY}"})

    def test_negative_control_a_write_served_before_the_identities_load_is_caught(
        self,
    ) -> None:
        engine = FakeEngine(served_while_loading=True)
        (failure,) = race(engine, restart(engine))
        self.assertIn(f"/{BUCKET}/{KEY} answered 200", failure)

    def test_negative_control_a_loop_that_never_meets_the_restart_is_caught(
        self,
    ) -> None:
        engine = FakeEngine()
        (failure,) = race(engine, restart(engine, goes_down=False))
        self.assertIn("never spanned the restart", failure)

    def test_a_write_stalled_by_the_restart_gives_up_and_the_loop_goes_on(
        self,
    ) -> None:
        engine = FakeEngine(stalls=True)
        self.assertEqual(race(engine, restart(engine)), [])
        self.assertEqual(set(engine.writes), {f"/{BUCKET}/{KEY}"})
        self.assertEqual(engine.landed, set())

    def test_a_stalled_write_that_lands_after_the_give_up_is_caught(self) -> None:
        engine = FakeEngine(stalls=True, stalled_writes_land=True)
        (failure,) = race(engine, restart(engine))
        self.assertEqual(
            f"F: an anonymous write landed during the restart: /{BUCKET}/{KEY} exists",
            failure,
        )

    def test_negative_control_a_write_served_while_a_stalling_engine_loads_is_caught(
        self,
    ) -> None:
        engine = FakeEngine(served_while_loading=True, stalls=True)
        (failure,) = race(engine, restart(engine))
        self.assertIn(f"/{BUCKET}/{KEY} answered 200", failure)

    def test_negative_control_an_engine_lost_to_anonymous_writes_is_caught(
        self,
    ) -> None:
        engine = FakeEngine()
        (failure,) = race(engine, restart(engine, anonymous_lost=True))
        self.assertIn("never saw it start again", failure)

    def test_an_engine_that_never_loads_its_identities_fails(self) -> None:
        engine = FakeEngine()
        failures = race(engine, restart(engine, loads=False), timeout=0.05)
        self.assertTrue(any("loaded no identities" in failure for failure in failures))

    def test_a_failed_restart_is_reported(self) -> None:
        engine = FakeEngine()
        failures = race(engine, lambda: ["F: container restart x failed: gone"])
        self.assertIn("F: container restart x failed: gone", failures)
        self.assertTrue(
            any("never spanned the restart" in failure for failure in failures)
        )


class TestNoWriteLanded(unittest.TestCase):
    def _check(self, status: int) -> tuple[list[str], mock.Mock]:
        engine = mock.Mock()
        engine.request.return_value = (status, b"", {})
        failures = restart_race.check_no_write_landed(engine, ADMIN, f"/{BUCKET}/{KEY}")
        return failures, engine

    def test_a_missing_object_passes_and_is_read_as_admin(self) -> None:
        failures, engine = self._check(404)
        self.assertEqual([], failures)
        engine.request.assert_called_once_with(
            "GET", f"/{BUCKET}/{KEY}", access_key=ADMIN[0], secret_key=ADMIN[1]
        )

    def test_negative_control_an_existing_object_is_caught(self) -> None:
        (failure,) = self._check(200)[0]
        self.assertIn("landed during the restart", failure)

    def test_an_admin_read_without_an_answer_is_a_failure(self) -> None:
        (failure,) = self._check(0)[0]
        self.assertIn("answered nothing instead of 404", failure)

    def test_an_admin_read_that_is_refused_is_a_failure(self) -> None:
        (failure,) = self._check(403)[0]
        self.assertIn("answered 403 instead of 404", failure)


class SlowBody(io.BytesIO):
    def read(self, *args):
        raise TimeoutError("timed out")


class TestEngine(unittest.TestCase):
    def _send(self, body: io.BytesIO) -> tuple[int, bytes, dict[str, str]]:
        refused = urllib.error.HTTPError(
            f"{LOOPBACK}/{BUCKET}/{KEY}",
            403,
            "Forbidden",
            {"Content-Type": "application/xml"},
            body,
        )
        engine = s3_engine.Engine(LOOPBACK, "us-east-1")
        with mock.patch.object(
            urllib.request.OpenerDirector, "open", side_effect=refused
        ):
            return engine.request(
                "PUT", f"/{BUCKET}/{KEY}", payload=b"x", timeout=GIVE_UP
            )

    def test_an_error_status_whose_body_times_out_keeps_its_status(self) -> None:
        status, body, headers = self._send(SlowBody())
        self.assertEqual((403, b""), (status, body))
        self.assertEqual("application/xml", headers["Content-Type"])

    def test_negative_control_an_error_body_that_arrives_is_returned(self) -> None:
        status, body, _ = self._send(io.BytesIO(b"<Error/>"))
        self.assertEqual((403, b"<Error/>"), (status, body))


def completed(
    stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class TestRestartContainer(unittest.TestCase):
    def _restart(self, before: str, after: str, returncode: int = 0) -> list[str]:
        answers = [
            completed(before),
            completed(returncode=returncode),
            completed(after),
        ]
        with mock.patch.object(
            restart_race.subprocess, "run", side_effect=answers
        ) as run:
            failures = restart_race.restart_container("seaweedfs")
        self.assertEqual(
            run.call_args_list[1].args[0], ["container", "restart", "seaweedfs"]
        )
        return failures

    def test_a_new_start_time_proves_the_restart(self) -> None:
        self.assertEqual(
            self._restart("2026-11-14T10:00:00Z", "2026-11-14T10:05:00Z"), []
        )

    def test_negative_control_an_unchanged_start_time_is_caught(self) -> None:
        (failure,) = self._restart("2026-11-14T10:00:00Z", "2026-11-14T10:00:00Z")
        self.assertIn("never restarted", failure)

    def test_a_failed_restart_command_is_reported(self) -> None:
        (failure,) = self._restart("2026-11-14T10:00:00Z", "", returncode=1)
        self.assertIn("container restart seaweedfs failed", failure)


SERVICE = "seaweedfs_seaweedfs"
LOOPBACK = "http://127.0.0.1:8333"
AUTH = "SEAWEEDFS_TEST_AUTHORIZATION"
SECRETS = ("ADMINKEY", "adminsecret", "MASTODONKEY", "mastodonsecret", "Signature=")
OUTAGE = 0.4
PS = [
    "container",
    "ps",
    "--filter",
    f"label=com.docker.swarm.service.name={SERVICE}",
    "--filter",
    "status=running",
    "--format",
    "{{.ID}}",
]
UPDATE = ["container", "service", "update", "--force", "--quiet", SERVICE]
TIMEOUT_FAILURE = "F: the engine loaded no identities within 300s of its restart"


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def _http(status: int, body: bytes = b"") -> bytes:
    return (
        f"HTTP/1.1 {status} X\r\nContent-Type: application/xml\r\n\r\n".encode() + body
    )


def _done(stdout: str | bytes = "", returncode: int = 0, stderr: str | bytes = ""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _after(words: list[str], flag: str) -> str:
    return words[words.index(flag) + 1] if flag in words[:-1] else ""


def _holds(words: list[str], window: list[str]) -> bool:
    return any(
        words[start : start + len(window)] == window
        for start in range(len(words) - len(window) + 1)
    )


class FakeSwarmNode:
    def __init__(self, *, loads: bool = True) -> None:
        self.loads = loads
        self.containers: dict[str, dict[str, object]] = {
            "decoy": {"service": "mastodon_mastodon", "running": True, "loaded": True}
        }
        self.objects: dict[str, bytes] = {}
        self.calls: list[list[str]] = []
        self.leaks: list[str] = []
        self.lock = threading.Lock()
        self._start(loaded=True)

    def _start(self, *, loaded: bool) -> str:
        with self.lock:
            cid = f"cid{len(self.containers)}"
            self.containers[cid] = {
                "service": SERVICE,
                "running": True,
                "loaded": loaded,
                "started": f"2026-11-20T03:06:{len(self.containers):02d}Z",
            }
        return cid

    def _snapshot(self) -> list[tuple[str, dict[str, object]]]:
        with self.lock:
            return list(self.containers.items())

    def running(self) -> list[str]:
        return [
            cid
            for cid, state in self._snapshot()
            if state["service"] == SERVICE and state["running"]
        ]

    def run(self, argv, **kwargs):
        with self.lock:
            self.calls.append(list(argv))
            self.leaks += [w for w in argv if any(s in w for s in SECRETS)]
        args = list(argv[1:])
        if args[0] == "ps":
            return _done(self._ps(args[1:]))
        if args[0] == "inspect":
            state = self.containers.get(args[-1])
            return _done(str(state["started"]) if state else "", 0 if state else 1)
        if args[0] == "restart":
            return self._restart_task_container(args[-1])
        if args == UPDATE[1:]:
            for cid in self.running():
                self.containers[cid]["running"] = False
            time.sleep(OUTAGE)
            self._start(loaded=self.loads)
            return _done()
        if args[0] == "exec":
            return self._exec(args, kwargs.get("input") or b"", kwargs.get("env") or {})
        return _done(returncode=1, stderr="unsupported by the fake node")

    def _ps(self, args: list[str]) -> str:
        filters = [
            _after(args[i:], "--filter") for i, w in enumerate(args) if w == "--filter"
        ]
        labels = [f.removeprefix("label=") for f in filters if f.startswith("label=")]
        found = [
            cid
            for cid, state in self._snapshot()
            if all(
                label == f"com.docker.swarm.service.name={state['service']}"
                for label in labels
            )
            and (state["running"] or "status=running" not in filters)
        ]
        return "".join(f"{cid}\n" for cid in found)

    def _restart_task_container(self, cid: str):
        state = self.containers.get(cid)
        if not state:
            return _done(returncode=1, stderr=f"no such container {cid}")
        state["running"] = False
        time.sleep(OUTAGE)
        state["running"] = True
        state["started"] = "2026-11-20T03:06:59Z"
        self._start(loaded=self.loads)
        return _done()

    def _exec(self, args: list[str], payload: bytes, env: dict[str, str]):
        signed = args[2:4] == ["-e", AUTH]
        container = args[4] if signed else args[2]
        state = self.containers.get(container)
        if not state or not state["running"]:
            return _done(b"", 1, f"container {container} is not running".encode())
        curl = args[args.index("curl") :]
        url = urllib.parse.urlsplit(curl[-1])
        if url.netloc != "127.0.0.1:8333":
            return _done(b"", 7, b"curl: (7) Failed to connect")
        if not signed:
            return _done(_http(403, b"<Error><Code>AccessDenied</Code></Error>"))
        if (
            _after(curl, "--variable") != f"%{AUTH}"
            or _after(curl, "--expand-header") != "Authorization: {{" + AUTH + "}}"
            or not env.get(AUTH, "").startswith("AWS4-HMAC-SHA256 Credential=")
        ):
            return _done(
                _http(400, b"<Error><Code>MissingSecurityHeader</Code></Error>")
            )
        if not state["loaded"]:
            return _done(_http(503, b"<Error><Code>ServiceUnavailable</Code></Error>"))
        method = _after(curl, "-X") or "GET"
        if url.path == "/" or url.query:
            return _done(_http(200, b"<ListAllMyBucketsResult/>"))
        if method == "PUT" and _holds(curl, ["--data-binary", "@-"]):
            self.objects[url.path] = payload
            return _done(_http(200))
        if method == "DELETE":
            self.objects.pop(url.path, None)
            return _done(_http(204))
        if method == "GET" and url.path in self.objects:
            return _done(_http(200, self.objects[url.path]))
        return _done(_http(404))


class FastClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        self.now += 60.0
        return self.now

    def sleep(self, seconds: float) -> None:
        time.sleep(min(seconds, 0.5))


SWARM_ENV = {
    "SEAWEEDFS_TEST_REGION": "us-east-1",
    "SEAWEEDFS_TEST_SWARM_SERVICE": SERVICE,
    "SEAWEEDFS_TEST_LOOPBACK_URL": LOOPBACK,
    "SEAWEEDFS_TEST_LOCAL_URL": "http://0.0.0.0:8085",
    "SEAWEEDFS_TEST_CONTAINER": "cid1",
    "SEAWEEDFS_TEST_BIND_HOST": "127.0.0.1",
    "SEAWEEDFS_TEST_FILER_PORT": "8888",
    "SEAWEEDFS_TEST_MASTER_PORT": "9333",
    "SEAWEEDFS_TEST_ADMIN_ACCESS_KEY_B64": _b64("ADMINKEY"),
    "SEAWEEDFS_TEST_ADMIN_SECRET_KEY_B64": _b64("adminsecret"),
    "SEAWEEDFS_TEST_PRIMARY_BUCKET": "mastodon",
    "SEAWEEDFS_TEST_PRIMARY_IS_PUBLIC": "false",
    "SEAWEEDFS_TEST_PRIMARY_ACCESS_KEY_B64": _b64("MASTODONKEY"),
    "SEAWEEDFS_TEST_PRIMARY_SECRET_KEY_B64": _b64("mastodonsecret"),
    "SEAWEEDFS_TEST_OTHER_BUCKET": "",
    "SEAWEEDFS_TEST_PUBLIC_BUCKET": "",
    "SEAWEEDFS_TEST_PUBLIC_ACCESS_KEY_B64": "",
    "SEAWEEDFS_TEST_PUBLIC_SECRET_KEY_B64": "",
}


def _probe_on(node: FakeSwarmNode) -> tuple[int, list[str], mock.MagicMock]:
    refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.dict(probe.os.environ, SWARM_ENV, clear=True),
        mock.patch.object(subprocess, "run", side_effect=node.run),
        mock.patch.object(
            urllib.request.OpenerDirector, "open", side_effect=refused
        ) as host_port,
        mock.patch.object(
            access_checks.socket,
            "create_connection",
            side_effect=ConnectionRefusedError,
        ),
        mock.patch.object(restart_race, "time", FastClock()),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        status = probe.main()
    return status, err.getvalue().splitlines(), host_port


class TestSwarmProbe(unittest.TestCase):
    def test_swarm_reaches_the_gateway_in_its_container_and_never_the_host_port(
        self,
    ) -> None:
        node = FakeSwarmNode()
        status, failures, host_port = _probe_on(node)
        self.assertEqual([], failures)
        self.assertEqual(0, status)
        host_port.assert_not_called()
        self.assertEqual([], node.leaks)
        self.assertEqual(["cid2"], node.running())
        self.assertIn(UPDATE, node.calls)
        self.assertNotIn("restart", [call[1] for call in node.calls])
        lookups = [call for call in node.calls if call[1] == "ps"]
        self.assertTrue(lookups)
        self.assertTrue(all(call == PS for call in lookups), lookups)

    def test_negative_control_a_replacement_that_never_loads_its_identities_times_out(
        self,
    ) -> None:
        node = FakeSwarmNode(loads=False)
        status, failures, host_port = _probe_on(node)
        self.assertEqual(1, status)
        self.assertEqual([f"[FAIL] {TIMEOUT_FAILURE}"], failures)
        host_port.assert_not_called()
        self.assertIn(UPDATE, node.calls)

    def test_the_restart_check_leaves_one_engine_on_the_data_directory(
        self,
    ) -> None:
        node = FakeSwarmNode()
        _probe_on(node)
        self.assertEqual(["cid2"], node.running())
        self.assertNotIn(["container", "restart", "cid1"], node.calls)


class TestContainerEngine(unittest.TestCase):
    def _engine(self, *cids: str):
        resolve = mock.Mock(side_effect=list(cids))
        return s3_engine.ContainerEngine(LOOPBACK, "us-east-1", resolve), resolve

    def test_a_signed_request_passes_the_signature_through_the_environment_only(
        self,
    ) -> None:
        engine, _ = self._engine("cid1")
        payload = b"blob\r\n\r\ntail"
        with mock.patch.object(
            s3_engine.subprocess, "run", return_value=_done(_http(200, payload))
        ) as run:
            status, body, headers = engine.request(
                "PUT",
                "/mastodon/k",
                payload=payload,
                access_key="ADMINKEY",
                secret_key="adminsecret",
            )
        self.assertEqual((200, payload), (status, body))
        self.assertEqual("application/xml", headers["Content-Type"])
        argv = run.call_args.args[0]
        self.assertEqual(
            ["container", "exec", "-i", "-e", AUTH, "cid1", "curl", "-sS", "-i"],
            argv[:9],
        )
        self.assertTrue(_holds(argv, ["-X", "PUT", "-H", "Expect:"]), argv)
        self.assertTrue(
            _holds(
                argv,
                [
                    "--variable",
                    f"%{AUTH}",
                    "--expand-header",
                    "Authorization: {{" + AUTH + "}}",
                ],
            ),
            argv,
        )
        self.assertTrue(_holds(argv, ["--data-binary", "@-"]), argv)
        self.assertEqual(f"{LOOPBACK}/mastodon/k", argv[-1])
        self.assertEqual([], [w for w in argv if any(s in w for s in SECRETS)])
        self.assertFalse([w for w in argv if w.startswith("Authorization: AWS4")])
        env = run.call_args.kwargs["env"]
        self.assertTrue(env[AUTH].startswith("AWS4-HMAC-SHA256 Credential=ADMINKEY/"))
        self.assertIn("Signature=", env[AUTH])
        self.assertLessEqual(set(os.environ), set(env))
        self.assertEqual(payload, run.call_args.kwargs["input"])

    def test_an_unsigned_request_carries_no_credential(self) -> None:
        engine, _ = self._engine("cid1")
        with mock.patch.object(
            s3_engine.subprocess, "run", return_value=_done(_http(403, b"<Error/>"))
        ) as run:
            status, _, _ = engine.request("GET", "/")
        argv = run.call_args.args[0]
        self.assertEqual(403, status)
        self.assertEqual(["container", "exec", "-i", "cid1", "curl"], argv[:5])
        self.assertNotIn("--variable", argv)
        self.assertNotIn("--data-binary", argv)
        self.assertIsNone(run.call_args.kwargs["env"])

    def test_the_container_is_resolved_once_while_execs_succeed(self) -> None:
        engine, resolve = self._engine("cid1")
        with mock.patch.object(
            s3_engine.subprocess, "run", return_value=_done(_http(403))
        ) as run:
            for _ in range(3):
                engine.request("PUT", "/mastodon/k", payload=b"x")
        self.assertEqual(1, resolve.call_count)
        self.assertEqual(3, run.call_count)

    def test_a_failed_exec_resolves_the_container_again(self) -> None:
        engine, resolve = self._engine("cid1", "cid2")
        answers = [
            _done(_http(403)),
            _done(b"", 1, b"container cid1 is not running"),
            _done(_http(403)),
        ]
        with mock.patch.object(s3_engine.subprocess, "run", side_effect=answers) as run:
            statuses = [engine.request("GET", "/")[0] for _ in range(3)]
        self.assertEqual([403, 0, 403], statuses)
        self.assertEqual(2, resolve.call_count)
        self.assertEqual(
            ["cid1", "cid1", "cid2"], [call.args[0][3] for call in run.call_args_list]
        )

    def test_no_running_container_is_no_answer_without_an_exec(self) -> None:
        engine, _ = self._engine("")
        with mock.patch.object(s3_engine.subprocess, "run") as run:
            self.assertEqual(0, engine.request("GET", "/")[0])
        run.assert_not_called()

    def test_output_without_a_status_line_is_no_answer(self) -> None:
        self.assertEqual(0, s3_engine.parse_response(b"curl: (7) Failed to connect")[0])


class TestRunningContainer(unittest.TestCase):
    def _lookup(self, listed: str) -> tuple[str, mock.MagicMock]:
        with mock.patch.object(
            restart_race.subprocess, "run", return_value=_done(listed)
        ) as run:
            found = restart_race.running_container(SERVICE)
        return found, run

    def test_the_lookup_filters_on_the_service_label_and_the_running_state(
        self,
    ) -> None:
        found, run = self._lookup("cid1\n")
        self.assertEqual("cid1", found)
        self.assertEqual(PS, run.call_args.args[0])

    def test_no_running_container_is_empty(self) -> None:
        self.assertEqual("", self._lookup("")[0])

    def test_two_running_engines_fail_loudly(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, r"\(cid1, cid2\).*one data directory"
        ):
            self._lookup("cid1\ncid2\n")


class TestRestartService(unittest.TestCase):
    def _restart(self, before: str, after: str, returncode: int = 0) -> list[str]:
        answers = [
            _done(before),
            _done(returncode=returncode, stderr="boom"),
            _done(after),
        ]
        with mock.patch.object(
            restart_race.subprocess, "run", side_effect=answers
        ) as run:
            failures = restart_race.restart_service(SERVICE)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual([PS, UPDATE, PS][: len(calls)], calls)
        return failures

    def test_a_replaced_task_proves_the_restart(self) -> None:
        self.assertEqual([], self._restart("cid1\n", "cid2\n"))

    def test_negative_control_an_unreplaced_task_is_caught(self) -> None:
        (failure,) = self._restart("cid1\n", "cid1\n")
        self.assertIn("never replaced", failure)

    def test_a_task_that_left_this_node_is_caught(self) -> None:
        (failure,) = self._restart("cid1\n", "")
        self.assertIn("no container of seaweedfs_seaweedfs runs on this node", failure)

    def test_a_failed_update_is_reported(self) -> None:
        (failure,) = self._restart("cid1\n", "", returncode=1)
        self.assertIn("update --force seaweedfs_seaweedfs failed: boom", failure)


class TestRoleTemplates(unittest.TestCase):
    def test_the_host_port_url_renders_only_in_compose(self) -> None:
        text = read_text(str(TEST_ENV))
        self.assertTrue(
            in_compose_branch(text, text.index("SEAWEEDFS_TEST_LOCAL_URL=")),
            "swarm publishes no ports.local port, so the probe MUST NOT get one there",
        )

    def test_swarm_gets_the_service_and_the_loopback_url(self) -> None:
        text = read_text(str(TEST_ENV))
        for name in ("SEAWEEDFS_TEST_SWARM_SERVICE=", "SEAWEEDFS_TEST_LOOPBACK_URL="):
            self.assertIn(name, text)
            self.assertFalse(in_compose_branch(text, text.index(name)), name)

    def test_the_engine_is_stopped_before_its_replacement_starts(self) -> None:
        self.assertEqual(
            update_order_at_container_base(read_text(str(COMPOSE))),
            "stop-first",
            "two engines MUST NOT open one data directory",
        )


SCRIPT_ENV = {
    "PATH": os.environ["PATH"],
    "SEAWEEDFS_TEST_CONTAINER": "cid1",
    "SEAWEEDFS_TEST_IS_STACK_HOST": "true",
    "SEAWEEDFS_TEST_BIND_HOST": "127.0.0.1",
    "SEAWEEDFS_TEST_REGION": "us-east-1",
    "SEAWEEDFS_TEST_FILER_PORT": "8888",
    "SEAWEEDFS_TEST_MASTER_PORT": "9333",
    "SEAWEEDFS_TEST_ADMIN_ACCESS_KEY_B64": _b64("ADMINKEY"),
    "SEAWEEDFS_TEST_ADMIN_SECRET_KEY_B64": _b64("adminsecret"),
    "SEAWEEDFS_TEST_PRIMARY_IS_PUBLIC": "false",
}


class TestTestScript(unittest.TestCase):
    def _run(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(PROBE_DIR / "test.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def test_compose_without_the_host_url_fails_with_its_name(self) -> None:
        done = self._run(SCRIPT_ENV)
        self.assertNotEqual(0, done.returncode)
        self.assertIn("SEAWEEDFS_TEST_LOCAL_URL", done.stderr)

    def test_swarm_without_the_loopback_url_fails_with_its_name(self) -> None:
        done = self._run({**SCRIPT_ENV, "SEAWEEDFS_TEST_SWARM_SERVICE": SERVICE})
        self.assertNotEqual(0, done.returncode)
        self.assertIn("SEAWEEDFS_TEST_LOOPBACK_URL", done.stderr)


if __name__ == "__main__":
    unittest.main()
