"""Count the CONNECTs to one target in the journal of the workspace egress proxies.

Usage: ``journalctl --output=json ... | python3 -I egress_log.py SERVICE TARGET``

Args:
    SERVICE: the compose service of the workspace egress proxy.
    TARGET: ``<host>:<port>`` the egress spec asks the proxy for, which the
        proxy has to refuse.

Prints one ``OK``, ``FAIL`` or ``NOT RUN`` line holding counts and TARGET only
and never a journal line: the role's journal tag also carries the lines of the
Semaphore server and its runners. Exits 1 on ``FAIL`` and 2 on ``NOT RUN``.
"""

from __future__ import annotations

import json
import re
import sys

CONTAINER = "^semaphore-ws-[0-9a-f-]+-{service}-[0-9]+$"
CONNECT = re.compile(
    r"\s(?P<action>[A-Z_]+)/(?P<code>[0-9]{3})\s+[0-9]+\s+CONNECT\s+(?P<target>\S+)\s"
)
REFUSED = ("TCP_DENIED", "403")


def connects(lines, service, target):
    """Args:
        lines: ``journalctl --output=json`` lines.
        service: SERVICE.
        target: TARGET.

    Returns:
        ``(logged, refused, passed)``: the entries the workspace egress proxies
        wrote, their ``TCP_DENIED/403`` CONNECTs to ``target``, and their
        CONNECTs to ``target`` with any other result.
    """
    container = re.compile(CONTAINER.format(service=re.escape(service)))
    logged = refused = passed = 0
    for line in lines:
        if not line.strip():
            continue
        entry = json.loads(line)
        if not container.match(str(entry.get("CONTAINER_NAME", ""))):
            continue
        logged += 1
        found = CONNECT.search(f" {entry.get('MESSAGE', '')} ")
        if found is None or found["target"] != target:
            continue
        if (found["action"], found["code"]) == REFUSED:
            refused += 1
        else:
            passed += 1
    return logged, refused, passed


def verdict(logged, refused, passed, target):
    """Args:
        logged: the first count of :func:`connects`.
        refused: the second count of :func:`connects`.
        passed: the third count of :func:`connects`.
        target: TARGET.

    Returns:
        ``(status, line)``: the exit status and the one line the probe prints.
        Only the CONNECTs to ``target`` decide it: without one the egress spec
        did not run since the mark of this deploy, which is ``NOT RUN`` and
        never a pass.
    """
    if passed:
        return 1, (
            f"FAIL: the egress proxies answered {passed} CONNECT {target} "
            "without TCP_DENIED/403"
        )
    if not refused:
        return 2, (
            f"NOT RUN: no CONNECT {target} in {logged} egress lines of this deploy, "
            "the egress spec did not run"
        )
    return 0, f"OK: {refused} TCP_DENIED/403 CONNECT {target} in the egress log"


def main(argv, lines):
    """Args:
        argv: ``[SERVICE, TARGET]``.
        lines: the journal lines.

    Returns:
        The status of :func:`verdict`.
    """
    service, target = argv
    status, line = verdict(*connects(lines, service, target), target)
    print(line)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], sys.stdin))
