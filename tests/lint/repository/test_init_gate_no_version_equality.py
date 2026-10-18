"""Forbid image-version comparisons in the swarm init-gate scripts.

An init gate (``roles/*/files/**/\\*init-gate*.sh``) is the image ENTRYPOINT
of a replicated web app. Every task whose ``TASK_SLOT`` is not 1 waits in it
until the shared volume holds an installation it may serve, then hands over
to the upstream entrypoint.

Gating that wait on "the installed version equals the version MY image
ships" deadlocks a rolling update. Swarm replaces one task at a time
(``service_update_parallelism: 1``, order ``stop-first``) and picks an
arbitrary slot first, while the version on the shared volume only moves
when some task reaches the upstream entrypoint and runs the upgrade. A
non-1 slot that is updated first therefore waits for a state that nobody
will produce: php-fpm never starts, the healthcheck never passes, swarm
SIGKILLs the task after ``start_period``, and its replacement repeats it.
Measured on run 38818071194 job 116715662950, where the nextcloud tag moved
34.0.4 -> 34.0.5 between two deploys of the same job and slot 2 spun for 26
minutes until the converge wait gave up.

The version decision belongs to the upstream entrypoint, which is the only
actor that can act on it: it takes a blocking ``flock`` on the very
``*-init-sync.lock`` the gate probes, re-reads the installed version after
acquiring it (so a second task skips an upgrade another one just finished),
performs the upgrade, and hard-exits before ``exec`` on a downgrade.
Verified against ``nextcloud:34-fpm-alpine`` and ``friendica:2026.05``.

So a gate may wait for a free init lock and for the installation to be
complete and consistent, and it may never wait for a version.

Per-line opt-out: ``# nocheck: init-gate-image-version``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "init-gate-image-version"

_IMAGE_STATE = re.compile(r"/usr/src/|\bimage_version\b")

_INIT_LOCK = re.compile(r"-init-sync\.lock\b")


def _gate_files() -> list[str]:
    return sorted(
        path
        for path in iter_project_files(extensions=(".sh",), exclude_tests=True)
        if "init-gate" in Path(path).name
    )


class TestInitGateNoVersionEquality(unittest.TestCase):
    def test_gates_are_discovered(self) -> None:
        self.assertTrue(
            _gate_files(),
            "No *init-gate*.sh found under the project. Either the gates were "
            "renamed, in which case this lint stopped protecting them and its "
            "discovery needs updating, or they are gone and so is this test.",
        )

    def test_gate_never_waits_for_the_image_version(self) -> None:
        offenders: list[str] = []
        for path_str in _gate_files():
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = read_text(path_str).splitlines()
            for lineno, line in enumerate(lines, 1):
                if line.lstrip().startswith("#"):
                    continue
                if not _IMAGE_STATE.search(line):
                    continue
                if is_suppressed_at(lines, lineno, _RULE):
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

        if offenders:
            self.fail(
                f"{len(offenders)} init-gate line(s) read the image's own "
                "version (/usr/src/<app> or an image_version variable). A "
                "non-1 slot that waits for the installation to reach ITS "
                "image version deadlocks every rolling update that carries a "
                "new version, because only a task past the gate ever upgrades "
                "the shared volume. Wait for a free init lock and a consistent "
                "installation instead, and leave the version decision to the "
                "upstream entrypoint that holds the same lock. Opt out per "
                f"line with `# nocheck: {_RULE}`.\n" + "\n".join(offenders)
            )

    def test_gate_hands_over_through_the_init_lock(self) -> None:
        offenders: list[str] = []
        for path_str in _gate_files():
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            body = read_text(path_str)
            if "flock" in body and _INIT_LOCK.search(body):
                continue
            offenders.append(rel)

        if offenders:
            self.fail(
                f"{len(offenders)} init-gate(s) no longer probe the upstream "
                "*-init-sync.lock with flock. That probe is what makes the "
                "removal of the version comparison safe: it keeps a replica "
                "parked while another task holds the lock across the file "
                "copy and the database upgrade. Without it a gate can release "
                "a replica onto a half-replaced tree.\n" + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
