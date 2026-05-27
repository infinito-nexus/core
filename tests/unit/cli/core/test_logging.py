import tempfile
import unittest
from pathlib import Path

from cli.core.run import open_log_file
from utils.cache.files import read_text


class TestLogging(unittest.TestCase):
    def test_open_log_file_creates_parents_and_writes(self):
        with tempfile.TemporaryDirectory() as td:
            # nested path to ensure parents=True behavior is exercised
            log_dir = Path(td) / "a" / "b" / "c" / "logs"

            self.assertFalse(log_dir.exists())
            f, path = open_log_file(log_dir)
            try:
                self.assertTrue(log_dir.exists())
                self.assertTrue(path.exists())
                self.assertIn(log_dir, path.parents)

                f.write("hello\n")
                f.flush()

                content = read_text(str(path))
                self.assertIn("hello", content)
            finally:
                f.close()


if __name__ == "__main__":
    unittest.main()
