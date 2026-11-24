import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

DOCKERFILE = PROJECT_ROOT / "roles/web-app-mobilizon/files/Dockerfile"
ERTS_LISTING = "ls -d /erts-*"
REMOVAL_HINT = "Drop this Dockerfile and the custom build of web-app-mobilizon"
SHIM_COPY = re.compile(r"^COPY --from=(\S+) (\S+) \$\{LD_PRELOAD\}$")


def _instructions(dockerfile: str) -> list[str]:
    """Return every instruction with its continuation lines joined.

    Args:
      dockerfile: text of the Dockerfile.
    """
    joined = dockerfile.replace("\\\n", "").splitlines()
    return [line.strip() for line in joined if line.strip()]


def _guard(dockerfile: str) -> str:
    """Return the shell command of the RUN instruction that reads the erts version.

    Args:
      dockerfile: text of the Dockerfile.
    """
    (command,) = [
        line.removeprefix("RUN ")
        for line in _instructions(dockerfile)
        if line.startswith("RUN ") and ERTS_LISTING in line
    ]
    return command


def _run_guard(*erts_dirs: str) -> subprocess.CompletedProcess:
    """Run the guard against a root that holds the given erts directories.

    Args:
      erts_dirs: directory names to create in the root, e.g. ``erts-16.4.0.2``.
    """
    command = _guard(read_text(str(DOCKERFILE))).replace(
        ERTS_LISTING, 'ls -d "$0"/erts-*'
    )
    with tempfile.TemporaryDirectory() as root:
        for name in erts_dirs:
            Path(root, name).mkdir()
        return subprocess.run(
            ["sh", "-c", command, root], capture_output=True, text=True, check=False
        )


def _shim_wiring_errors(dockerfile: str) -> list[str]:
    """Return why the last stage would not preload the shim the build stage compiles.

    Args:
      dockerfile: text of the Dockerfile.
    """
    instructions = _instructions(dockerfile)
    stages = [i for i, line in enumerate(instructions) if line.startswith("FROM ")]
    final = instructions[stages[-1] :]
    errors = []
    if not any(line.startswith("ENV LD_PRELOAD=/") for line in final):
        errors.append("the last stage sets no absolute LD_PRELOAD")
    copies = [match for line in final if (match := SHIM_COPY.match(line))]
    if len(copies) != 1:
        return [*errors, "the last stage copies no shim to ${LD_PRELOAD}"]
    stage, source = copies[0].groups()
    build = instructions[stages[0] : stages[-1]]
    if not build[0].endswith(f" AS {stage}"):
        errors.append(f"the copied stage {stage} is not the build stage")
    if not any(line.startswith("RUN ") and f"-o {source} " in line for line in build):
        errors.append(f"the build stage compiles nothing to {source}")
    return errors


class TestErtsGuard(unittest.TestCase):
    def test_an_erts_without_the_signal_stack_fix_builds(self):
        for erts in ("erts-16.4.0.2", "erts-16.4.0.7", "erts-17.0.6"):
            with self.subTest(erts=erts):
                result = _run_guard(erts)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_erts_with_the_signal_stack_fix_fails_and_names_the_removal(self):
        for erts in ("erts-17.1", "erts-17.1.1", "erts-18.0"):
            with self.subTest(erts=erts):
                result = _run_guard(erts)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(REMOVAL_HINT, result.stderr)

    def test_an_unreadable_erts_layout_fails_without_the_removal_hint(self):
        for erts_dirs in ((), ("erts-16.4.0.2", "erts-17.1")):
            with self.subTest(erts_dirs=erts_dirs):
                result = _run_guard(*erts_dirs)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(REMOVAL_HINT, result.stderr)


class TestShimWiring(unittest.TestCase):
    def test_the_last_stage_preloads_the_shim_the_build_stage_compiles(self):
        self.assertEqual(_shim_wiring_errors(read_text(str(DOCKERFILE))), [])

    def test_negative_control_a_copy_to_another_path_is_reported(self):
        dockerfile = read_text(str(DOCKERFILE)).replace(
            "${LD_PRELOAD}", "/usr/lib/libsigaltstack.so"
        )
        self.assertNotEqual(_shim_wiring_errors(dockerfile), [])

    def test_negative_control_a_copy_of_an_uncompiled_file_is_reported(self):
        dockerfile = read_text(str(DOCKERFILE)).replace(
            "-o /tmp/libsigaltstack.so", "-o /tmp/other.so"
        )
        self.assertNotEqual(_shim_wiring_errors(dockerfile), [])


if __name__ == "__main__":
    unittest.main()
