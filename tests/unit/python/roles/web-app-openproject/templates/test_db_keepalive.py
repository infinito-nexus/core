import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles/web-app-openproject"
COMPOSE = ROLE / ROLE_FILE_TEMPL_COMPOSE
ENV = ROLE / "templates/env.j2"
VARS = ROLE / ROLE_FILE_VARS_MAIN
MANAGER_OPS = ROLE / "tasks/01_manager_ops.yml"
SEEDER_WAIT_TASK = "⏳ Wait until the seeder has committed the seed (swarm)"
KERNEL_DEFAULT_KEEPALIVE_TIME = 7200
KEEPALIVE = {
    "net.ipv4.tcp_keepalive_time": "keepalives_idle",
    "net.ipv4.tcp_keepalive_intvl": "keepalives_interval",
    "net.ipv4.tcp_keepalive_probes": "keepalives_count",
}
VARIABLE = re.compile(r"^\{\{\s*(\w+)\s*\}\}$")
SYSCTLS = re.compile(r"^  sysctls:\n((?:    \S.*\n?)+)", re.MULTILINE)


def _variable(value: str) -> str:
    """
    Args:
      value: a template value, optionally double-quoted.

    Returns:
      the variable a `{{ NAME }}` value renders, else the value itself.
    """
    match = VARIABLE.match(value.strip().strip('"'))
    return match.group(1) if match else value


def _anchor_sysctls(compose: str) -> dict[str, str]:
    """
    Args:
      compose: text of compose.yml.j2.

    Returns:
      the sysctls of the x-op-app anchor every OpenProject app service merges.
    """
    anchor = compose.split("\n\n", 1)[0]
    match = SYSCTLS.search(anchor)
    if not match:
        return {}
    pairs = (line.strip().split(": ", 1) for line in match.group(1).splitlines())
    return {key: _variable(value) for key, value in pairs}


def _database_url_params(env: str) -> dict[str, str]:
    """
    Args:
      env: text of env.j2.

    Returns:
      the DATABASE_URL query parameters.
    """
    line = next(row for row in env.splitlines() if row.startswith("DATABASE_URL="))
    pairs = (param.split("=", 1) for param in line.split("?", 1)[1].split("&"))
    return {key: _variable(value) for key, value in pairs}


def _seeder_wait_seconds() -> int:
    """
    Returns:
      seconds the swarm deploy waits for the seeder to complete.
    """
    tasks = load_yaml_any(MANAGER_OPS)
    task = next(task for task in tasks if task.get("name") == SEEDER_WAIT_TASK)
    return int(task["retries"]) * int(task["delay"])


def _detection_seconds(idle: int, interval: int, count: int) -> int:
    """
    Args:
      idle: seconds before the first keepalive probe.
      interval: seconds between probes.
      count: unanswered probes before the socket errors out.

    Returns:
      seconds an idle socket to a vanished peer stays undetected.
    """
    return idle + interval * count


class TestDatabaseKeepalive(unittest.TestCase):
    def setUp(self):
        self.compose = read_text(str(COMPOSE))
        self.sysctls = _anchor_sysctls(self.compose)
        self.variables = load_yaml(VARS)

    def test_the_app_anchor_tunes_the_kernel_keepalive(self):
        self.assertEqual(set(self.sysctls), set(KEEPALIVE))

    def test_kernel_and_libpq_keepalive_share_one_source(self):
        params = _database_url_params(read_text(str(ENV)))
        for sysctl, param in KEEPALIVE.items():
            with self.subTest(sysctl=sysctl):
                self.assertIn(self.sysctls[sysctl], self.variables)
                self.assertEqual(self.sysctls[sysctl], params[param])

    def test_the_seeder_merges_the_app_anchor(self):
        seeder = self.compose.split(
            "{% set service_name = OPENPROJECT_SEEDER_SERVICE %}"
        )
        self.assertEqual(len(seeder), 2)
        self.assertIn("<<: *app", seeder[1].split("{% set service_name", 1)[0])

    def test_a_dead_peer_is_detected_before_the_seeder_wait_ends(self):
        idle, interval, count = (
            int(self.variables[self.sysctls[sysctl]]) for sysctl in KEEPALIVE
        )
        self.assertLess(
            _detection_seconds(idle, interval, count), _seeder_wait_seconds()
        )

    def test_negative_control_without_the_sysctls_psql_keeps_the_kernel_default(self):
        stripped = SYSCTLS.sub("", self.compose.split("\n\n", 1)[0])
        self.assertEqual(_anchor_sysctls(stripped), {})
        self.assertGreater(
            _detection_seconds(KERNEL_DEFAULT_KEEPALIVE_TIME, 75, 9),
            _seeder_wait_seconds(),
        )


if __name__ == "__main__":
    unittest.main()
