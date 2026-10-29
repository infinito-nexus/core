import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-svc-container"
EGRESS_MTUS = (1200, 1280, 1400, 1500, 9000)
IPV4_ICMP_HEADER_BYTES = 28
INTERNET_MTU = 1500

_ENV = NativeEnvironment(undefined=StrictUndefined)


def _render(value, context):
    if isinstance(value, str) and "{{" in value:
        return _ENV.from_string(value).render(context)
    return value


def _task(tasks, register):
    return next(task for task in tasks if task.get("register") == register)


def _option(argv, flag):
    return int(argv[argv.index(flag) + 1])


class TestAutomtuProbeWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = load_yaml_any(ROLE / "tasks" / "_mtu.yml")
        networks = load_yaml_any(
            PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"
        )
        cls.context = {
            "ansible_python_interpreter": "python3",
            "NETWORK_PUBLIC_DNS_RESOLVERS": networks["NETWORK_PUBLIC_DNS_RESOLVERS"],
        }
        for key, value in load_yaml_any(ROLE / ROLE_FILE_VARS_MAIN).items():
            if key.startswith("SYS_SVC_DOCKER_AUTOMTU_"):
                cls.context[key] = _render(value, cls.context)

    def _detect_argv(self, egress_mtu):
        task = _task(self.tasks, "automtu_mtu")
        context = {**self.context, "automtu_egress": {"stdout": str(egress_mtu)}}
        for key, value in task["vars"].items():
            context[key] = _render(value, context)
        return [
            str(_render(arg, context))
            for arg in task["ansible.builtin.command"]["argv"]
        ]

    def test_the_probe_window_is_one_size_at_the_largest_reachable_mtu(self) -> None:
        for egress_mtu in EGRESS_MTUS:
            with self.subTest(egress_mtu=egress_mtu):
                argv = self._detect_argv(egress_mtu)
                low = _option(argv, "--pmtu-min-payload")
                high = _option(argv, "--pmtu-max-payload")
                self.assertEqual(
                    low,
                    high,
                    "a binary search turns every lost echo into a lower MTU; a "
                    "one-size window confirms the ceiling and only searches "
                    "below it when that size fails",
                )
                self.assertEqual(
                    high + IPV4_ICMP_HEADER_BYTES,
                    min(egress_mtu, INTERNET_MTU),
                    "automtu returns min(egress, measured): a probe above the egress "
                    "MTU or above the internet MTU only buys a 1 s timeout, a probe "
                    "below it lowers the result",
                )

    def test_one_target_confirming_the_window_decides(self) -> None:
        argv = self._detect_argv(1400)
        self.assertEqual(
            argv[argv.index("--pmtu-policy") + 1],
            "max",
            "under min one target's lost echoes lower daemon.json, and every "
            "change restarts dockerd; max keeps the largest size a target "
            "confirmed end to end, which never exceeds the egress MTU",
        )

    def test_the_window_comes_from_automtu_not_from_gathered_facts(self) -> None:
        egress = _task(self.tasks, "automtu_egress")
        argv = egress["ansible.builtin.command"]["argv"]
        self.assertEqual(argv[-2:], ["--print-mtu", "egress"])
        self.assertNotIn("--pmtu-target", argv)
        detect = _task(self.tasks, "automtu_mtu")
        self.assertLess(self.tasks.index(egress), self.tasks.index(detect))
        for fact in ("ansible_facts", "ansible_default_ipv4", "ansible_default_ipv6"):
            self.assertNotIn(
                fact,
                repr(detect),
                "this file installs iproute, so a fresh container gathered no "
                "network facts and default_ipv4 is undefined when the probe runs",
            )

    def test_every_target_answers_icmp_echo(self) -> None:
        self.assertNotIn(
            "registry-1.docker.io",
            self.context["SYS_SVC_DOCKER_AUTOMTU_TARGETS"],
            "registry-1.docker.io drops ICMP echo, so it only adds four 1 s "
            "timeouts to every deploy",
        )


if __name__ == "__main__":
    unittest.main()
