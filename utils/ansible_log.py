"""SPOT for the line prefix Ansible writes into its ``log_path`` file.

Every line of the file named by ``ANSIBLE_LOG_PATH`` carries
``<ts> p=<pid> u=<user> n=<name> <LEVEL>| `` in front of the message that
also went to stdout. Left unstripped, that prefix defeats every
line-anchored matcher a reader applies, so a reader that mixes an anchored
match with an unanchored one silently sees an empty log instead of failing.
"""

from __future__ import annotations

import re

LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ p=\d+ u=\S+ n=\S+ (?:\w+)?\| ",
    re.MULTILINE,
)
