from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from functools import partial
from pathlib import Path

from cli.agents import scenarios
from cli.agents.scenarios import (
    ScenarioError,
    Step,
    load_scenarios,
    missing_credentials,
    parse_scenario,
    play,
    run_all,
    select,
)
from utils.cache.files import read_text

HEAD = (
    "id: probe\n"
    "criterion: SC-PROBE\n"
    "mode: compose\n"
    "given: a seeded fixture\n"
    "when: the probe runs\n"
    "then: the observable holds\n"
)
TWO_STEPS = (
    HEAD + "steps:\n"
    "  - run: seed --user 'biber'\n"
    "  - run: probe\n"
    "    expect: ^refused\n"
    "    exit: 3\n"
)
ENV_KEY = "SCENARIO_TEST_ANTHROPIC_KEY"
INVENTORY = {
    "API": {
        "anthropic": {"api_key": "{{ lookup('env', '" + ENV_KEY + "') }}"},
        "openai": {"api_key": "literal"},
    }
}


class Recording:
    """A runner that replays recorded step outputs and keeps the commands it ran."""

    def __init__(self, replies: dict[str, tuple[int, str]]) -> None:
        self.replies = replies
        self.ran: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.ran.append(command)
        return self.replies[command]


class TestParse(unittest.TestCase):
    def test_the_real_scenarios_load(self):
        loaded = load_scenarios()
        self.assertIn("counsel-blocker", [scenario.id for scenario in loaded])
        blocker = next(s for s in loaded if s.id == "counsel-blocker")
        self.assertTrue(blocker.then.endswith("while the blocker is open"))

    def test_steps_and_requires_are_parsed(self):
        scenario = parse_scenario(
            TWO_STEPS + "requires:\n  - API.anthropic.api_key\n", "<inline>"
        )
        self.assertEqual(
            scenario.steps,
            (Step("seed --user 'biber'", "", 0), Step("probe", "^refused", 3)),
        )
        self.assertEqual(scenario.requires, ("API.anthropic.api_key",))

    def test_red_fixture_fails(self):
        broken = (
            HEAD.replace("mode: compose", "mode: k8s"),
            "id: x\nmode: compose\n",
            HEAD + "steps:\n  - expect: ok\n",
            HEAD + "steps:\n  - run: probe\n    expect: '('\n",
            HEAD + "steps:\n  - run: probe\n    exit: 'zero'\n",
            HEAD + "steps:\n  - run: probe\n    wait: 5\n",
            HEAD + "requires: API.anthropic.api_key\n",
            HEAD + "steps: probe\n",
        )
        for text in broken:
            with self.subTest(text=text), self.assertRaises(ScenarioError):
                parse_scenario(text, "<inline>")

    def test_a_both_scenario_runs_in_either_mode(self):
        both = parse_scenario(HEAD.replace("compose", "both"), "<inline>")
        swarm = parse_scenario(HEAD.replace("compose", "swarm"), "<inline>")
        self.assertEqual(select([both, swarm], mode="compose"), [both])
        self.assertEqual(select([both, swarm], mode="swarm"), [both, swarm])


class TestPlay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "probe.log"

    def _play(self, text: str, runner: Recording, inventory: dict) -> str:
        scenario = parse_scenario(text, "<inline>")
        return play(scenario, self.log, runner=runner, inventory=inventory)

    def _logged(self) -> str:
        return read_text(str(self.log))

    def test_a_recorded_run_passes(self):
        runner = Recording(
            {"seed --user 'biber'": (0, "seeded\n"), "probe": (3, "refused: lockout\n")}
        )
        self.assertEqual(self._play(TWO_STEPS, runner, {}), "passed")
        self.assertEqual(runner.ran, ["seed --user 'biber'", "probe"])
        self.assertIn("refused: lockout", self._logged())

    def test_an_output_without_the_expected_pattern_fails(self):
        runner = Recording(
            {"seed --user 'biber'": (0, "seeded\n"), "probe": (3, "accepted\n")}
        )
        self.assertEqual(self._play(TWO_STEPS, runner, {}), "failed")
        self.assertIn("printed no '^refused'", self._logged())

    def test_a_wrong_exit_fails_and_ends_the_scenario(self):
        runner = Recording({"seed --user 'biber'": (1, "boom\n")})
        self.assertEqual(self._play(TWO_STEPS, runner, {}), "failed")
        self.assertEqual(runner.ran, ["seed --user 'biber'"])

    def test_a_scenario_without_steps_is_skipped_not_passed(self):
        runner = Recording({})
        self.assertEqual(self._play(HEAD, runner, {}), "skipped")
        self.assertIn("declares no steps", self._logged())

    def test_an_unset_credential_skips_without_touching_the_stack(self):
        text = TWO_STEPS + "requires:\n  - API.anthropic.api_key\n"
        runner = Recording({})
        with mock.patch.dict(os.environ, {ENV_KEY: ""}):
            self.assertEqual(self._play(text, runner, INVENTORY), "skipped")
        self.assertEqual(runner.ran, [])
        self.assertIn("API.anthropic.api_key", self._logged())

    def test_a_set_credential_plays_the_scenario(self):
        text = TWO_STEPS + "requires:\n  - API.anthropic.api_key\n"
        runner = Recording({"seed --user 'biber'": (0, ""), "probe": (3, "refused\n")})
        with mock.patch.dict(os.environ, {ENV_KEY: "set"}):
            self.assertEqual(self._play(text, runner, INVENTORY), "passed")


class TestCredentials(unittest.TestCase):
    def _missing(self, *paths: str) -> list[str]:
        requires = "".join(f"  - {path}\n" for path in paths)
        scenario = parse_scenario(HEAD + "requires:\n" + requires, "<inline>")
        return missing_credentials(scenario, INVENTORY)

    def test_literal_env_and_absent_values(self):
        with mock.patch.dict(os.environ, {ENV_KEY: "set"}):
            self.assertEqual(
                self._missing("API.openai.api_key", "API.anthropic.api_key"), []
            )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(ENV_KEY, None)
            self.assertEqual(
                self._missing("API.anthropic.api_key", "agents.github.token"),
                ["API.anthropic.api_key", "agents.github.token"],
            )


class TestRunnerAndMain(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(scenarios, "LOG_DIR", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_stack_runner_passes_the_step_as_one_argv_element(self):
        done = subprocess.CompletedProcess([], 0, stdout="out\n", stderr="err\n")
        with mock.patch.object(scenarios.subprocess, "run", return_value=done) as run:
            self.assertEqual(scenarios.stack_runner("echo 'a b'"), (0, "out\nerr\n"))
        argv = run.call_args.args[0]
        self.assertEqual(argv[-3:], ["sh", "-lc", "echo 'a b'"])
        self.assertTrue(
            argv[1].endswith("scripts/tests/deploy/local/exec/container.sh")
        )
        self.assertTrue(Path(argv[1]).is_file())

    def test_a_hanging_step_times_out(self):
        expired = subprocess.TimeoutExpired("sh", scenarios.STEP_TIMEOUT_SECONDS)
        with mock.patch.object(scenarios.subprocess, "run", side_effect=expired):
            code, _output = scenarios.stack_runner("sleep infinity")
        self.assertEqual(code, scenarios.TIMEOUT_EXIT)

    def test_main_prints_the_table_and_fails_on_a_failed_scenario(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "probe.yml").write_text(TWO_STEPS, encoding="utf-8")
            loaded = load_scenarios(Path(tmp))
        runner = Recording({"seed --user 'biber'": (1, "")})
        out = io.StringIO()
        with (
            mock.patch.object(scenarios, "load_scenarios", return_value=loaded),
            contextlib.redirect_stdout(out),
        ):
            self.assertEqual(scenarios.main(["--mode", "compose"], runner=runner), 1)
        self.assertRegex(out.getvalue(), r"probe\s+compose\s+failed")

    def test_a_runner_failing_every_step_passes_no_real_scenario(self):
        def failing(_command: str) -> tuple[int, str]:
            return 1, ""

        results = run_all(
            load_scenarios(), execute=partial(play, runner=failing, inventory={})
        )
        self.assertTrue(results)
        self.assertNotIn("passed", {r.result for r in results})


if __name__ == "__main__":
    unittest.main()
