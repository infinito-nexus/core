"""What the gpu gate of svc-ai-ltengine decides about the build.

The binary is compiled against CUDA, so a host without a card must not get
that build: the runtime base ships cuBLAS but never ``libcuda.so.1``, which
the nvidia container runtime injects and which is therefore absent exactly
where the gate is closed. The cargo feature and the image tag both hang off
the gate.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import ClassVar

from jinja2 import Environment, StrictUndefined

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
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
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
        env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - renders an ansible var expression, not markup
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

    def test_the_dockerfile_passes_the_feature_through_as_a_build_arg(self) -> None:
        body = read_text(str(DOCKERFILE))

        self.assertIn("ARG LTENGINE_FEATURES", body)
        self.assertIn('${LTENGINE_FEATURES:+--features "${LTENGINE_FEATURES}"}', body)
        self.assertNotIn(
            "--features cuda",
            body,
            "an unconditional feature would link libcuda on a host without one",
        )


if __name__ == "__main__":
    unittest.main()
