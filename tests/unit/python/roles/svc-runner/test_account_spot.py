from __future__ import annotations

import importlib
import unittest

from utils.cache.files import read_text

render = importlib.import_module("tests.unit.python.roles.svc-runner._render")

DOCKERFILE = render.ROLE / "files" / "Dockerfile"
LOCAL_SUITE = render.ROLE / "files" / "test" / "local.sh"
PASSED = {
    DOCKERFILE: ("USER ${RUNNER_USER}", "USER {name}"),
    LOCAL_SUITE: (
        "chown -R ${RUNNER_USER}:${RUNNER_USER}",
        "chown -R {name}:{name}",
    ),
}


def literal_lines(text: str, name: str) -> list[int]:
    """Args:
        text: a file of the role.
        name: the runner account's username.

    Returns:
        The numbers of the lines that spell the account name out.
    """
    return [
        number for number, line in enumerate(text.splitlines(), start=1) if name in line
    ]


class TestRunnerAccountSpot(unittest.TestCase):
    def test_the_image_and_the_suite_take_the_account_as_a_variable(self) -> None:
        name = render.runner_account()["username"]
        found = {
            str(path): literal_lines(read_text(str(path)), name) for path in PASSED
        }
        self.assertEqual(found, {str(path): [] for path in PASSED})

    def test_a_spelled_out_account_name_is_caught(self) -> None:
        name = render.runner_account()["username"]
        for path, (variable, literal) in PASSED.items():
            with self.subTest(path=str(path)):
                source = read_text(str(path))
                self.assertIn(variable, source)
                spelled = source.replace(variable, literal.format(name=name), 1)
                self.assertNotEqual(literal_lines(spelled, name), [])


if __name__ == "__main__":
    unittest.main()
