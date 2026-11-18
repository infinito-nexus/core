import ast
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text

DOCKERFILE = PROJECT_ROOT / "roles/web-app-openproject/files/Dockerfile"
INITIALIZERS = "/app/config/initializers/"
LOAD_FLAGS = "ActiveRecord::Tasks::DatabaseTasks.structure_load_flags"


def _steps(dockerfile: str) -> list[list[str]]:
    """Return every RUN instruction as its list of `&&`-chained shell steps.

    Args:
      dockerfile: text of the Dockerfile.
    """
    instructions = dockerfile.replace("\\\n", " ").splitlines()
    return [
        [step.strip() for step in line.removeprefix("RUN ").split("&&")]
        for line in instructions
        if line.startswith("RUN ")
    ]


def _without_initializers(dockerfile: str) -> str:
    """Return the RUN instructions with every step that writes an initializer dropped.

    Args:
      dockerfile: text of the Dockerfile.
    """
    runs = [
        " && ".join(step for step in steps if INITIALIZERS not in step)
        for steps in _steps(dockerfile)
    ]
    return "\n".join(f"RUN {run}" for run in runs if run)


def _initializers(dockerfile: str) -> dict[str, str]:
    """Run every step that writes a Rails initializer and return what it wrote.

    Args:
      dockerfile: text of the Dockerfile.

    Returns:
      The written initializers, keyed by file name.
    """
    commands = [
        step for steps in _steps(dockerfile) for step in steps if INITIALIZERS in step
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for command in commands:
            subprocess.run(
                ["sh", "-c", command.replace(INITIALIZERS, f"{tmp}/")], check=True
            )
        return {path.name: read_text(str(path)) for path in Path(tmp).iterdir()}


def _load_flags(dockerfile: str) -> list[str] | None:
    """Return the psql flags the image adds to the Rails schema load.

    Args:
      dockerfile: text of the Dockerfile.
    """
    for source in _initializers(dockerfile).values():
        target, _, value = source.strip().partition(" = ")
        if target == LOAD_FLAGS:
            return ast.literal_eval(value)
    return None


class TestSchemaLoad(unittest.TestCase):
    def test_the_schema_load_runs_in_one_transaction(self):
        flags = _load_flags(read_text(str(DOCKERFILE)))
        self.assertEqual(flags, ["--single-transaction"])

    def test_the_initializer_loads_after_the_upstream_ones(self):
        names = list(_initializers(read_text(str(DOCKERFILE))))
        self.assertEqual(len(names), 1)
        self.assertTrue(names[0].startswith("zz_"))
        self.assertTrue(names[0].endswith(".rb"))

    def test_negative_control_without_the_initializer_the_load_autocommits(self):
        dockerfile = read_text(str(DOCKERFILE))
        upstream = _without_initializers(dockerfile)
        self.assertNotEqual(_steps(upstream), _steps(dockerfile))
        self.assertIsNone(_load_flags(upstream))


if __name__ == "__main__":
    unittest.main()
