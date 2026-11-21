from __future__ import annotations

import json
import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

ROLE = PROJECT_ROOT / "roles/web-app-snipe-it"
DOCKERFILE = ROLE / "files/Dockerfile"
PACKAGE = ROLE / "files/php/login_rbac/composer.json"
CLEAR = "artisan clear-compiled"
DISCOVER = "artisan package:discover"
MANIFEST = "bootstrap/cache/packages.php"
MASKING = ("|", ";")

_QUOTED_RE = re.compile(r"'[^']*'")

PIPED_TO_GREP = (
    "USER apache\n"
    "RUN composer require --no-scripts infinito/snipe-it-login-rbac:1.0.0 \\\n"
    "    && php artisan package:discover --no-ansi"
    " | grep -F infinito/snipe-it-login-rbac\n"
    "USER root\n"
)


def _discovery_steps(dockerfile: str) -> list[list[str]]:
    """Return the ``&&``-chained shell steps of every RUN that discovers packages.

    Args:
      dockerfile: text of the Dockerfile.
    """
    instructions = dockerfile.replace("\\\n", " ").splitlines()
    return [
        [step.strip() for step in line.removeprefix("RUN ").split("&&")]
        for line in instructions
        if line.startswith("RUN ") and DISCOVER in line
    ]


def _position(steps: list[str], command: str) -> int | None:
    """Return the index of the first step running ``command``.

    Args:
      steps: the ``&&``-chained shell steps of one RUN.
      command: the substring that identifies the step.
    """
    return next((index for index, step in enumerate(steps) if command in step), None)


def discovery_problems(dockerfile: str, package: str) -> list[str]:
    """Return why the image would not fail when discovery misses ``package``.

    Args:
      dockerfile: text of the Dockerfile.
      package: composer name of the package discovery has to register.
    """
    runs = _discovery_steps(dockerfile)
    if len(runs) != 1:
        return [f"expected one RUN with {DISCOVER}, found {len(runs)}"]
    steps = runs[0]
    problems = [
        f"step masks an exit status with a pipe or separator: {step}"
        for step in steps
        if any(operator in _QUOTED_RE.sub("''", step) for operator in MASKING)
    ]
    discover = _position(steps, DISCOVER)
    clear = _position(steps, CLEAR)
    if clear is None or clear > discover:
        problems.append(f"no {CLEAR} before {DISCOVER}: the stale manifest boots")
    if not any(
        step.startswith("php -r ") and MANIFEST in step and f'"{package}"' in step
        for step in steps[discover + 1 :]
    ):
        problems.append(f"no step after {DISCOVER} reads {package} from {MANIFEST}")
    return problems


def _rebuilt(steps: list[str]) -> str:
    """Return a one-instruction Dockerfile running ``steps`` as an ``&&`` chain.

    Args:
      steps: the shell steps of the RUN.
    """
    return f"RUN {' && '.join(steps)}\n"


class TestPackageDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.package = json.loads(read_text(str(PACKAGE)))["name"]
        self.steps = _discovery_steps(read_text(str(DOCKERFILE)))[0]

    def test_the_build_fails_when_discovery_misses_the_package(self) -> None:
        self.assertEqual(
            [], discovery_problems(read_text(str(DOCKERFILE)), self.package)
        )

    def test_negative_control_grep_on_the_discovery_output_is_rejected(self) -> None:
        problems = discovery_problems(PIPED_TO_GREP, self.package)
        self.assertEqual(3, len(problems), problems)

    def test_a_masked_manifest_check_is_rejected(self) -> None:
        for suffix in (" || true", "; true", " | cat"):
            with self.subTest(suffix=suffix):
                masked = [*self.steps[:-1], f"{self.steps[-1]}{suffix}"]
                self.assertTrue(discovery_problems(_rebuilt(masked), self.package))

    def test_dropping_a_step_is_rejected(self) -> None:
        for command in (CLEAR, MANIFEST):
            with self.subTest(dropped=command):
                kept = [step for step in self.steps if command not in step]
                self.assertTrue(discovery_problems(_rebuilt(kept), self.package))


if __name__ == "__main__":
    unittest.main()
