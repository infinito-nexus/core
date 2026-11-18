from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

ROLES = ("svc-ai-nllb-engine", "svc-ai-s1")
PIN = "AI_TORCH_VERSION"
GROUP_VARS = PROJECT_ROOT / "group_vars" / "all" / "16_ai.yml"
TORCH = 'TORCH="torch==${TORCH_VERSION:?'
PINNED = '"${TORCH}"'
BUILD_ARG = 'TORCH_VERSION: "{{ AI_TORCH_VERSION }}"'
BUILD_RUN = "RUN bash /usr/local/bin/build.sh"
TORCH_TOKEN = re.compile(r'^"?torch(?:[=<>!~\[" ]|$)')
VERSION_LITERAL = re.compile(r"torch(?:==|>=|~=)[0-9]|TORCH_VERSION=[0-9]")
UNPINNED_S1 = (
    'if [ "${S1_GPU}" = "true" ]; then\n'
    "\tpip install --no-cache-dir torch\n"
    "else\n"
    "\tpip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch\n"
    "fi\n"
)


def _texts(role: str) -> dict[str, str]:
    base = PROJECT_ROOT / "roles" / role
    return {
        "build": read_text(str(base / "files" / "shell" / "build.sh")),
        "dockerfile": read_text(str(base / "files" / "Dockerfile")),
        "compose": read_text(str(base / ROLE_FILE_TEMPL_COMPOSE)),
    }


def _unpinned(build: str) -> list[str]:
    return [
        line.strip()
        for line in build.splitlines()
        if "pip install" in line
        and any(TORCH_TOKEN.match(token) and token != PINNED for token in line.split())
    ]


def _findings(texts: dict[str, str]) -> list[str]:
    build, dockerfile = texts["build"], texts["dockerfile"]
    found = [f"installs torch unpinned: {line}" for line in _unpinned(build)]
    if TORCH not in build:
        found.append("the torch requirement does not come from TORCH_VERSION")
    if VERSION_LITERAL.search(build):
        found.append("the build pins torch itself instead of AI_TORCH_VERSION")
    if BUILD_ARG not in texts["compose"]:
        found.append("the compose build does not pass AI_TORCH_VERSION")
    lines = dockerfile.splitlines()
    run = lines.index(BUILD_RUN) if BUILD_RUN in lines else -1
    if "ARG TORCH_VERSION" not in lines[: max(run, 0)]:
        found.append("the Dockerfile does not declare TORCH_VERSION before the build")
    return found


class TestTorchPin(unittest.TestCase):
    def test_every_build_installs_torch_at_the_one_pin(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(_findings(_texts(role)), [])

    def test_the_pin_is_declared_once(self) -> None:
        self.assertRegex(
            str(load_yaml(str(GROUP_VARS))[PIN]), r"^[0-9]+\.[0-9]+\.[0-9]+$"
        )
        group_vars = f"{PROJECT_ROOT / 'group_vars'}{os.sep}"
        holders = [
            Path(path).relative_to(PROJECT_ROOT).as_posix()
            for path in iter_project_files(extensions=(".yml",))
            if path.startswith(group_vars)
            and re.search(rf"^{PIN}:", read_text(path), re.MULTILINE)
        ]
        self.assertEqual(holders, ["group_vars/all/16_ai.yml"])

    def test_the_guard_reports_an_unpinned_and_a_self_pinned_build(self) -> None:
        texts = _texts("svc-ai-s1")
        start = texts["build"].index('if [ "${S1_GPU}" = "true" ]; then\n')
        end = texts["build"].index("fi\n", start) + len("fi\n")
        unpinned = dict(
            texts, build=texts["build"][:start] + UNPINNED_S1 + texts["build"][end:]
        )
        self.assertEqual(
            [f for f in _findings(unpinned) if f.startswith("installs torch unpinned")],
            [
                "installs torch unpinned: pip install --no-cache-dir torch",
                (
                    "installs torch unpinned: pip install --no-cache-dir --index-url "
                    "https://download.pytorch.org/whl/cpu torch"
                ),
            ],
        )
        self_pinned = dict(
            texts,
            build=texts["build"].replace(
                TORCH, 'TORCH_VERSION=2.9.1\nTORCH="torch==${TORCH_VERSION:?'
            ),
        )
        self.assertIn(
            "the build pins torch itself instead of AI_TORCH_VERSION",
            _findings(self_pinned),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
