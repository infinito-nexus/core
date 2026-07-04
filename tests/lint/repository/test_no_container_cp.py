"""Forbid ``container cp`` / ``docker cp`` in tracked .yml and .sh files.

``cp`` needs the source path on the node where the docker CLI runs. In
compose mode that is always the deploy host, so controller-side paths
(``role_path`` checkouts, downloaded artifacts) happen to work. In swarm
the container lives on an arbitrary node and the same invocation dies
with a missing source or an unreachable container. Node-agnostic
replacements:

* single file:   ``container exec -i <cid> tee <dest>`` with
  ``args.stdin: "{{ lookup('file', ...) }}"``
* directory:     stream a tarball, e.g.
  ``base64 -d | container exec -i <cid> tar -xzf - -C <dest>`` with
  ``args.stdin: "{{ lookup('pipe', 'tar -C <src> -czf - . | base64') }}"``
* container to host on the SAME node (report/cert extraction) is
  legitimate; mark it.

Per-line opt-out: ``# nocheck: container-cp`` on the offending line or
the immediately preceding one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "container-cp"

_CP_CALL = re.compile(r"\b(?:docker|container)\s+cp\b")


class TestNoContainerCp(unittest.TestCase):
    def test_no_container_cp_invocations(self) -> None:
        offenders: list[str] = []
        for path_str in iter_project_files(
            extensions=(".yml", ".yaml", ".sh"),
            exclude_tests=True,
            exclude_dirs=("docs",),
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path_str).splitlines()
            for lineno, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if not _CP_CALL.search(line):
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} docker/container cp invocation(s). cp "
                "requires the source on the node running the docker CLI and "
                "breaks on swarm workers; ship content through stdin instead "
                "(container exec -i ... tee/tar with args.stdin lookup). "
                f"Legitimate same-node uses take `# nocheck: {_RULE}` on the "
                "offending or preceding line.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
