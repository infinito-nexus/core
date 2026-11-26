"""Lint: the decider svc-ai-s1 owns is staged into each consumer, never copied.

``Sampler``, ``History``, ``record_of`` and ``Decider.judge_answers`` live in
``roles/svc-ai-s1/files/python/infinito_decider``, which owns the decider
contract, and svc-ai-litellm and web-svc-translate stage that package into their own
build context the way the MCP adapter's is staged per instance. A consumer
whose module list falls behind the package ships an import error at startup,
and a role that grows its own ``class History`` is the second copy the
extraction removed: the next fix to the contract would land in one of them.
"""

from __future__ import annotations

import re
import shlex
import unittest
from pathlib import Path, PurePosixPath

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml
from utils.docker.image.toolchain import instructions
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

PACKAGE = "roles/svc-ai-s1/files/python/infinito_decider"
PACKAGE_DIR = PROJECT_ROOT / PACKAGE
CONSUMERS = {"svc-ai-litellm": "LITELLM", "web-svc-translate": "TRANSLATE"}
STAGING_TASKS = "tasks/00_core.yml"
LITELLM_MOUNT = "/etc/litellm/infinito_decider/{module}"
TRANSLATE_SOURCE = "python/infinito_decider"
DEFINITION = re.compile(
    r"^[ \t]*(?:class (?:Sampler|History|Decider)\b|def record_of\b)", re.MULTILINE
)
MECHANISM = ["__init__.py", "history.py", "judge.py", "sampling.py"]


def package_modules() -> list[str]:
    """Return the module file names the shared package consists of."""
    return sorted(path.name for path in PACKAGE_DIR.glob("*.py"))


def staging_findings(
    role: str, prefix: str, variables: dict, tasks: str, modules: list[str]
) -> list[str]:
    """Return what keeps *role* from staging every module of the package.

    Args:
        role: the consumer role.
        prefix: its variable prefix, such as ``LITELLM``.
        variables: its parsed ``vars/main.yml``.
        tasks: the text of the task file that stages the package.
        modules: the module file names the package consists of.
    """
    findings = []
    source = str(variables.get(f"{prefix}_DECIDER_SOURCE_DIR", ""))
    if PACKAGE not in source:
        findings.append(f"{role}: {prefix}_DECIDER_SOURCE_DIR is not {PACKAGE}")
    staged = sorted(variables.get(f"{prefix}_DECIDER_MODULES") or [])
    if staged != modules:
        findings.append(
            f"{role}: {prefix}_DECIDER_MODULES stages {staged}, the package holds "
            f"{modules}"
        )
    if f'loop: "{{{{ {prefix}_DECIDER_MODULES }}}}"' not in tasks:
        findings.append(f"{role}: no task in {STAGING_TASKS} loops over the modules")
    return findings


def unmounted_modules(volumes: str, modules: list[str]) -> list[str]:
    """Return the modules svc-ai-litellm stages but does not mount.

    LiteLLM reads its hook from a config mount, so a staged module that is
    not mounted next to it is missing inside the container.

    Args:
        volumes: the text of svc-ai-litellm's ``meta/volumes.yml``.
        modules: the module file names the package consists of.
    """
    return [
        module
        for module in modules
        if LITELLM_MOUNT.format(module=module) not in volumes
    ]


def workdir_copies(dockerfile: str) -> list[str]:
    """
    Args:
        dockerfile: the Dockerfile's content.

    Returns:
        The build-context sources a ``COPY`` places directly inside the
        working directory in effect.
    """
    workdir = ""
    placed: list[str] = []
    for instruction in instructions(dockerfile):
        if instruction.keyword == "WORKDIR":
            workdir = instruction.args.rstrip("/")
        elif instruction.keyword == "COPY":
            *sources, target = (
                word
                for word in shlex.split(instruction.args)
                if not word.startswith("--")
            )
            placed.extend(
                source
                for source in sources
                if target.rstrip("/") == f"{workdir}/{PurePosixPath(source).name}"
            )
    return placed


def second_copies(files: list[tuple[str, str]]) -> list[str]:
    """Return one finding per decider definition outside the package.

    Args:
        files: ``(path relative to the project, content)`` pairs.
    """
    findings = []
    for path, content in files:
        if path.startswith(f"{PACKAGE}/"):
            continue
        for match in DEFINITION.finditer(content):
            line = content.count("\n", 0, match.start()) + 1
            findings.append(f"{path}:{line}: {match.group().strip()}")
    return findings


def role_sources() -> list[tuple[str, str]]:
    """Return ``(relative path, content)`` for every Python source under roles/."""
    sources = []
    for path, content in iter_project_files_with_content(
        extensions=(".py", ".py.j2"), exclude_tests=True
    ):
        relative = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if relative.startswith("roles/"):
            sources.append((relative, content))
    return sources


class TestDeciderStagedOnce(unittest.TestCase):
    def test_the_package_holds_the_mechanism(self) -> None:
        self.assertEqual(package_modules(), MECHANISM)

    def test_every_consumer_stages_every_module(self) -> None:
        modules = package_modules()
        findings = []
        for role, prefix in CONSUMERS.items():
            role_dir = PROJECT_ROOT / "roles" / role
            findings += staging_findings(
                role,
                prefix,
                load_yaml(role_dir / ROLE_FILE_VARS_MAIN),
                read_text(str(role_dir / STAGING_TASKS)),
                modules,
            )
        self.assertEqual(findings, [])

    def test_litellm_mounts_every_staged_module(self) -> None:
        volumes = read_text(
            str(PROJECT_ROOT / "roles/svc-ai-litellm" / ROLE_FILE_META_VOLUMES)
        )
        self.assertEqual(unmounted_modules(volumes, package_modules()), [])

    def test_the_gateway_image_carries_the_package(self) -> None:
        dockerfile = read_text(
            str(PROJECT_ROOT / "roles/web-svc-translate/files/Dockerfile")
        )
        self.assertIn(TRANSLATE_SOURCE, workdir_copies(dockerfile))

    def test_no_role_defines_the_mechanism_a_second_time(self) -> None:  # nocheck: test.text-presence -- policy lint over every Python source under roles/  # fmt: skip
        self.assertEqual(second_copies(role_sources()), [])

    def test_the_scan_reaches_the_package_itself(self) -> None:  # nocheck: test.text-presence -- vacuity guard on the role source scan  # fmt: skip
        """Without this the rule would pass on a scan that read nothing."""
        scanned = [path for path, _content in role_sources()]
        self.assertIn(f"{PACKAGE}/history.py", scanned)
        self.assertIn("roles/svc-ai-litellm/templates/router_hook.py.j2", scanned)


class TestDeciderStagedOnceRedFixtures(unittest.TestCase):
    TASKS = 'loop: "{{ LITELLM_DECIDER_MODULES }}"'

    def _variables(self, modules):
        return {
            "LITELLM_DECIDER_SOURCE_DIR": f"{{{{ lookup('path_absolute', '{PACKAGE}') }}}}",
            "LITELLM_DECIDER_MODULES": modules,
        }

    def test_a_consumer_staging_every_module_passes(self) -> None:
        self.assertEqual(
            staging_findings(
                "r", "LITELLM", self._variables(MECHANISM), self.TASKS, MECHANISM
            ),
            [],
        )

    def test_a_module_the_consumer_forgot_is_reported(self) -> None:
        findings = staging_findings(
            "r", "LITELLM", self._variables(MECHANISM[:-1]), self.TASKS, MECHANISM
        )
        self.assertEqual(len(findings), 1)
        self.assertIn("sampling.py", findings[0])

    def test_a_consumer_reading_another_source_is_reported(self) -> None:
        variables = self._variables(MECHANISM)
        variables["LITELLM_DECIDER_SOURCE_DIR"] = "roles/svc-ai-litellm/files"
        self.assertEqual(
            len(staging_findings("r", "LITELLM", variables, self.TASKS, MECHANISM)),
            1,
        )

    def test_a_consumer_that_stopped_looping_is_reported(self) -> None:
        self.assertEqual(
            len(
                staging_findings(
                    "r", "LITELLM", self._variables(MECHANISM), "", MECHANISM
                )
            ),
            1,
        )

    def test_an_unmounted_module_is_reported(self) -> None:
        volumes = "\n".join(
            LITELLM_MOUNT.format(module=module) for module in MECHANISM[:-1]
        )
        self.assertEqual(unmounted_modules(volumes, MECHANISM), ["sampling.py"])

    def test_a_copied_history_is_reported(self) -> None:
        files = [
            (f"{PACKAGE}/history.py", "class History:\n    pass\n"),
            ("roles/x/files/router.py", "import os\n\nclass History:\n    pass\n"),
            ("roles/y/templates/hook.py.j2", "def record_of(alias, tally):\n"),
        ]
        self.assertEqual(
            second_copies(files),
            [
                "roles/x/files/router.py:3: class History",
                "roles/y/templates/hook.py.j2:1: def record_of",
            ],
        )

    def test_a_name_that_merely_starts_alike_is_not_a_copy(self) -> None:
        files = [("roles/x/files/a.py", "class HistoryView:\n    pass\n")]
        self.assertEqual(second_copies(files), [])


if __name__ == "__main__":
    unittest.main()
