from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-cache-package"
SCRIPT = ROLE / "files" / "shell" / "bootstrap.sh"
POLICY = "infinito-idle"
POLICY_ROUTE = "/service/rest/internal/cleanup-policies"
EXTDIRECT = "/service/extdirect"
CLEANUP = "repository.cleanup"
COMPACT = "blobstore.compact"
COMPACT_NAME = "infinito compact default"
DUPLICATE = f"Task with name '{COMPACT_NAME}' already exists"
TASK_NAMES = {CLEANUP: "Cleanup service", COMPACT: COMPACT_NAME}
DAILY = re.compile(r"^0 \d{1,2} \d{1,2} \* \* \?$")
UPSTREAMS = (
    "pypi-proxy|pypi|https://pypi.org/|||,"  # nocheck: url  upstream list fixture
    "apt-debian|apt|http://deb.debian.org/debian|bookworm||,"  # nocheck: url  fixture
    "raw-githubusercontent|raw|https://raw.githubusercontent.com/|||"  # nocheck: url
)

FAKE_CURL = r"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
if "-K" in args:
    sys.stdin.read()
method, data, url, write_out, headers = "GET", None, "", False, []
index = 0
while index < len(args):
    arg = args[index]
    if arg in ("-X", "--data", "-w", "-H", "-o", "-K"):
        value = args[index + 1]
        method = value if arg == "-X" else method
        data = value if arg == "--data" else data
        write_out = write_out or arg == "-w"
        if arg == "-H":
            headers.append(value)
        index += 2
        continue
    if arg.startswith("http"):
        url = arg
    index += 1
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as log:
    entry = {"method": method, "url": url, "data": data, "headers": headers}
    log.write(json.dumps(entry) + "\n")
if "/v1/tasks?type=" in url:
    kind = url.rsplit("type=", 1)[1]
    if kind in os.environ["STUB_LISTING_FAILS"].split(","):
        sys.stderr.write("curl: (22) The requested URL returned error: 500\n")
        sys.exit(22)
    scheduled = os.environ["STUB_TASKS"].split(",")
    if os.path.exists(os.environ["STUB_CREATED"]):
        scheduled += os.environ["STUB_TASKS_AFTER_CREATE"].split(",")
    names = json.loads(os.environ["STUB_TASK_NAMES"])
    item = '{ "id" : "existing", "name" : "' + names[kind] + '" }' if kind in scheduled else ""
    sys.stdout.write('{\n  "items" : [ ' + item + ' ],\n  "continuationToken" : null\n}')
elif url.endswith("/service/extdirect"):
    with open(os.environ["STUB_CREATED"], "w", encoding="utf-8"):
        pass
    success = os.environ["STUB_EXTDIRECT_SUCCESS"]
    refusal = os.environ["STUB_EXTDIRECT_REFUSAL"]
    message = '"message":' + json.dumps(refusal) + "," if refusal else ""
    sys.stdout.write(
        '{"tid":1,"action":"coreui_Task","method":"create","type":"rpc",'
        '"result":{' + message + '"success":' + success + ',"data":{}}}'
    )
elif write_out:
    sys.stdout.write("204" if method == "PUT" or url.endswith("/v1/system/eula") else "201")
"""

DRAIN = "#!/usr/bin/env bash\ncat >/dev/null\n"
NOOP = "#!/usr/bin/env bash\nexit 0\n"


def _bootstrap(
    idle_days: str,
    scheduled: str,
    extdirect_success: str,
    refusal: str = "",
    scheduled_after_create: str = "",
    listing_fails: str = "",
) -> tuple[int, list[dict]]:
    """Args:
        idle_days: the INFINITO_CACHE_MAX_IDLE_DAYS the bootstrap gets, empty to leave it unset.
        scheduled: the comma-separated task types Nexus already lists.
        extdirect_success: what Nexus answers to the Ext.Direct task creation, `true` or `false`.
        refusal: the message Nexus adds to that answer, empty for none.
        scheduled_after_create: the comma-separated task types Nexus lists once a
            creation was posted, as when a concurrent bootstrap created them.
        listing_fails: the comma-separated task types whose listing Nexus answers with HTTP 500.

    Returns:
        The exit code and every Nexus request, with its JSON body parsed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        for name, body in (
            ("curl", FAKE_CURL),
            ("sh", DRAIN),
            ("touch", NOOP),
            ("sleep", NOOP),
        ):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        log = Path(tmp) / "requests"
        env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "HOME": tmp,
            "STUB_LOG": str(log),
            "STUB_TASKS": scheduled,
            "STUB_TASKS_AFTER_CREATE": scheduled_after_create,
            "STUB_TASK_NAMES": json.dumps(TASK_NAMES),
            "STUB_LISTING_FAILS": listing_fails,
            "STUB_CREATED": str(Path(tmp) / "created"),
            "STUB_EXTDIRECT_SUCCESS": extdirect_success,
            "STUB_EXTDIRECT_REFUSAL": refusal,
            "INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD": "probe-password",
            "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX": "40g",
            "INFINITO_CACHE_PACKAGE_MAX_AGE_MIN": "8640",
            "INFINITO_CACHE_PACKAGE_METADATA_MAX_AGE_MIN": "0",
            "INFINITO_CACHE_UPSTREAMS": UPSTREAMS,
            "INFINITO_CACHE_PACKAGE_CONTAINER": "probe-nexus",
            "INFINITO_CACHE_PACKAGE_EXEC_MODE": "local",
            "INFINITO_CACHE_PACKAGE_PORT": "8081",
            "INFINITO_CACHE_PACKAGE_REST_HOST": "127.0.0.1",
        }
        if idle_days:
            env["INFINITO_CACHE_MAX_IDLE_DAYS"] = idle_days
        done = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        lines = read_text(str(log)).splitlines() if log.exists() else []
    requests = []
    for line in lines:
        request = json.loads(line)
        request["body"] = json.loads(request["data"]) if request["data"] else None
        requests.append(request)
    return done.returncode, requests


def _posts(requests: list[dict], suffix: str) -> list[dict]:
    return [r for r in requests if r["method"] == "POST" and r["url"].endswith(suffix)]


def _looked_up(requests: list[dict]) -> list[str]:
    return [
        r["url"].rsplit("type=", 1)[1]
        for r in requests
        if r["method"] == "GET" and "/v1/tasks?type=" in r["url"]
    ]


class TestBootstrapCleanup(unittest.TestCase):
    def test_a_cleanup_policy_on_last_download_covers_the_idle_window(self) -> None:
        code, requests = _bootstrap("30", CLEANUP, "true")
        self.assertEqual(code, 0)
        policies = _posts(requests, POLICY_ROUTE)
        self.assertEqual(len(policies), 1)
        self.assertEqual(
            policies[0]["body"],
            {"name": POLICY, "format": "*", "criteriaLastDownloaded": 30},
        )

    def test_the_idle_window_follows_the_environment(self) -> None:
        _, requests = _bootstrap("7", CLEANUP, "true")
        self.assertEqual(
            _posts(requests, POLICY_ROUTE)[0]["body"]["criteriaLastDownloaded"], 7
        )

    def test_the_bootstrap_refuses_to_run_without_an_idle_window(self) -> None:
        code, requests = _bootstrap("", CLEANUP, "true")
        self.assertNotEqual(code, 0)
        self.assertEqual(requests, [])

    def test_every_proxy_repository_is_attached_to_the_policy(self) -> None:
        _, requests = _bootstrap("30", CLEANUP, "true")
        repos = [
            r
            for r in requests
            if r["method"] == "POST" and "/v1/repositories/" in r["url"]
        ]
        self.assertEqual(
            sorted(r["body"]["name"] for r in repos),
            ["apt-debian", "pypi-proxy", "raw-githubusercontent"],
        )
        for repo in repos:
            self.assertEqual(repo["body"]["cleanup"], {"policyNames": [POLICY]})
        policy_at = requests.index(_posts(requests, POLICY_ROUTE)[0])
        self.assertLess(policy_at, requests.index(repos[0]))

    def test_cleanup_and_compaction_are_scheduled_daily(self) -> None:
        code, requests = _bootstrap("30", CLEANUP, "true")
        self.assertEqual(code, 0)
        self.assertIn(CLEANUP, _looked_up(requests))
        calls = _posts(requests, EXTDIRECT)
        self.assertEqual(len(calls), 1)
        body = calls[0]["body"]
        self.assertEqual((body["action"], body["method"]), ("coreui_Task", "create"))
        task = body["data"][0]
        self.assertEqual(task["typeId"], COMPACT)
        self.assertEqual(task["properties"]["blobstoreName"], "default")
        self.assertTrue(task["enabled"])
        self.assertEqual(task["schedule"], "advanced")
        self.assertRegex(task["cronExpression"], DAILY)

    def test_the_compaction_request_passes_the_csrf_check(self) -> None:
        _, requests = _bootstrap("30", CLEANUP, "true")
        headers = _posts(requests, EXTDIRECT)[0]["headers"]
        tokens = [h.split(":", 1)[1].strip() for h in headers if h.startswith("NX-")]
        cookies = [h.split("=", 1)[1] for h in headers if h.startswith("Cookie:")]
        self.assertEqual(len(tokens), 1)
        self.assertEqual(cookies, tokens)

    def test_the_bootstrap_uses_no_route_the_pinned_nexus_lacks(self) -> None:
        _, requests = _bootstrap("30", CLEANUP, "true")
        self.assertEqual(_posts(requests, "/v1/tasks"), [])
        self.assertEqual(
            [r for r in requests if "/v1/cleanup-policies" in r["url"]], []
        )

    def test_scheduled_tasks_are_not_created_twice(self) -> None:
        code, requests = _bootstrap("30", f"{CLEANUP},{COMPACT}", "true")
        self.assertEqual(code, 0)
        self.assertEqual(set(_looked_up(requests)), {CLEANUP, COMPACT})
        self.assertEqual(_posts(requests, EXTDIRECT), [])

    def test_a_nexus_without_its_cleanup_task_fails_the_bootstrap(self) -> None:
        code, requests = _bootstrap("30", "", "true")
        self.assertNotEqual(code, 0)
        self.assertIn(CLEANUP, _looked_up(requests))
        self.assertEqual(_posts(requests, EXTDIRECT), [])

    def test_a_refused_compaction_task_fails_the_bootstrap(self) -> None:
        code, requests = _bootstrap("30", CLEANUP, "false")
        self.assertNotEqual(code, 0)
        self.assertEqual(len(_posts(requests, EXTDIRECT)), 1)

    def test_the_task_a_concurrent_bootstrap_created_counts_once_nexus_lists_it(
        self,
    ) -> None:
        code, requests = _bootstrap(
            "30", CLEANUP, "false", refusal=DUPLICATE, scheduled_after_create=COMPACT
        )
        self.assertEqual(code, 0)
        calls = _posts(requests, EXTDIRECT)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["body"]["data"][0]["name"], COMPACT_NAME)
        self.assertEqual(_looked_up(requests).count(COMPACT), 2)

    def test_a_duplicate_refusal_fails_while_nexus_lists_no_such_task(self) -> None:
        code, requests = _bootstrap("30", CLEANUP, "false", refusal=DUPLICATE)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(_posts(requests, EXTDIRECT)), 1)

    def test_another_refusal_fails_even_once_nexus_lists_the_task(self) -> None:
        code, _ = _bootstrap(
            "30",
            CLEANUP,
            "false",
            refusal="Invalid cron expression",
            scheduled_after_create=COMPACT,
        )
        self.assertNotEqual(code, 0)

    def test_a_compaction_task_of_another_name_does_not_count(self) -> None:
        names = {**TASK_NAMES, COMPACT: "operator compact default"}
        with unittest.mock.patch.dict(TASK_NAMES, names):
            code, requests = _bootstrap("30", f"{CLEANUP},{COMPACT}", "true")
        self.assertEqual(code, 0)
        calls = _posts(requests, EXTDIRECT)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["body"]["data"][0]["name"], COMPACT_NAME)

    def test_an_unanswered_task_listing_fails_before_any_creation(self) -> None:
        code, requests = _bootstrap("30", CLEANUP, "true", listing_fails=COMPACT)
        self.assertNotEqual(code, 0)
        self.assertEqual(_posts(requests, EXTDIRECT), [])


class TestAptProxies(unittest.TestCase):
    def test_an_apt_proxy_serves_every_suite_of_its_archive(self) -> None:
        _, requests = _bootstrap("30", CLEANUP, "true")
        self.assertEqual(
            [r["body"]["apt"] for r in _posts(requests, "/v1/repositories/apt/proxy")],
            [
                {
                    "distribution": "bookworm",
                    "flat": False,
                    "enforceDistribution": False,
                }
            ],
        )


class TestRoleDefaults(unittest.TestCase):
    def test_the_role_defaults_to_the_30_day_window_and_keeps_its_server_cap(
        self,
    ) -> None:
        package = load_yaml(str(ROLE / ROLE_FILE_META_SERVICES))["package"]
        self.assertEqual(package["max_idle_days"], 30)
        self.assertEqual(package["blobstore_max"], "40g")

    def test_both_bootstrap_environments_carry_the_role_window(self) -> None:
        self.assertIn(
            "CACHE_PACKAGE_MAX_IDLE_DAYS: \"{{ lookup('config', application_id, 'services.package.max_idle_days') }}\"",
            read_text(str(ROLE / ROLE_FILE_VARS_MAIN)),
        )
        self.assertIn(
            "INFINITO_CACHE_MAX_IDLE_DAYS={{ CACHE_PACKAGE_MAX_IDLE_DAYS }}",
            read_text(str(ROLE / "templates" / "env" / "bootstrap.j2")),
        )
        self.assertIn(
            "INFINITO_CACHE_MAX_IDLE_DAYS: {{ CACHE_PACKAGE_MAX_IDLE_DAYS | to_json }}",
            read_text(str(ROLE / "templates" / "environment" / "bootstrap.j2")),
        )


if __name__ == "__main__":
    unittest.main()
