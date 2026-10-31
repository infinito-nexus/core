import unittest
from pathlib import Path

from jinja2 import Environment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

FULLSTACK = (
    Path(PROJECT_ROOT) / "roles" / "web-app-nextcloud" / "tasks" / "01_fullstack.yml"
)
ASSERT_NAME = "🛑 Assert Talk has the TURN server its calls relay through"


def _turn_assert() -> tuple[dict, list[str]]:
    for task in load_yaml_any(str(FULLSTACK)):
        for inner in task.get("block", []):
            if inner.get("name") == ASSERT_NAME:
                outer = task.get("when", [])
                return inner, outer if isinstance(outer, list) else [outer]
    raise AssertionError(f"{ASSERT_NAME!r} not found in {FULLSTACK}")


def _runs_and_holds(*, stack_host: bool, coturn_here: bool) -> tuple[bool, bool]:
    task, guards = _turn_assert()
    inner = task.get("when", [])
    guards = guards + (inner if isinstance(inner, list) else [inner])
    env = Environment(autoescape=True)
    env.filters["bool"] = bool
    context = {
        "NEXTCLOUD_HPB_SIGNALING_ENABLED": True,
        "IS_STACK_HOST": stack_host,
        "NEXTCLOUD_HPB_TURN_ACTIVE_SERVER": "turn.example.org:3478"
        if coturn_here
        else "",
    }
    runs = all(bool(env.compile_expression(guard)(**context)) for guard in guards)
    holds = bool(
        env.compile_expression(task["ansible.builtin.assert"]["that"])(**context)
    )
    return runs, holds


class TestTalkTurnAssert(unittest.TestCase):
    def test_a_swarm_worker_without_coturn_skips_the_assert(self) -> None:
        runs, _ = _runs_and_holds(stack_host=False, coturn_here=False)
        self.assertFalse(
            runs,
            "a swarm worker never runs Talk and is not in web-svc-coturn's group, "
            "so the assert must not judge it",
        )

    def test_the_stack_host_with_coturn_passes(self) -> None:
        self.assertEqual(
            _runs_and_holds(stack_host=True, coturn_here=True), (True, True)
        )

    def test_the_stack_host_without_coturn_is_refused(self) -> None:
        self.assertEqual(
            _runs_and_holds(stack_host=True, coturn_here=False), (True, False)
        )


if __name__ == "__main__":
    unittest.main()
