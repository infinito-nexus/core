"""The GPU keys of the shared resource template.

The template asks the ``gpu`` lookup and decides nothing itself: combining
the declared flag with the host's device is that lookup's job, and its own
tests own the matrix.

``runtime: nvidia`` alone hands the container nothing. The runtime's hook
reads ``NVIDIA_VISIBLE_DEVICES`` off the container's environment and is a
no-op while that is unset, so the two keys below belong to the same branch.
"""

import unittest
from pathlib import Path

from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils import PROJECT_ROOT

TEMPLATES = Path(PROJECT_ROOT) / "roles" / "sys-svc-container" / "templates"

BASE = {
    "application_id": "web-svc-libretranslate",
    "service_name": "libretranslate",
    "RESOURCE_CPUS": "1",
    "RESOURCE_HOST_CPUS": "8",
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
    "SYS_SVC_CONTAINER_GPU_DEVICES": "GPU-strong,GPU-weak",
    "NVIDIA_DRIVER_CAPABILITIES": "compute,utility",
}


class TestGpuRuntimeRegistration(unittest.TestCase):
    def _render(self, *, gpu):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["resource_filter"] = lambda _apps, _id, _key, _svc, default, **_k: (
            default
        )
        self.asked = []

        def _lookup(name, *terms, **_kwargs):
            self.asked.append((name, terms))
            return gpu if name == "gpu" else {}

        env.globals["lookup"] = _lookup
        return env.get_template("resource.yml.j2").render(BASE)

    def test_the_lookups_yes_reaches_the_runtime_key(self):
        self.assertIn("runtime:            nvidia", self._render(gpu=True))

    def test_the_lookups_no_leaves_the_runtime_key_out(self):
        self.assertNotIn("runtime:", self._render(gpu=False))

    def test_the_runtime_is_told_which_devices_to_hand_over(self):
        self.assertIn(
            'NVIDIA_VISIBLE_DEVICES:     "GPU-strong,GPU-weak"',
            self._render(gpu=True),
        )

    def test_the_runtime_is_told_to_inject_the_cuda_driver(self):
        self.assertIn(
            'NVIDIA_DRIVER_CAPABILITIES: "compute,utility"',
            self._render(gpu=True),
        )

    def test_the_lookups_no_leaves_the_device_env_out(self):
        self.assertNotIn("NVIDIA_VISIBLE_DEVICES", self._render(gpu=False))

    def test_the_lookup_is_asked_for_this_service(self):
        self._render(gpu=True)

        self.assertIn(
            ("gpu", ("web-svc-libretranslate", "libretranslate")),
            self.asked,
        )


if __name__ == "__main__":
    unittest.main()
