from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

SCRIPT = PROJECT_ROOT / "scripts" / "github" / "runner" / "raise_sysctl_floors.sh"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"
RUNNER_VARS_REL = f"roles/svc-runner/{ROLE_FILE_VARS_MAIN}"
RUNNER_VARS = PROJECT_ROOT / RUNNER_VARS_REL
INSTANCES_KEY = "fs.inotify.max_user_instances"
HOSTED_IMAGE_INSTANCES = 1280
HOSTED_IMAGE = {
    "fs.inotify.max_user_instances": "1280",
    "fs.inotify.max_user_watches": "655360",
    "fs.inotify.max_queued_events": "16384",
    "vm.max_map_count": "262144",
}

SUDO_STUB = (
    "#!/usr/bin/env bash\n"
    'printf "%s\\n" "$*" >>"${STUB_LOG}"\n'
    'if [ -x "${STUB_BIN}/$1" ]; then exec "${STUB_BIN}/$1" "${@:2}"; fi\n'
    'echo "unstubbed sudo $1" >&2\n'
    "exit 97\n"
)
SYSCTL_READ_STUB = (
    "#!/usr/bin/env bash\n"
    'if [ "$1" != -n ]; then echo "sysctl $1 ran without sudo" >&2; exit 98; fi\n'
    'grep -m1 "^$2 " "${STUB_STATE}" | cut -d" " -f2-\n'
)
SYSCTL_WRITE_STUB = (
    "#!/usr/bin/env bash\n"
    '[ "$1" = -w ] || exit 96\n'
    'printf "%s\\n" "$2" >>"${STUB_WRITES}"\n'
)


def runner_floors() -> dict[str, str]:
    """
    Returns:
        RUNNER_SYSCTL_PARAMETERS of svc-runner as strings.
    """
    parameters = load_yaml_any(str(RUNNER_VARS))["RUNNER_SYSCTL_PARAMETERS"]
    return {key: str(value) for key, value in parameters.items()}


def run(
    current: dict[str, str], vars_text: str | None = None
) -> tuple[subprocess.CompletedProcess, list[str], list[str]]:
    """Args:
        current: what ``sysctl -n`` reports per key.
        vars_text: vars file content, None for the real svc-runner vars.

    Returns:
        The finished process, every sudo call and every sysctl write.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub_bin = root / "privileged"
        stub_bin.mkdir()
        for path, body in (
            (bin_dir / "sudo", SUDO_STUB),
            (bin_dir / "sysctl", SYSCTL_READ_STUB),
            (stub_bin / "sysctl", SYSCTL_WRITE_STUB),
        ):
            path.write_text(body)
            path.chmod(0o755)
        state = root / "state"
        state.write_text("".join(f"{key} {value}\n" for key, value in current.items()))
        vars_file = RUNNER_VARS
        if vars_text is not None:
            vars_file = root / "vars.yml"
            vars_file.write_text(vars_text)
        log = root / "sudo.log"
        log.touch()
        writes = root / "writes"
        writes.touch()
        env = {k: v for k, v in os.environ.items() if k != "BASH_ENV"}
        env.update(
            PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            STUB_LOG=str(log),
            STUB_BIN=str(stub_bin),
            STUB_STATE=str(state),
            STUB_WRITES=str(writes),
        )
        done = subprocess.run(
            ["bash", str(SCRIPT), str(vars_file)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return (
            done,
            log.read_text().splitlines(),  # nocheck: cache-read  stub call log
            writes.read_text().splitlines(),  # nocheck: cache-read  stub write log
        )


class TestRaiseSysctlFloors(unittest.TestCase):
    def test_runner_floor_exceeds_the_hosted_image_inotify_instances(self) -> None:
        self.assertGreater(int(runner_floors()[INSTANCES_KEY]), HOSTED_IMAGE_INSTANCES)

    def test_hosted_image_values_below_the_floor_are_raised_to_it(self) -> None:
        floors = runner_floors()
        done, calls, writes = run(HOSTED_IMAGE)
        self.assertEqual(done.returncode, 0, done.stderr)
        expected = [
            f"{key}={floor}"
            for key, floor in floors.items()
            if int(HOSTED_IMAGE[key]) < int(floor)
        ]
        self.assertIn(f"{INSTANCES_KEY}={floors[INSTANCES_KEY]}", expected)
        self.assertEqual(writes, expected)
        self.assertEqual(calls, [f"sysctl -w {entry}" for entry in expected])

    def test_values_at_or_above_the_floor_are_never_lowered(self) -> None:
        floors = runner_floors()
        higher = {key: str(int(floor) * 2) for key, floor in floors.items()}
        done, calls, writes = run(higher)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls, [])
        self.assertEqual(writes, [])
        self.assertEqual(
            done.stdout.splitlines(),
            [
                f"{key}={higher[key]} already meets the floor {floor}"
                for key, floor in floors.items()
            ],
        )

    def test_non_numeric_floor_fails_loudly_without_writing(self) -> None:
        done, calls, _ = run(
            {INSTANCES_KEY: "128"},
            f"RUNNER_SYSCTL_PARAMETERS:\n  {INSTANCES_KEY}: lots\n",
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("must be a non-negative integer", done.stderr)
        self.assertEqual(calls, [])

    def test_empty_parameters_fail_loudly(self) -> None:
        done, calls, _ = run({}, "RUNNER_SYSCTL_PARAMETERS: {}\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("is empty", done.stderr)
        self.assertEqual(calls, [])

    def test_unreadable_kernel_key_fails_loudly(self) -> None:
        done, calls, _ = run({}, f"RUNNER_SYSCTL_PARAMETERS:\n  {INSTANCES_KEY}: 8\n")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not a single integer", done.stderr)
        self.assertEqual(calls, [])


class TestWorkflowWiring(unittest.TestCase):
    def test_floor_step_is_act_gated_and_precedes_every_deploy_step(self) -> None:
        workflow = load_yaml(str(WORKFLOW))
        steps = next(
            job["steps"]
            for job in workflow["jobs"].values()
            if any(
                "raise_sysctl_floors.sh" in str(step.get("run", ""))
                for step in job.get("steps", [])
            )
        )
        runs = [str(step.get("run", "")) for step in steps]
        index = next(i for i, cmd in enumerate(runs) if "raise_sysctl_floors.sh" in cmd)
        self.assertEqual(
            runs[index],
            f"./scripts/github/runner/raise_sysctl_floors.sh {RUNNER_VARS_REL}",
        )
        self.assertEqual(steps[index].get("if"), "${{ !env.ACT }}")
        deploys = [
            i
            for i, cmd in enumerate(runs)
            if "scripts/tests/deploy/job/entry.sh" in cmd
        ]
        self.assertEqual(len(deploys), 2, runs)
        self.assertLess(index, min(deploys))


if __name__ == "__main__":
    unittest.main()
