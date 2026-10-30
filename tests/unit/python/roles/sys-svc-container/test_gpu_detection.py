"""Which hosts the role treats as GPU hosts.

A privileged container, such as a swarm lab node on a workstation with an
NVIDIA card, sees the host's ``/dev/nvidia0`` but carries no driver, so
``nvidia-smi`` does not exist there. The device node alone must therefore not
make a GPU host: both the GPU include and the ``gpu`` lookup read the same
register, and both have to say no on such a host.
"""

import unittest
from pathlib import Path

from jinja2 import Environment

from plugins.lookup.gpu import _device_present
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE = Path(PROJECT_ROOT) / "roles" / "sys-svc-container"
CORE = ROLE / "tasks" / "00_core.yml"
GPU_INCLUDE = "00_core/gpu.yml"
DEVICE = "/dev/nvidia0"

_ENV = Environment(autoescape=True)
_ENV.tests["skipped"] = lambda result: (
    isinstance(result, dict) and bool(result.get("skipped"))
)


def _role_vars() -> dict:
    return load_yaml_any(str(ROLE / "vars" / "main.yml"))


def _render(value: str, context: dict) -> str:
    return _ENV.from_string(value).render(**context)


def _holds(task: dict, context: dict) -> bool:
    when = task.get("when", [])
    guards = when if isinstance(when, list) else [when]
    return all(bool(_ENV.compile_expression(expr)(**context)) for expr in guards)


def _walk(*, driver: bool, device: bool) -> tuple[bool, dict]:
    """Run the GPU detection of 00_core.yml over a fake filesystem.

    Args:
        driver: whether the NVIDIA driver binary exists on the host.
        device: whether the host shows an NVIDIA device node.

    Returns:
        Whether the GPU include runs, and the registers the tasks left.
    """
    context = dict(_role_vars())
    existing = {
        _render(context["SYS_SVC_CONTAINER_GPU_DRIVER"], context): driver,
        DEVICE: device,
    }
    included = False
    for task in load_yaml_any(str(CORE)):
        stat = task.get("ansible.builtin.stat")
        if stat is not None:
            register = task["register"]
            if not _holds(task, context):
                context[register] = {"changed": False, "skipped": True}
                continue
            path = _render(stat["path"], context)
            context[register] = {"stat": {"exists": existing.get(path, False)}}
        elif task.get("include_tasks") == GPU_INCLUDE:
            included = _holds(task, context)
    return included, context


class TestGpuDetection(unittest.TestCase):
    def test_a_device_node_without_the_driver_is_no_gpu_host(self):
        included, registers = _walk(driver=False, device=True)
        self.assertFalse(
            included,
            "a privileged container sees the host's /dev/nvidia0 without "
            "nvidia-smi; the include would fail on the missing binary",
        )
        self.assertFalse(_device_present(registers))

    def test_driver_and_device_make_a_gpu_host(self):
        included, registers = _walk(driver=True, device=True)
        self.assertTrue(included)
        self.assertTrue(_device_present(registers))

    def test_a_driver_without_a_device_is_no_gpu_host(self):
        included, registers = _walk(driver=True, device=False)
        self.assertFalse(included)
        self.assertFalse(_device_present(registers))

    def test_neither_is_no_gpu_host(self):
        included, registers = _walk(driver=False, device=False)
        self.assertFalse(included)
        self.assertFalse(_device_present(registers))

    def test_the_query_runs_the_binary_the_detection_probed(self):
        role_vars = _role_vars()
        self.assertTrue(
            role_vars["SYS_SVC_CONTAINER_GPU_QUERY"].startswith(
                "{{ SYS_SVC_CONTAINER_GPU_DRIVER }} "
            )
        )


if __name__ == "__main__":
    unittest.main()
