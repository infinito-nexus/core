import shlex
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

_CORE = PROJECT_ROOT / "roles" / "svc-db-redis" / "tasks" / "00_core.yml"
_CARRY = "Keep accepting the replaced passwords"
_HASHES = ["a" * 64, "b" * 64]


def _carry_command() -> str:
    tasks = load_yaml_any(str(_CORE))
    task = next(task for task in tasks if _CARRY in str(task.get("name", "")))
    return task["ansible.builtin.shell"]


class TestCarryCommand(unittest.TestCase):
    def _inner_words(self, hashes: list[str]) -> list[str]:
        variables = {
            "REDIS_EXEC_SHELL": "container exec redis sh -lc",
            "REDIS_CLI": 'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli',
            "redis_retired_password_hashes": hashes,
        }
        rendered = Templar(loader=DataLoader(), variables=variables).template(
            trust_as_template(_carry_command())
        )
        outer = shlex.split(rendered)
        self.assertEqual(outer[:5], ["container", "exec", "redis", "sh", "-lc"])
        self.assertEqual(len(outer), 6, "the in-container script must stay one word")
        return shlex.split(outer[5], comments=True)

    def test_every_replaced_hash_reaches_redis_as_its_own_argument(self):
        words = self._inner_words(_HASHES)
        self.assertEqual(
            words[words.index("SETUSER") + 1 :],
            ["default", *(f"#{value}" for value in _HASHES)],
        )

    def test_a_single_hash_is_not_read_as_a_shell_comment(self):
        self.assertEqual(self._inner_words(_HASHES[:1])[-1], f"#{_HASHES[0]}")


if __name__ == "__main__":
    unittest.main()
