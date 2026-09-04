"""The read-only qdrant key never leaves the MCP adapter.

qdrant authenticates with two engine-wide keys and has no per-consumer
principals, so the only thing keeping the adapter unable to write is which key
it is handed. A consumer lookup that reached for the read-only key, or an
adapter that received the full one, would erase that boundary without any
declaration changing.
"""

from __future__ import annotations

import importlib
import unittest

plugin_module = importlib.import_module("plugins.lookup.engine")
qdrant_consumer_key = plugin_module.qdrant_consumer_key

SVC = "svc-db-qdrant"

BOTH_KEYS = {
    SVC: {
        "secrets": {
            "credentials": {
                "api_key": "full-access-key",
                "read_only_api_key": "read-only-key",
            }
        }
    }
}


class TestQdrantConsumerKey(unittest.TestCase):
    def test_a_data_owning_consumer_gets_the_full_key(self) -> None:
        self.assertEqual("full-access-key", qdrant_consumer_key(BOTH_KEYS, SVC))

    def test_the_read_only_key_is_never_handed_to_a_consumer(self) -> None:
        self.assertNotIn(
            "read-only-key",
            qdrant_consumer_key(BOTH_KEYS, SVC),
            "the adapter's read-only guarantee is that it holds this key and "
            "nothing else; handing it out elsewhere makes the key meaningless",
        )

    def test_an_engine_without_a_declared_key_yields_nothing(self) -> None:
        self.assertEqual("", qdrant_consumer_key({SVC: {}}, SVC))

    def test_an_absent_service_role_does_not_raise(self) -> None:
        self.assertEqual("", qdrant_consumer_key({}, SVC))

    def test_a_blank_key_does_not_render_as_whitespace(self) -> None:
        blank = {SVC: {"secrets": {"credentials": {"api_key": "  "}}}}
        self.assertEqual("", qdrant_consumer_key(blank, SVC))


if __name__ == "__main__":
    unittest.main()
