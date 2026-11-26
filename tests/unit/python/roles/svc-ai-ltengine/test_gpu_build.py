"""What the gpu gate of svc-ai-ltengine decides about the build.

The binary is compiled against CUDA, so a host without a card must not get
that build: the runtime base ships cuBLAS but never ``libcuda.so.1``, which
the nvidia container runtime injects and which is therefore absent exactly
where the gate is closed. The cargo feature and the image tag both hang off
the gate.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = "svc-ai-ltengine"
SERVICE = "ltengine"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
SERVICES = ROLE_DIR / ROLE_FILE_META_SERVICES
DOCKERFILE = ROLE_DIR / "files" / "Dockerfile"
BASE_VERSION = "12.6.3-runtime-ubuntu24.04"
STUB = '#!/usr/bin/env bash\nprintf \'%s %s\\n\' "${0##*/}" "$*" >> "${STUB_LOG}"\n'


def _build_stage() -> list[tuple[str, str]]:
    """
    Returns:
        ``(INSTRUCTION, arguments)`` of the Dockerfile's ``build`` stage, its
        continuation lines joined.
    """
    stages: list[list[tuple[str, str]]] = []
    for line in re.sub(r"\\\n", " ", read_text(str(DOCKERFILE))).splitlines():
        keyword, _, arguments = line.strip().partition(" ")
        if keyword.upper() == "FROM":
            stages.append([(keyword.upper(), arguments.strip())])
        elif keyword and not keyword.startswith("#") and stages:
            stages[-1].append((keyword.upper(), arguments.strip()))
    (stage,) = [s for s in stages if s[0][1].split()[-2:] == ["AS", "build"]]
    return stage


def _cargo_argv(features: str) -> list[str]:
    """
    Args:
        features: the value the build passes as ``LTENGINE_FEATURES``.

    Returns:
        The arguments the build stage's cargo step hands to ``cargo``.
    """
    (step,) = [
        arguments
        for keyword, arguments in _build_stage()
        if keyword == "RUN" and arguments.startswith("cargo build")
    ]
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = Path(tmp) / "bin"
        bin_dir.mkdir()
        log = Path(tmp) / "calls.log"
        for name in ("cargo", "install"):
            stub = bin_dir / name
            stub.write_text(STUB, encoding="utf-8")
            stub.chmod(0o755)
        result = subprocess.run(
            ["bash", "-c", step],
            cwd=tmp,
            env={
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
                "LTENGINE_FEATURES": features,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        written = log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    calls = written.splitlines()
    (cargo,) = [call.split()[1:] for call in calls if call.split()[0] == "cargo"]
    return cargo


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestGpuBuild(unittest.TestCase):
    variables: ClassVar[dict] = load_yaml(str(VARS))
    services: ClassVar[dict] = load_yaml(str(SERVICES))

    def _render(self, key: str, gpu: bool) -> str:
        """Render one role variable with the gate answering ``gpu``.

        Args:
            key: the variable name in ``vars/main.yml``.
            gpu: what the ``gpu`` lookup answers.
        """
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        env.filters["bool"] = _ansible_bool
        env.globals["lookup"] = lambda name, *terms, **_kw: (
            gpu if name == "gpu" else BASE_VERSION
        )
        return env.from_string(self.variables[key]).render(
            application_id=ROLE,
            LTENGINE_GPU=gpu,
            LTENGINE_BASE_VERSION=BASE_VERSION,
        )

    def test_the_role_declares_the_gpu_flag(self) -> None:
        self.assertTrue(self.services[SERVICE].get("gpu"))

    def test_the_gate_asks_the_gpu_lookup_for_this_service(self) -> None:
        asked: list = []
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        env.globals["lookup"] = lambda name, *terms, **_kw: (
            asked.append((name, terms)) or True
        )

        env.from_string(self.variables["LTENGINE_GPU"]).render(application_id=ROLE)

        self.assertIn(("gpu", (ROLE, SERVICE)), asked)

    def test_a_card_selects_the_cuda_feature_and_tag(self) -> None:
        self.assertEqual(self._render("LTENGINE_FEATURES", True), "cuda")
        self.assertEqual(
            self._render("LTENGINE_IMAGE_VERSION", True), f"{BASE_VERSION}-cuda"
        )

    def test_no_card_builds_without_cuda_under_its_own_tag(self) -> None:
        self.assertEqual(self._render("LTENGINE_FEATURES", False), "")
        self.assertEqual(
            self._render("LTENGINE_IMAGE_VERSION", False),
            BASE_VERSION,
            "a CPU build under the GPU tag would be served to a card",
        )

    def test_the_build_stage_declares_the_feature_build_arg(self) -> None:  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        declared = {
            arguments.split("=", 1)[0]
            for keyword, arguments in _build_stage()
            if keyword == "ARG"
        }
        self.assertIn("LTENGINE_FEATURES", declared)

    def test_the_cargo_build_takes_the_feature_only_when_the_gate_sets_one(
        self,
    ) -> None:
        self.assertEqual(_cargo_argv("cuda")[-2:], ["--features", "cuda"])
        self.assertNotIn(
            "--features",
            _cargo_argv(""),
            "an unconditional feature would link libcuda on a host without one",
        )


if __name__ == "__main__":
    unittest.main()
