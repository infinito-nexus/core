import sqlite3
import tempfile
import unittest
from pathlib import Path

from ._fixtures import _uri, load

store = load("store")


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = store.Store(str(Path(self.tmp.name) / "state.sqlite"))

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_mobilizon_event_id_is_unique_across_records(self):
        self.store.put(_uri("a"), "c1", "9", 1.0)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.put(_uri("b"), "c1", "9", 1.0)


if __name__ == "__main__":
    unittest.main()
