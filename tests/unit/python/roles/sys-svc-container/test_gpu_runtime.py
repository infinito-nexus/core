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
    "RESOURCE_MEM_LIMIT": "1g",
    "RESOURCE_MEM_RESERVATION": "256m",
    "RESOURCE_PIDS_LIMIT": "512",
}


def _ansible_bool(value):
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


class TestGpuRuntimeRegistration(unittest.TestCase):
    def _render(self, *, wants_gpu, host_has_gpu):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = _ansible_bool
        env.filters["resource_filter"] = lambda _apps, _id, key, _svc, default: (
            wants_gpu if key == "gpu" else default
        )
        env.globals["lookup"] = lambda name, *a, **k: {}
        device = {"stat": {"exists": host_has_gpu}}
        return env.get_template("resource.yml.j2").render(
            {**BASE, "sys_svc_container_nvidia_device": device}
        )

    def test_a_gpu_service_on_a_gpu_host_gets_the_nvidia_runtime(self):
        self.assertIn(
            "runtime:            nvidia",
            self._render(wants_gpu=True, host_has_gpu=True),
        )

    def test_a_gpu_service_on_a_host_without_a_card_gets_no_runtime(self):
        self.assertNotIn("runtime:", self._render(wants_gpu=True, host_has_gpu=False))

    def test_a_plain_service_never_gets_the_nvidia_runtime(self):
        for host_has_gpu in (True, False):
            with self.subTest(host_has_gpu=host_has_gpu):
                self.assertNotIn(
                    "runtime:",
                    self._render(wants_gpu=False, host_has_gpu=host_has_gpu),
                )

    def test_a_missing_device_fact_is_treated_as_no_gpu(self):
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATES)),
            trim_blocks=True,
            lstrip_blocks=False,
            undefined=StrictUndefined,
            autoescape=select_autoescape(),
        )
        env.filters["bool"] = _ansible_bool
        env.filters["resource_filter"] = lambda _apps, _id, key, _svc, default: (
            True if key == "gpu" else default
        )
        env.globals["lookup"] = lambda name, *a, **k: {}

        self.assertNotIn("runtime:", env.get_template("resource.yml.j2").render(BASE))


if __name__ == "__main__":
    unittest.main()
