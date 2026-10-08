"""phpredis reads ``auth[user]``/``auth[pass]`` and ``prefix`` from the query of
``session.save_path``; a password with a reserved character that is not
percent-encoded splits the query and the handler authenticates with a fragment.
"""

from __future__ import annotations

import importlib
import unittest
from urllib.parse import parse_qs, urlsplit

plugin_module = importlib.import_module("plugins.lookup.engine")
redis_session_path = plugin_module.redis_session_path


class TestRedisSessionPath(unittest.TestCase):
    def test_an_embedded_sidecar_gets_no_credentials(self) -> None:
        self.assertEqual(
            "tcp://redis:6379?prefix=suitecrm:session:",
            redis_session_path("redis", 6379, "suitecrm", "", ""),
        )

    def test_a_shared_redis_gets_user_and_password(self) -> None:
        query = parse_qs(
            urlsplit(
                redis_session_path("redis-central", 6379, "suitecrm", "default", "pw")
            ).query
        )
        self.assertEqual(["default"], query["auth[user]"])
        self.assertEqual(["pw"], query["auth[pass]"])

    def test_a_password_with_reserved_characters_survives_the_query(self) -> None:
        password = "a&b=c?d#e/f+g h"
        query = parse_qs(
            urlsplit(
                redis_session_path("redis-central", 6379, "suitecrm", "default", password)
            ).query
        )
        self.assertEqual([password], query["auth[pass]"])
        self.assertEqual(["suitecrm:session:"], query["prefix"])

    def test_a_user_without_a_password_is_not_sent(self) -> None:
        self.assertNotIn(
            "auth", redis_session_path("redis", 6379, "suitecrm", "default", "")
        )


if __name__ == "__main__":
    unittest.main()
