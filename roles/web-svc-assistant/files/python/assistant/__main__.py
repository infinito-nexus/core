"""Rebuild the knowledge index: ``python -m assistant``.

The role runs this inside the container on every deploy, after it staged the
platform documentation, the README of every deployed role and the tenant
document sources into the knowledge directory.
"""

# nocheck: mirrored-unit-test - the entry point reads the container environment and writes to the live PostgreSQL; the build it drives is covered by test_index and the integration test

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from assistant import logs
from assistant.environment import dsn, models
from assistant.index import build
from assistant.sources import documents, load_manifest
from assistant.store import Store


def main() -> int:
    """Rebuild the index and log how many passages it holds."""
    logs.configure()
    env = os.environ
    knowledge = Path(env["ASSISTANT_KNOWLEDGE_DIR"])
    count = asyncio.run(
        build(
            documents(knowledge, load_manifest(knowledge)),
            models(env),
            Store(dsn(env), env["ASSISTANT_INDEX_TABLE"]),
            int(env["ASSISTANT_PASSAGE_CHARS"]),
        )
    )
    logging.getLogger("assistant").info("index_built", extra={"passages": count})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
