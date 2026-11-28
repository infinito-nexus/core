from __future__ import annotations

import importlib
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.lint.repository import dockerfile_instructions
from utils import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

gates = importlib.import_module(
    "tests.unit.python.roles.svc-ai-models.test_engine_gates"
)

PIN = "AI_TORCH_VERSION"
TORCH_PIN = "9.8.7"
GROUP_VARS = PROJECT_ROOT / "group_vars" / "all" / "16_ai.yml"
TORCH = 'TORCH="torch==${TORCH_VERSION:?'
BUILD_RUN = "bash /usr/local/bin/build.sh"
BUILD_CONTEXT = "build:\n  context: .\n  dockerfile: Dockerfile"
COMPOSE_BASE = {"roles/sys-svc-compose/templates/base.yml.j2": "services:\n"}
TORCH_TOKEN = re.compile(r"^torch(?:[=<>!~\[]|$)")
STUBBED = ("apt-get", "hf", "mkdir", "pip", "python", "rm")
STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "${0##*/} $*" >>"${STUB_LOG}"\n'
BUILDS = {
    "svc-ai-nllb-engine": [
        {"NLLB_SERVICE": "nllb-engine", "NLLB_GPU": gpu} for gpu in ("true", "false")
    ],
    "svc-ai-s1": [
        {
            "S1_GPU": gpu,
            "S1_FLAVOR": flavor,
            "S1_LAYA_REPOS": "org/laya-a,org/laya-b",
            "S1_JEFF_REPOSITORY": "https://git.example.org/jeff.git",
            "S1_JEFF_REF": "0123456789abcdef",
            "S1_JEFF_MODEL_REPO": "org/jeff",
            "S1_JEFF_MODEL_PATH": "/models/jeff",
            "S1_JEFF_IMAGE_MODEL_PATH": "/opt/jeff",
        }
        for gpu in ("true", "false")
        for flavor in ("laya", "torch", "onnx")
    ],
}
UNDECLARED = (
    ("dockerfile", "ARG TORCH_VERSION\n"),
    ("compose", '        TORCH_VERSION: "{{ AI_TORCH_VERSION }}"\n'),
)
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


def _build_args(compose: str, variables: dict) -> dict:
    """
    Args:
        compose: the role's compose template.
        variables: the variables it reads beside ``AI_TORCH_VERSION``.

    Returns:
        The build args of the one service the rendered compose file builds.
    """
    rendered = gates.render(
        compose,
        {**variables, PIN: TORCH_PIN},
        lambda name, *_terms, **_kwargs: BUILD_CONTEXT if name == "template" else "",
        includes=COMPOSE_BASE,
    )
    (args,) = [
        service["build"]["args"]
        for service in load_yaml_str(rendered)["services"].values()
        if "build" in service
    ]
    return args


def _declared(dockerfile: str) -> set[str]:
    """
    Args:
        dockerfile: text of the Dockerfile.

    Returns:
        The build args its stage declares before the build step, the only
        ones Docker hands to that step's environment.
    """
    declared: set[str] = set()
    for keyword, arguments in dockerfile_instructions(dockerfile):
        if keyword == "FROM":
            declared = set()
        elif keyword == "ARG":
            declared.add(arguments.split("=", 1)[0])
        elif keyword == "RUN" and arguments == BUILD_RUN:
            return declared
    return set()


def _build(
    texts: dict[str, str], variables: dict
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Args:
        texts: the role's build script, Dockerfile and compose template.
        variables: the compose variables of one build variant.

    Returns:
        The finished build and every torch requirement its pip calls install.
    """
    declared = _declared(texts["dockerfile"])
    env = {
        name: str(value)
        for name, value in _build_args(texts["compose"], variables).items()
        if name in declared and value is not None
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_dir, script, log = root / "bin", root / "build.sh", root / "calls.log"
        bin_dir.mkdir()
        log.touch()
        script.write_text(texts["build"], encoding="utf-8")
        for name in STUBBED:
            (bin_dir / name).write_text(STUB, encoding="utf-8")
            (bin_dir / name).chmod(0o755)
        done = subprocess.run(
            ["bash", str(script)],
            cwd=root,
            env={
                **env,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        written = log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    torch = [
        token
        for call in written.splitlines()
        if call.startswith("pip ")
        for token in call.split()[1:]
        if TORCH_TOKEN.match(token)
    ]
    return done, torch


class TestTorchPin(unittest.TestCase):
    def test_every_build_installs_torch_at_the_one_pin(self) -> None:
        for role, variants in BUILDS.items():
            texts = _texts(role)
            for variables in variants:
                with self.subTest(role=role, variables=variables):
                    done, torch = _build(texts, variables)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(set(torch), {f"torch=={TORCH_PIN}"})

    def test_the_pin_is_declared_once(self) -> None:  # nocheck: test.text-presence -- parses the pin from group_vars YAML and lints all group_vars for a second holder  # fmt: skip
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

    def test_negative_control_an_unpinned_or_self_pinned_build_is_caught(
        self,
    ) -> None:
        texts = _texts("svc-ai-s1")
        start = texts["build"].index('if [ "${S1_GPU}" = "true" ]; then\n')
        end = texts["build"].index("fi\n", start) + len("fi\n")
        for build in (
            texts["build"][:start] + UNPINNED_S1 + texts["build"][end:],
            texts["build"].replace(
                TORCH, 'TORCH_VERSION=2.9.1\nTORCH="torch==${TORCH_VERSION:?'
            ),
        ):
            with self.subTest(build=build):
                self.assertNotEqual(build, texts["build"])
                _done, torch = _build({**texts, "build": build}, BUILDS["svc-ai-s1"][0])
                self.assertNotEqual(set(torch), {f"torch=={TORCH_PIN}"})

    def test_negative_control_a_pin_the_build_step_never_gets_fails_the_build(
        self,
    ) -> None:
        for role, variants in BUILDS.items():
            texts = _texts(role)
            for key, line in UNDECLARED:
                with self.subTest(role=role, source=key):
                    dropped = texts[key].replace(line, "")
                    self.assertNotEqual(dropped, texts[key])
                    done, torch = _build({**texts, key: dropped}, variants[0])
                    self.assertNotEqual(done.returncode, 0)
                    self.assertEqual(torch, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
