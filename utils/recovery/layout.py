"""Fallback shape for a generation that cannot state its own.

baudolo owns these values and writes them into every generation's manifest, so
:func:`utils.recovery.manifest.layout_of` is what callers ask. These literals
answer only for generations written before the manifest existed - those cannot
describe themselves, and nothing else can tell a reader what they used.

Literals rather than an import because the code that reads a generation runs on
swarm nodes, the NFS server and bare rescue hosts, which carry a git checkout
and no baudolo; this module must stay import-free for that reason. The
agreement is enforced by
``tests/lint/repository/dependencies/test_baudolo_pin.py``.
"""

from __future__ import annotations

SQL_DIR = "sql"
FILES_DIR = "files"
DUMP_SUFFIX = ".backup.sql"
CLUSTER_SUFFIX = ".cluster.backup.sql"

MANIFEST_FILE = "manifest.json"
MANIFEST_SCHEMA = 1
