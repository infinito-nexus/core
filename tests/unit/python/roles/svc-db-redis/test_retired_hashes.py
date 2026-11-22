import hashlib
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

_CORE = PROJECT_ROOT / "roles" / "svc-db-redis" / "tasks" / "00_core.yml"
_PICK = "Pick the passwords a rotated REDIS_PASSWORD replaced"


def _sha(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


CURRENT = "example-new"
OLDER = _sha("example-older")
OLD = _sha("example-old")
NEW = _sha(CURRENT)


def _default_line(*hashes: str) -> str:
    accepted = " ".join(f"#{value}" for value in hashes)
    return f"user default on sanitize-payload {accepted} ~* &* +@all"


def _expression() -> str:
    tasks = load_yaml_any(str(_CORE))
    task = next(task for task in tasks if _PICK in str(task.get("name", "")))
    return task["ansible.builtin.set_fact"]["redis_retired_password_hashes"]


class TestRetiredHashes(unittest.TestCase):
    def _retired(self, acl_list):
        read = {"skipped": True} if acl_list is None else {"stdout_lines": acl_list}
        variables = {"redis_acl_before_restart": read, "REDIS_PASSWORD": CURRENT}
        return list(
            Templar(loader=DataLoader(), variables=variables).template(
                trust_as_template(_expression())
            )
        )

    def test_an_unchanged_password_retires_nothing(self):
        self.assertEqual(self._retired([_default_line(NEW)]), [])

    def test_a_rotated_password_retires_the_one_the_engine_accepted(self):
        self.assertEqual(self._retired([_default_line(OLD)]), [OLD])

    def test_passwords_an_aborted_pass_left_behind_are_retired_too(self):
        self.assertEqual(
            self._retired([_default_line(OLD, OLDER)]), sorted([OLD, OLDER])
        )

    def test_the_current_password_is_kept_when_the_engine_already_accepts_it(self):
        self.assertEqual(self._retired([_default_line(NEW, OLD)]), [OLD])

    def test_an_engine_that_was_not_read_retires_nothing(self):
        self.assertEqual(self._retired(None), [])

    def test_only_the_default_user_is_read(self):
        lines = [
            f"user cloud on #{OLD} ~cloud:* &* +@all",
            f"user default2 on #{OLDER} ~* &* +@all",
            _default_line(NEW),
        ]
        self.assertEqual(self._retired(lines), [])

    def test_tokens_that_are_no_password_hash_are_ignored(self):
        line = f"user default on #{OLD[:-1]} %R~#{OLDER} #{NEW} ~* &* +@all"
        self.assertEqual(self._retired([line]), [])


if __name__ == "__main__":
    unittest.main()
