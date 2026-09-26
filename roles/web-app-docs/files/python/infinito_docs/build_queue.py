"""The build queue, the cross-replica builder lock and the daemon loop.

``Queue`` is a mixin of :class:`infinito_docs.library.Library`. A marker is a
file named ``version`` or ``version:code``; the background lane holds the
languages nobody is waiting on.
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
import time

from infinito_docs.builder import DEPLOYED, QUEUE_SEPARATOR

POLL_SECONDS = 2
BACKGROUND_LANE = "background"


class Queue:
    def request(self, version, code=None, background=False):
        """Queue a build of ``version``, or of one of its translated sites.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code to build instead of the version's own site.
            background: queue behind every language a visitor asked for.
        """
        head, _ = self.refs()
        if not head and version != DEPLOYED:
            return
        if code is None:
            if self._current(version, head):
                return
            marker = version
        elif not self.translates(version, code) or self._translation_current(
            version, code, head
        ):
            return
        else:
            marker = f"{version}{QUEUE_SEPARATOR}{code}"
        lane = self.queue / BACKGROUND_LANE if background else self.queue
        lane.mkdir(parents=True, exist_ok=True)
        if background and (self.queue / marker).exists():
            return
        (lane / marker).touch(exist_ok=True)

    def _dequeue(self, marker):
        """Drop ``marker`` from both lanes.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        (self.queue / marker).unlink(missing_ok=True)
        (self.queue / BACKGROUND_LANE / marker).unlink(missing_ok=True)

    def next_queued(self):
        """Return the oldest marker a visitor is waiting on, else the oldest background one."""
        for lane in (self.queue, self.queue / BACKGROUND_LANE):
            if not lane.is_dir():
                continue
            waiting = sorted(
                (marker for marker in lane.iterdir() if marker.is_file()),
                key=lambda marker: marker.stat().st_mtime,
            )
            if waiting:
                return waiting[0].name
        return None

    def acquire_builder(self):
        """Try to become the builder of all replicas without blocking.

        Returns:
            ``True`` while this process holds the builder lock.
        """
        if self._lock_handle is not None:
            return True
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_file.open("a+")
        try:
            fcntl.lockf(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._lock_handle = handle
        return True

    def run_builder(self, interval):
        while not self.acquire_builder():
            time.sleep(POLL_SECONDS)
        if self.snapshot.is_dir():
            self.request(DEPLOYED)
        next_fetch = 0.0
        while True:
            if time.monotonic() >= next_fetch:
                try:
                    self.fetch()
                except (OSError, subprocess.CalledProcessError) as exc:
                    print(f"fetch of {self.repository} failed: {exc}", file=sys.stderr)
                next_fetch = time.monotonic() + interval
            marker = self.next_queued()
            if marker is None:
                time.sleep(POLL_SECONDS)
                continue
            version, separator, code = marker.partition(QUEUE_SEPARATOR)
            if separator:
                self.build_language(version, code)
            else:
                self.build(version)
