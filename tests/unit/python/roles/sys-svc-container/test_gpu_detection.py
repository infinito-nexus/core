"""Which hosts the role treats as GPU hosts.

A privileged container, such as a swarm lab node on a workstation with an
NVIDIA card, sees the host's ``/dev/nvidia0`` but carries no driver, so
``nvidia-smi`` does not exist there. The device node alone must therefore not
make a GPU host: the GPU include and the ``gpu`` lookup both have to say no
there, and a bare host in that state has to fail instead of silently running
its GPU services on the CPU.
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
NVIDIA_REGISTER = "sys_svc_container_nvidia_"

_ENV = Environment(autoescape=True)
_ENV.filters["bool"] = bool


def _role_vars() -> dict:
    return load_yaml_any(str(ROLE / "vars" / "main.yml"))


def _render(value: str, context: dict) -> str:
    return _ENV.from_string(value).render(**context)


def _all_hold(expressions, context: dict) -> bool:
    guards = expressions if isinstance(expressions, list) else [expressions]
    return all(bool(_ENV.compile_expression(expr)(**context)) for expr in guards)


def _walk(*, driver: bool, device: bool, in_container: bool) -> tuple[str, dict]:
    """Run the GPU detection of 00_core.yml over a fake filesystem.

    Args:
        driver: whether the NVIDIA driver binary exists on the host.
        device: whether the host shows an NVIDIA device node.
        in_container: whether the host is itself a container.

    Returns:
        "gpu" when the GPU include runs, "cpu" when it does not, "refused"
        when an assert stops the play; and the registers the tasks left.
    """
    context = dict(_role_vars())
    context["DOCKER_IN_CONTAINER"] = in_container
    existing = {
        _render(context["SYS_SVC_CONTAINER_GPU_DRIVER"], context): driver,
        DEVICE: device,
    }
    outcome = "cpu"
    for task in load_yaml_any(str(CORE)):
        stat = task.get("ansible.builtin.stat")
        assertion = task.get("ansible.builtin.assert")
        if assertion is not None and NVIDIA_REGISTER not in str(assertion["that"]):
            assertion = None
        gpu_include = task.get("include_tasks") == GPU_INCLUDE
        if stat is None and assertion is None and not gpu_include:
            continue
        if not _all_hold(task.get("when", []), context):
            continue
        if stat is not None:
            path = _render(stat["path"], context)
            context[task["register"]] = {"stat": {"exists": existing.get(path, False)}}
        elif assertion is not None and not _all_hold(assertion["that"], context):
            return "refused", context
        elif gpu_include:
            outcome = "gpu"
    return outcome, context


class TestGpuDetection(unittest.TestCase):
    def test_a_container_seeing_a_driverless_device_runs_on_the_cpu(self):
        outcome, registers = _walk(driver=False, device=True, in_container=True)
        self.assertEqual(
            outcome,
            "cpu",
            "a privileged container sees the host's /dev/nvidia0 without "
            "nvidia-smi; the include would fail on the missing binary",
        )
        self.assertFalse(_device_present(registers))

    def test_a_bare_host_with_a_driverless_device_is_refused(self):
        outcome, _ = _walk(driver=False, device=True, in_container=False)
        self.assertEqual(outcome, "refused")

    def test_driver_and_device_make_a_gpu_host(self):
        for in_container in (False, True):
            with self.subTest(in_container=in_container):
                outcome, registers = _walk(
                    driver=True, device=True, in_container=in_container
                )
                self.assertEqual(outcome, "gpu")
                self.assertTrue(_device_present(registers))

    def test_no_device_is_no_gpu_host(self):
        for driver in (False, True):
            for in_container in (False, True):
                with self.subTest(driver=driver, in_container=in_container):
                    outcome, registers = _walk(
                        driver=driver, device=False, in_container=in_container
                    )
                    self.assertEqual(outcome, "cpu")
                    self.assertFalse(_device_present(registers))

    def test_the_query_runs_the_binary_the_detection_probed(self):
        self.assertTrue(
            _role_vars()["SYS_SVC_CONTAINER_GPU_QUERY"].startswith(
                "{{ SYS_SVC_CONTAINER_GPU_DRIVER }} "
            )
        )


if __name__ == "__main__":
    unittest.main()
