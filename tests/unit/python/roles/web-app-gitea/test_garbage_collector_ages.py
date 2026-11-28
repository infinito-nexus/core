import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_SERVICES = Path(PROJECT_ROOT) / "roles" / "web-app-gitea" / ROLE_FILE_META_SERVICES
_UNITS = {"s": 1, "m": 60, "h": 3600}


def _seconds(duration: str) -> int:
    return int(duration[:-1]) * _UNITS[duration[-1]]


class TestGiteaGcAges(unittest.TestCase):
    def setUp(self) -> None:
        self.gitea = load_yaml(_SERVICES)["gitea"]
        configuration = self.gitea["configuration"]
        self.timeouts = {
            "git.timeout.gc": configuration["git"]["timeout"]["gc"],
            "git.timeout.mirror": configuration["git"]["timeout"]["mirror"],
            "cron.git_gc_repos.timeout": _seconds(
                configuration["cron"]["git_gc_repos"]["timeout"]
            ),
        }

    def test_both_ages_outlast_every_git_timeout(self) -> None:
        for mode, minutes in self.gitea["garbage_collector"]["minutes"].items():
            for name, seconds in self.timeouts.items():
                with self.subTest(mode=mode, timeout=name):
                    self.assertGreater(minutes * 60, seconds)

    def test_pressure_only_shortens_the_routine_age(self) -> None:
        minutes = self.gitea["garbage_collector"]["minutes"]
        self.assertLessEqual(minutes["pressure"], minutes["routine"])

    def test_the_mirror_timeout_exceeds_the_upstream_default(self) -> None:
        self.assertGreater(self.timeouts["git.timeout.mirror"], 300)

    def test_the_gc_cron_timeout_keeps_the_upstream_default(self) -> None:
        self.assertGreaterEqual(self.timeouts["cron.git_gc_repos.timeout"], 3600)


if __name__ == "__main__":
    unittest.main()
