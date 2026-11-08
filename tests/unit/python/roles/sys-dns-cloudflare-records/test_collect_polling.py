import unittest

from jinja2 import Environment, StrictUndefined

from plugins.lookup.timeout import scaled_timeout
from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_DEFAULTS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-dns-cloudflare-records"


def _defaults() -> dict:
    return load_yaml(str(ROLE / ROLE_FILE_DEFAULTS_MAIN))


def _collect_task() -> dict:
    return next(
        task
        for task in load_yaml_any(str(ROLE / "tasks" / "judge.yml"))
        if "ansible.builtin.async_status" in task
    )


def _render(expression: str, variables: dict, factor: int):
    """
    Args:
        expression: one templated value of the role.
        variables: the role defaults the expression may read.
        factor: the ``TIMEOUT_FACTOR`` the ``timeout`` lookup scales by.

    Returns:
        The rendered value as an integer.
    """
    environment = Environment(undefined=StrictUndefined, autoescape=True)
    environment.globals["lookup"] = lambda name, base: scaled_timeout(base, factor)
    return int(environment.from_string(str(expression)).render(**variables))


class TestCollectPolling(unittest.TestCase):
    def test_collect_polls_at_the_role_interval_and_retries_by_it(self):
        defaults = _defaults()
        task = _collect_task()

        self.assertEqual(task["delay"], "{{ cloudflare_collect_interval | int }}")
        self.assertEqual(task["retries"], "{{ cloudflare_collect_retries | int }}")
        self.assertIn(
            "cloudflare_collect_interval", defaults["cloudflare_collect_retries"]
        )
        self.assertIn("_cf_collect_deadline", task["until"])

    def test_the_polling_window_covers_the_attempt_timeout(self):
        defaults = _defaults()
        task = _collect_task()
        for factor in (1, 2, 3):
            for interval in (1, 2, 5, 7):
                with self.subTest(factor=factor, interval=interval):
                    variables = dict(defaults, cloudflare_collect_interval=interval)
                    variables["cloudflare_collect_retries"] = _render(
                        defaults["cloudflare_collect_retries"], variables, factor
                    )
                    retries = _render(task["retries"], variables, factor)
                    delay = _render(task["delay"], variables, factor)
                    attempt = scaled_timeout(
                        defaults["cloudflare_attempt_timeout"], factor
                    )

                    self.assertEqual(delay, interval)
                    self.assertGreaterEqual(retries * delay, attempt)

    def test_the_default_interval_is_one_second(self):
        self.assertEqual(_defaults()["cloudflare_collect_interval"], 1)


if __name__ == "__main__":
    unittest.main()
