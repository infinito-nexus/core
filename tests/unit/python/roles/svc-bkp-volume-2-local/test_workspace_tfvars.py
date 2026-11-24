from __future__ import annotations

import base64
import contextlib
import functools
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import urllib.parse
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_VARS_MAIN,
)

from .test_workspace_order import (
    CATALOG_VOLUME,
    CATALOGS,
    E2E_PROVIDER,
    INTERFACE,
    LOCAL_INCUS,
    ROLE,
    SEMAPHORE_FILES,
    TEST_ENV,
    configured_order,
    e2e_surveys,
    provision_inputs,
    render,
    sourced,
)

WORKSPACE_FILES = ROLE / "files" / "test" / "workspace"
PASS = WORKSPACE_FILES / "pass.sh"
DRILL = WORKSPACE_FILES / "drill.py"
FAKE_DRILL = Path(__file__).resolve().parent / "_fake_drill.py"
SEMAPHORE_SERVICES = SEMAPHORE_FILES.parent / ROLE_FILE_META_SERVICES
SEMAPHORE_VARS = load_yaml_str(
    read_text(str(SEMAPHORE_FILES.parent / ROLE_FILE_VARS_MAIN))
)
OWNER = SEMAPHORE_VARS["SEMAPHORE_WORKSPACES_GITEA_OWNER"]
BRANCH = SEMAPHORE_VARS["SEMAPHORE_WORKSPACES_REPOSITORY_BRANCH"]
ROOT_VARIABLES = (
    SEMAPHORE_FILES / "opentofu" / "roots" / E2E_PROVIDER / "variables.tf.json"
)
TEST_PROVISION = SEMAPHORE_FILES / "playwright" / "test-provision.js"
COMMIT_VALUES = re.compile(
    r"function commitValues\(.*?JSON\.stringify\(\{(.*?)\}\)", re.DOTALL
)
COMMIT_VALUES_KEY = re.compile(r"^\s*(\w+):", re.MULTILINE)
PROVISION_RUNNER = "provision-runner"
CATALOGS_VAR = "BKP_TEST_WORKSPACE_CATALOGS"
STEP_TWO_LINE = (
    f'drill task "${{STATE}}/result-${{IDS[0]}}.json" '
    f'"provision-{E2E_PROVIDER} ws-${{IDS[0]}}" "${{STATE}}/provision-before.log"'
)
STEP_ONE_ECHO = 'echo "workspace drill: step 1 '
COMMIT_CALL = "drill order "
CREATE_CALL = "drill repository create "
SECOND_CREATE = (
    f'    drill repository create "${{STATE}}/result-${{IDS[1]}}.json" '
    f'"provision-{E2E_PROVIDER} ws-${{IDS[1]}}"\n'
)
KEEP_GOING = re.compile(r' \|\| left\+=\("[^"]*"\)')
KEEP_FOR_RETRY = '|| kept="${IDS[0]}"'
DELETE_PAST_FAILED_DESTROY = '|| left+=("the server of ${IDS[0]}")'
NO_COMMIT = (
    "prepare provisions in step 2 without committing the tfvars file of the order"
)
LATE_COMMIT = "prepare commits the tfvars file of the order after step 2"
NO_REPOSITORY = "prepare commits into a repository it never created"
MISSING_REPOSITORY = "prepare leaves a workspace without its repository"
SKIPPED_DESTROY = "a failed step of the cleanup skips a workspace destroy"
HIDDEN_FAILURE = "the cleanup reports success although a step failed"
RETRY_DELETED = "the cleanup deletes what a retried server destroy needs"
OTHER_LEFT = "the cleanup leaves another workspace behind"
WORKSPACE = "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"
ALIAS = f"ws-{WORKSPACE}"
TEMPLATE = f"provision-{E2E_PROVIDER} {ALIAS}"
GIT_URL = f"ssh://git@gitea.example:2201/{OWNER}/{ALIAS}.git"
READ_KEY = "ssh-ed25519 read-key-public-half"
REGION_HOST = "target"
API = "/api/v1"
KEY_RAW = bytes(range(32))
KEY_BLOB = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + KEY_RAW


@functools.cache
def drill() -> object:
    """Returns:
    The role's ``files/test/workspace/drill.py``, loaded as a module.
    """
    spec = spec_from_file_location("bkp_workspace_drill", str(DRILL))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def role_catalog() -> dict:
    """Returns:
    The incus catalog of ``web-app-semaphore``, every region host rendered
    for an inventory that holds the Incus target.
    """
    catalog = load_yaml_any(str(SEMAPHORE_SERVICES))["semaphore"]["workspaces"][
        "catalog"
    ][E2E_PROVIDER]
    return {
        flavor: {
            **entry,
            "regions": {
                region: {**place, "host": REGION_HOST}
                for region, place in entry["regions"].items()
            },
        }
        for flavor, entry in catalog.items()
    }


@functools.cache
def root_variables() -> frozenset[str]:
    """Returns:
    The variables the incus root module declares.
    """
    return frozenset(json.loads(read_text(str(ROOT_VARIABLES)))["variable"])


@functools.cache
def commit_values_keys() -> tuple[str, ...]:
    """Returns:
    The keys of the object ``commitValues`` of ``test-provision.js`` hands
    ``JSON.stringify``, in its order.
    """
    body = COMMIT_VALUES.search(read_text(str(TEST_PROVISION))).group(1)
    return tuple(COMMIT_VALUES_KEY.findall(body))


def commit_values_text(values: dict[str, str]) -> str:
    """Args:
        values: the values of an order line.

    Returns:
        The text ``JSON.stringify`` gives ``commitValues``' object for them:
        its key order and no whitespace.
    """
    pairs = (
        f"{json.dumps(key)}:{json.dumps(values[key])}" for key in commit_values_keys()
    )
    return "{" + ",".join(pairs) + "}"


def tfvars_findings(
    content: bytes, name: str, catalogs: Path, checkout: Path
) -> list[str]:
    """Args:
        content: the bytes of a committed tfvars file.
        name: ``<SALES_ORDER>-<LINE>`` of the order.
        catalogs: the catalog directory the provision runner mounts.
        checkout: an absent directory that becomes the workspace checkout.

    Returns:
        One message per reason the provision runner refuses the file, runs
        another root with it, or it differs from what ``commitValues``
        writes, empty when it is the incus line of the order.
    """
    relative = f"provision/{name}.tfvars.json"
    (checkout / "provision").mkdir(parents=True)
    (checkout / relative).write_bytes(content)
    inputs = provision_inputs()
    interface = json.loads(read_text(str(INTERFACE)))
    try:
        values = inputs.load_tfvars(checkout, name, interface)
        provider = inputs.select_provider(
            inputs.load_catalogs(catalogs, interface), values
        )
    except inputs.RefusedError as error:
        return [str(error)]
    findings = []
    if provider != E2E_PROVIDER:
        findings.append(f"the {provider} root runs the line, not {E2E_PROVIDER}")
    if set(values) != root_variables():
        findings.append(
            f"the line sets {sorted(values)}, not {sorted(root_variables())}"
        )
    if content.decode("utf-8") != commit_values_text(values):
        findings.append("the file differs from the bytes commitValues writes")
    return findings


def run_pass(
    source: str, scratch: Path, action: str, failing: list[str]
) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Args:
        source: a workspace pass script.
        scratch: the directory the script, the fake drill and the state sit
            in; ``prepare`` and ``cleanup`` of one scratch share the state.
        action: the pass action.
        failing: the start of the drill calls that exit 1.

    Returns:
        The finished pass and the drill calls it made, in order.
    """
    script = scratch / "pass.sh"
    script.write_text(source, encoding="utf-8")
    (scratch / "drill.py").write_text(read_text(str(FAKE_DRILL)), encoding="utf-8")
    state = scratch / "state"
    state.mkdir(exist_ok=True)
    log = scratch / f"{action}.jsonl"
    log.touch()
    env = {
        "PATH": os.environ["PATH"],
        "BKP_TEST_PYTHON": sys.executable,
        "BKP_TEST_HEALTH_TIMEOUT": "1",
        "BKP_TEST_WORKSPACE_DIR": str(state),
        CATALOGS_VAR: CATALOGS,
        "BKP_TEST_WORKSPACE_ORDER": json.dumps(configured_order()),
        "FAKE_DRILL_LOG": str(log),
        "FAKE_DRILL_REAL": str(DRILL),
        "FAKE_DRILL_FAIL": json.dumps(failing),
        "FAKE_DRILL_OWNER": OWNER,
        "FAKE_DRILL_BRANCH": BRANCH,
        "FAKE_DRILL_TEMPLATES": json.dumps(sorted(e2e_surveys())),
    }
    finished = subprocess.run(
        ["bash", str(script), action],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    lines = log.read_text(encoding="utf-8").splitlines()  # nocheck: cache-read
    return finished, [json.loads(line) for line in lines]


def applied(calls: list[list[str]]) -> list[str]:
    """Args:
        calls: the drill calls of a pass.

    Returns:
        The workspaces ``workspace apply`` ran for, in order.
    """
    return [call[2] for call in calls if call[:2] == ["workspace", "apply"]]


def prepare_findings(calls: list[list[str]], state: Path) -> list[str]:
    """Args:
        calls: the drill calls of ``pass.sh prepare``.
        state: its state directory.

    Returns:
        One message per reason step 2 would find no tfvars file of the order
        in the repository of the first workspace, empty when ``prepare``
        creates that exact repository and commits the file before step 2.
    """
    workspaces = applied(calls)
    result = f"{state}/result-{workspaces[0]}.json"
    template = f"provision-{E2E_PROVIDER} ws-{workspaces[0]}"
    catalog = f"{CATALOGS}/{E2E_PROVIDER}.json"
    step_two = next(
        index
        for index, call in enumerate(calls)
        if call[:3] == ["task", result, template]
    )
    commits = [
        index
        for index, call in enumerate(calls)
        if call[:4] == ["order", result, template, catalog]
    ]
    if not commits:
        return [NO_COMMIT]
    created = [
        call[-1] for call in calls[: commits[0]] if call[:2] == ["repository", "create"]
    ]
    findings = []
    if commits[0] > step_two:
        findings.append(LATE_COMMIT)
    if calls[commits[0]][-1] not in created:
        findings.append(NO_REPOSITORY)
    if {f"{OWNER}/ws-{workspace}" for workspace in workspaces} - set(created):
        findings.append(MISSING_REPOSITORY)
    return findings


def cleanup_findings(
    calls: list[list[str]],
    finished: subprocess.CompletedProcess,
    workspaces: list[str],
) -> list[str]:
    """Args:
        calls: the drill calls of ``pass.sh cleanup`` whose repository
            deletes fail.
        finished: the finished cleanup.
        workspaces: the workspaces ``prepare`` applied.

    Returns:
        One message per reason the failed delete leaks a workspace or goes
        unreported, empty when every step ran and the cleanup failed.
    """
    destroyed = {call[2] for call in calls if call[:2] == ["workspace", "destroy"]}
    findings = []
    if set(workspaces) - destroyed:
        findings.append(SKIPPED_DESTROY)
    if finished.returncode == 0:
        findings.append(HIDDEN_FAILURE)
    return findings


def retry_findings(
    calls: list[list[str]],
    finished: subprocess.CompletedProcess,
    workspaces: list[str],
    state: Path,
) -> list[str]:
    """Args:
        calls: the drill calls of ``pass.sh cleanup`` whose server destroy
            of the first workspace fails.
        finished: the finished cleanup.
        workspaces: the workspaces ``prepare`` applied.
        state: the state directory of the pass.

    Returns:
        One message per reason a retried server destroy could not run or
        the cleanup hides the failure, empty when the first workspace keeps
        its repository and workspace while the others are cleaned.
    """
    made = {tuple(call[:3]) for call in calls}

    def cleaned(workspace: str) -> set[tuple[str, str, str]]:
        return {
            ("repository", "delete", f"{state}/result-{workspace}.json"),
            ("workspace", "destroy", workspace),
        }

    findings = []
    if made & cleaned(workspaces[0]):
        findings.append(RETRY_DELETED)
    if any(not cleaned(workspace) <= made for workspace in workspaces[1:]):
        findings.append(OTHER_LEFT)
    if finished.returncode == 0:
        findings.append(HIDDEN_FAILURE)
    return findings


class TestWorkspaceTfvars(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.calls: list[tuple[str, str, object]] = []
        env = {
            "BKP_TEST_WORKSPACE_ORDER": json.dumps(configured_order()),
            "BKP_TEST_GITEA_URL": "https://gitea.example",
            "BKP_TEST_GITEA_BASIC_AUTH_B64": base64.b64encode(b"stub:stub").decode(
                "ascii"
            ),
        }
        for patcher in (
            unittest.mock.patch.dict(os.environ, env),
            unittest.mock.patch.object(drill(), "fetch_json", self.fetch),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fetch(
        self, method: str, url: str, _headers: dict, payload: object = None
    ) -> None:
        self.calls.append((method, urllib.parse.urlsplit(url).path, payload))

    def result(self) -> str:
        path = self.scratch / "result.json"
        written = {
            "alias": ALIAS,
            "read_key": READ_KEY,
            "templates": {TEMPLATE: {"git_url": GIT_URL, "git_branch": BRANCH}},
            "workspace": WORKSPACE,
        }
        path.write_text(json.dumps(written), encoding="utf-8")
        return str(path)

    def catalogs(self, incus: dict) -> Path:
        directory = self.scratch / "catalogs"
        directory.mkdir()
        for provider in provision_inputs().PROVIDERS:
            catalog = incus if provider == E2E_PROVIDER else {}
            (directory / f"{provider}.json").write_text(
                json.dumps(catalog), encoding="utf-8"
            )
        return directory

    def prepared(self, source: str) -> list[str]:
        finished, calls = run_pass(source, self.scratch, "prepare", [])
        self.assertEqual(finished.returncode, 0, finished.stderr)
        return prepare_findings(calls, self.scratch / "state")

    def destroy_failure(
        self, source: str
    ) -> tuple[subprocess.CompletedProcess, list[str], list[str]]:
        _, calls = run_pass(source, self.scratch, "prepare", [])
        workspaces = applied(calls)
        state = self.scratch / "state"
        failing = [
            "task",
            f"{state}/result-{workspaces[0]}.json",
            f"destroy-{E2E_PROVIDER} ws-{workspaces[0]}",
        ]
        finished, cleaned = run_pass(source, self.scratch, "cleanup", failing)
        findings = retry_findings(cleaned, finished, workspaces, state)
        return finished, findings, workspaces

    def committed(self) -> tuple[bytes, str]:
        order = configured_order()
        name = f"{order['SALES_ORDER']}-{order['LINE']}"
        drill().commit_order(
            self.result(),
            TEMPLATE,
            str(self.catalogs(role_catalog()) / f"{E2E_PROVIDER}.json"),
        )
        relative = f"provision/{name}.tfvars.json"
        self.assertEqual(len(self.calls), 1, self.calls)
        method, path, payload = self.calls[0]
        self.assertEqual(
            (method, path, payload["branch"]),
            ("POST", f"{API}/repos/{OWNER}/{ALIAS}/contents/{relative}", BRANCH),
        )
        return base64.b64decode(payload["content"]), name

    def test_the_pass_creates_the_repository_and_commits_the_order_before_step_two(
        self,
    ) -> None:
        self.assertEqual(self.prepared(read_text(str(PASS))), [])

    def test_negative_control_the_base_pass_provisions_without_a_tfvars_file(
        self,
    ) -> None:
        source = read_text(str(PASS))
        base = "".join(
            line
            for line in source.splitlines(keepends=True)
            if not line.strip().startswith((COMMIT_CALL, CREATE_CALL))
        )
        self.assertNotEqual(base, source)
        self.assertEqual(self.prepared(base), [NO_COMMIT])

    def test_negative_control_a_commit_after_step_two_is_reported(self) -> None:
        lines = read_text(str(PASS)).splitlines(keepends=True)
        commit = next(line for line in lines if line.strip().startswith(COMMIT_CALL))
        moved = [line for line in lines if line is not commit]
        step_two = next(
            index for index, line in enumerate(moved) if line.strip() == STEP_TWO_LINE
        )
        moved.insert(step_two + 1, commit)
        self.assertEqual(self.prepared("".join(moved)), [LATE_COMMIT])

    def test_negative_control_a_commit_into_another_created_repository_is_reported(
        self,
    ) -> None:
        planted = []
        for line in read_text(str(PASS)).splitlines(keepends=True):
            if line.strip().startswith(STEP_ONE_ECHO):
                planted.append(SECOND_CREATE)
            if not line.strip().startswith(CREATE_CALL):
                planted.append(line)
        self.assertIn(SECOND_CREATE, planted)
        self.assertEqual(
            self.prepared("".join(planted)), [NO_REPOSITORY, MISSING_REPOSITORY]
        )

    def test_a_failed_repository_delete_still_destroys_every_workspace(
        self,
    ) -> None:
        source = read_text(str(PASS))
        _, calls = run_pass(source, self.scratch, "prepare", [])
        finished, cleaned = run_pass(
            source, self.scratch, "cleanup", ["repository", "delete"]
        )
        self.assertEqual(cleanup_findings(cleaned, finished, applied(calls)), [])
        self.assertIn("FAIL: workspace drill: the cleanup left", finished.stdout)

    def test_negative_control_a_cleanup_that_stops_at_the_failed_delete(
        self,
    ) -> None:
        source = read_text(str(PASS))
        planted = KEEP_GOING.sub("", source)
        self.assertNotEqual(planted, source)
        _, calls = run_pass(planted, self.scratch, "prepare", [])
        finished, cleaned = run_pass(
            planted, self.scratch, "cleanup", ["repository", "delete"]
        )
        self.assertEqual(
            cleanup_findings(cleaned, finished, applied(calls)), [SKIPPED_DESTROY]
        )

    def test_a_failed_server_destroy_keeps_its_workspace_for_a_retry(self) -> None:
        finished, findings, workspaces = self.destroy_failure(read_text(str(PASS)))
        self.assertEqual(findings, [])
        self.assertIn(
            f"the server, repository and workspace of {workspaces[0]}", finished.stdout
        )

    def test_negative_control_a_cleanup_that_deletes_past_a_failed_server_destroy(
        self,
    ) -> None:
        source = read_text(str(PASS))
        planted = source.replace(KEEP_FOR_RETRY, DELETE_PAST_FAILED_DESTROY, 1)
        self.assertNotEqual(planted, source)
        _, findings, _ = self.destroy_failure(planted)
        self.assertEqual(findings, [RETRY_DELETED])

    def test_the_committed_tfvars_are_the_bytes_commit_values_writes_for_incus(
        self,
    ) -> None:
        self.assertEqual(set(commit_values_keys()), root_variables())
        content, name = self.committed()
        findings = tfvars_findings(
            content, name, self.scratch / "catalogs", self.scratch / "checkout"
        )
        self.assertEqual(findings, [])

    def test_negative_control_a_planted_tfvars_file_is_reported(self) -> None:
        content, name = self.committed()
        values = json.loads(content)
        compact = {"separators": (",", ":")}
        cases = {
            "unknown size": json.dumps({**values, "size": "huge"}, **compact),
            "extra key": json.dumps({**values, "image": "debian"}, **compact),
            "other line": json.dumps({**values, "name": f"{name}0"}, **compact),
            "upper dns label": json.dumps({**values, "dns_label": name}, **compact),
            "spaced json": json.dumps(values),
            "sorted keys": json.dumps(values, sort_keys=True, **compact),
        }
        for label, planted in cases.items():
            with self.subTest(planted=label):
                findings = tfvars_findings(
                    planted.encode("utf-8"),
                    name,
                    self.scratch / "catalogs",
                    self.scratch / label.replace(" ", "-"),
                )
                self.assertNotEqual(findings, [])

    def test_the_line_takes_the_smallest_size_in_a_region_with_a_host(self) -> None:
        catalog = {
            "cloud": {
                "sizes": {
                    "large": {"vcpus": 4, "memory_mib": 8192, "disk_gib": 80},
                    "small": {"vcpus": 1, "memory_mib": 1024, "disk_gib": 10},
                },
                "regions": {
                    "west": {"host": REGION_HOST, "pool": "agents"},
                    "east": {"host": REGION_HOST, "pool": "agents"},
                },
            },
            "demo": {
                "sizes": {"tiny": {"vcpus": 1, "memory_mib": 512, "disk_gib": 5}},
                "regions": {"default": {"host": "", "pool": "agents"}},
            },
        }
        key = drill().public_key()
        values = drill().order_values(configured_order(), catalog, key)
        self.assertEqual(
            (values["flavor"], values["size"], values["region"]),
            ("cloud", "small", "east"),
        )
        with self.assertRaises(drill().DrillError):
            drill().order_values(configured_order(), {"demo": catalog["demo"]}, key)

    def test_a_size_without_its_resources_fails_with_its_name(self) -> None:
        catalog = role_catalog()
        flavor = min(catalog)
        size = min(catalog[flavor]["sizes"])
        broken = {
            **catalog,
            flavor: {**catalog[flavor], "sizes": {size: {"vcpus": 1, "memory_mib": 1}}},
        }
        path = self.scratch / f"{E2E_PROVIDER}.json"
        path.write_text(json.dumps(broken), encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = drill().main(["order", self.result(), TEMPLATE, str(path)])
        self.assertEqual(code, 1)
        self.assertEqual(
            stderr.getvalue(),
            f"FAIL: workspace drill: size {size} of flavor {flavor} names no disk_gib\n",
        )
        self.assertEqual(self.calls, [])

    def test_the_repository_the_template_clones_is_created_as_the_store_does(
        self,
    ) -> None:
        drill().repository("create", self.result(), TEMPLATE)
        drill().repository("delete", self.result(), TEMPLATE)
        self.assertEqual(
            self.calls,
            [
                (
                    "POST",
                    f"{API}/orgs/{OWNER}/repos",
                    {
                        "name": ALIAS,
                        "private": True,
                        "auto_init": True,
                        "default_branch": BRANCH,
                    },
                ),
                (
                    "POST",
                    f"{API}/repos/{OWNER}/{ALIAS}/keys",
                    {"title": f"read {ALIAS}", "key": READ_KEY, "read_only": True},
                ),
                ("DELETE", f"{API}/repos/{OWNER}/{ALIAS}", None),
            ],
        )

    def test_the_login_key_has_the_shape_of_ssh_ed25519_public_line(self) -> None:
        with unittest.mock.patch(
            "secrets.token_bytes", return_value=KEY_RAW
        ) as token_bytes:
            line = drill().public_key()
        token_bytes.assert_called_once_with(len(KEY_RAW))
        kind, encoded = line.split(" ")
        self.assertEqual(
            (kind, base64.b64decode(encoded, validate=True)), ("ssh-ed25519", KEY_BLOB)
        )
        properties = json.loads(read_text(str(INTERFACE)))["properties"]
        self.assertRegex(line, properties["ssh_public_key"]["pattern"])
        self.assertNotEqual(drill().public_key(), drill().public_key())

    def test_test_env_hands_the_pass_the_provision_runner_catalogs(self) -> None:
        env = sourced(render(read_text(str(TEST_ENV)), LOCAL_INCUS))
        self.assertEqual(env[CATALOGS_VAR], CATALOGS)
        application, name = CATALOG_VOLUME
        volumes = load_yaml_any(
            str(PROJECT_ROOT / "roles" / application / ROLE_FILE_META_VOLUMES)
        )
        services = {mount["service"] for mount in volumes[name]["mounts"]}
        self.assertIn(PROVISION_RUNNER, services)

    def test_negative_control_another_volume_fails_the_render(self) -> None:
        source = read_text(str(TEST_ENV))
        application, name = CATALOG_VOLUME
        cases = {
            "volume": source.replace(f"'{name}'", "'semaphore_runner_tmp'", 1),
            "role": source.replace(
                f"lookup('volume', '{application}'",
                "lookup('volume', 'web-app-openbao'",
                1,
            ),
        }
        for label, planted in cases.items():
            with self.subTest(planted=label):
                self.assertNotEqual(planted, source)
                with self.assertRaisesRegex(
                    AssertionError, "test.env.j2 reads the volume"
                ):
                    render(planted, LOCAL_INCUS)


if __name__ == "__main__":
    unittest.main()
