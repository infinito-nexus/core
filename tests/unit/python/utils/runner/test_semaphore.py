from __future__ import annotations

import hashlib
import hmac
import unittest

from utils.runner.semaphore import pool_runner_names, pool_runner_token
from utils.runner.store import JobError


class TestPoolRunnerNames(unittest.TestCase):
    def test_one_name_per_pool_runner_as_the_queue_knows_it(self) -> None:
        self.assertEqual(
            pool_runner_names("runner", 3), ["runner-1", "runner-2", "runner-3"]
        )

    def test_no_runner_no_name(self) -> None:
        self.assertEqual(pool_runner_names("runner", 0), [])

    def test_negative_control_a_prefix_that_is_no_runner_name_is_refused(self) -> None:
        with self.assertRaises(JobError):
            pool_runner_names("../runner", 1)


class TestPoolRunnerToken(unittest.TestCase):
    def test_the_token_is_the_hmac_of_the_name_under_the_secret(self) -> None:
        expected = hmac.new(b"secret", b"runner-1", hashlib.sha256).hexdigest()
        self.assertEqual(pool_runner_token("secret", "runner-1"), expected)

    def test_negative_control_another_runner_or_secret_gets_another_token(
        self,
    ) -> None:
        token = pool_runner_token("secret", "runner-1")
        self.assertNotEqual(token, pool_runner_token("secret", "runner-2"))
        self.assertNotEqual(token, pool_runner_token("other", "runner-1"))

    def test_an_empty_secret_or_name_is_refused(self) -> None:
        for secret, runner in (("", "runner-1"), ("secret", " ")):
            with (
                self.subTest(secret=secret, runner=runner),
                self.assertRaises(JobError),
            ):
                pool_runner_token(secret, runner)


if __name__ == "__main__":
    unittest.main()
