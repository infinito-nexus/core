from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache.files import (
    is_translation_catalog,
    iter_non_ignored_files,
    read_text,
)
from utils.env.handlers.infinito.cache.host.sync import KEY

from . import PROJECT_ROOT

READERS = {
    "Makefile",
    "default.env",
    "utils/cache/host_sync.py",
    "utils/env/handlers/infinito/cache/host/sync.py",
}


class TestCacheHostSyncKeyReaders(unittest.TestCase):
    def test_only_the_host_sync_reads_the_key(self) -> None:
        readers = set()
        for path in iter_non_ignored_files(exclude_tests=True, exclude_dirs=("docs",)):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            if is_translation_catalog(rel):
                continue
            try:
                text = read_text(path)
            except (OSError, UnicodeDecodeError):
                continue
            if KEY in text:
                readers.add(rel)
        self.assertEqual(
            readers,
            READERS,
            f"{KEY} drives `make cache-host-sync` alone; a renderer reading it "
            "breaks the byte-identity of every render with the sync off",
        )


if __name__ == "__main__":
    unittest.main()
