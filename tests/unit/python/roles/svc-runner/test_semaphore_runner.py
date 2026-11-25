from __future__ import annotations

import importlib
import json
import unittest
from pathlib import PurePosixPath

from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.runner import pinned
from utils.runner.semaphore import pool_runner_token

render = importlib.import_module("tests.unit.python.roles.svc-runner._render")

SEMAPHORE = "web-app-semaphore"
ENABLED = {"RUNNER_SEMAPHORE_ENABLED": True}
SIDECARS = ("semaphore-runner-1", "semaphore-runner-2")
INSTANCE_TASKS = "03_instance.yml"
ENV_TEMPLATE = "runner/semaphore/env.j2"
TOKEN_TEMPLATE = "runner/semaphore/token.j2"


def _services(flavor: str, overrides: dict) -> dict:
    text = render.render(render.COMPOSE, flavor, overrides=overrides)
    return load_yaml_str(text)["services"]


def _gate(group_names: list[str], flavor: str) -> bool:
    expression = render.role_vars()["RUNNER_SEMAPHORE_ENABLED"].strip()[2:-2]
    return render.condition(
        expression, group_names=group_names, **render.flavor_variables(flavor)
    )


def _semaphore_tasks() -> list[dict]:
    tasks = load_yaml_any(str(render.ROLE / "tasks" / INSTANCE_TASKS))
    return [task for task in tasks if "RUNNER_SEMAPHORE" in json.dumps(task)]


class TestTheGate(unittest.TestCase):
    def test_a_local_runner_beside_semaphore_registers(self) -> None:
        self.assertTrue(_gate([SEMAPHORE, "svc-runner"], "local"))

    def test_negative_control_without_semaphore_nothing_registers(self) -> None:
        self.assertFalse(_gate(["svc-runner"], "local"))

    def test_negative_control_a_github_runner_never_registers(self) -> None:
        self.assertFalse(_gate([SEMAPHORE, "svc-runner"], "github"))


class TestTheSidecars(unittest.TestCase):
    def test_every_pool_runner_gets_one_semaphore_runner(self) -> None:
        services = _services("local", ENABLED)
        self.assertEqual(
            sorted(name for name in services if name.startswith("semaphore-")),
            list(SIDECARS),
        )

    def test_negative_control_a_disabled_gate_renders_no_semaphore_runner(
        self,
    ) -> None:
        for flavor, overrides in (("local", {}), ("github", ENABLED)):
            with self.subTest(flavor=flavor, overrides=overrides):
                services = _services(flavor, overrides)
                self.assertFalse([n for n in services if n.startswith("semaphore-")])

    def test_a_semaphore_runner_reads_its_own_token_and_the_queue_only(self) -> None:
        services = _services("local", ENABLED)
        token_file = render.role_vars()["RUNNER_SEMAPHORE_TOKEN_FILE"]
        for index, name in enumerate(SIDECARS, start=1):
            service = services[name]
            instance = f"/opt/github-runner/{index}"
            with self.subTest(name=name):
                self.assertIn(
                    f"{instance}/semaphore.token:{token_file}:ro", service["volumes"]
                )
                self.assertIn(f"{render.QUEUE}:{render.QUEUE}", service["volumes"])
                self.assertEqual(service["env_file"], f"{instance}/semaphore.env")
                self.assertEqual(service["group_add"], [str(render.QUEUE_GID)])
                self.assertEqual(service["image"], render.SEMAPHORE_IMAGE)
                self.assertFalse(
                    [v for v in service["volumes"] if "docker.sock" in v],
                    "the Semaphore runner must not reach a Docker daemon",
                )

    def test_the_token_file_never_lies_in_the_shared_queue(self) -> None:
        tasks = _semaphore_tasks()
        written = [task for task in tasks if "template" in task]
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0]["when"], "RUNNER_SEMAPHORE_ENABLED | bool")
        files = render.role_vars()["RUNNER_SEMAPHORE_FILES"]
        self.assertEqual(
            {entry["dest"]: entry["mode"] for entry in files},
            {"semaphore.env": "0600", "semaphore.token": "0400"},
        )
        dest = written[0]["template"]["dest"]
        self.assertTrue(dest.startswith("{{ RUNNER_INSTALL_DIR }}/"))
        self.assertNotIn("RUNNER_QUEUE_DIR", dest)

    def test_negative_control_an_opt_out_removes_the_token(self) -> None:
        removed = [
            task
            for task in _semaphore_tasks()
            if (task.get("file") or {}).get("state") == "absent"
        ]
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["when"], "not (RUNNER_SEMAPHORE_ENABLED | bool)")


class TestTheInstanceFiles(unittest.TestCase):
    def test_the_token_is_the_derived_token_of_this_runner(self) -> None:
        for index in (1, 2):
            with self.subTest(index=index):
                text = render.render(
                    TOKEN_TEMPLATE,
                    "local",
                    overrides={**ENABLED, "runner_instance": index},
                )
                self.assertEqual(
                    text.strip(),
                    pool_runner_token(render.SEMAPHORE_SECRET, f"runner-{index}"),
                )

    def test_negative_control_two_runners_never_share_a_token(self) -> None:
        one, two = (
            render.render(
                TOKEN_TEMPLATE, "local", overrides={**ENABLED, "runner_instance": index}
            )
            for index in (1, 2)
        )
        self.assertNotEqual(one, two)

    def test_the_task_environment_forwards_what_the_pinned_submit_reads(self) -> None:
        values = render.env_values(
            render.render(ENV_TEMPLATE, "local", overrides=ENABLED)
        )
        self.assertEqual(
            set(json.loads(values["SEMAPHORE_FORWARDED_ENV_VARS"])), set(pinned.KEYS)
        )
        self.assertEqual(values[pinned.RUNNER_KEY], "runner-1")
        self.assertEqual(values[pinned.QUEUE_KEY], render.QUEUE)
        self.assertEqual(values[pinned.SRC_KEY], render.source_dir("local"))
        self.assertEqual(values["SEMAPHORE_WEB_ROOT"], render.SEMAPHORE_URL)
        self.assertEqual(
            PurePosixPath(values["SEMAPHORE_TMP_PATH"]).parent,
            PurePosixPath("/opt/github-runner/1"),
        )


if __name__ == "__main__":
    unittest.main()
