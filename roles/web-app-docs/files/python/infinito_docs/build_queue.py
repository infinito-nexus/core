"""The build queue, the cross-replica builder lock and the daemon loop.

``Queue`` is a mixin of :class:`infinito_docs.library.Library`. A marker is a
file named ``version`` or ``version:code``; the background lane holds the
builds nobody is waiting on - the daemon's own prefetch and every language no
visitor has asked for.
"""

from __future__ import annotations

import fcntl
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from infinito_docs.builder import DEPLOYED, QUEUE_SEPARATOR

POLL_SECONDS = 2
BACKGROUND_LANE = "background"


class Queue:
    def request(self, version, code=None, background=False):
        """Queue a build of ``version``, or of one of its translated sites.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code to build instead of the version's own site.
            background: queue behind everything a visitor is waiting on.
        """
        head, _ = self.refs()
        if not head and version != DEPLOYED:
            return
        if code is None:
            if self._current(version, head):
                return
            marker = version
        elif not self.translatable(version, code) or self._translation_current(
            version, code, head
        ):
            return
        else:
            marker = f"{version}{QUEUE_SEPARATOR}{code}"
        failed_ref = self._failed_at(marker)
        if background and failed_ref and failed_ref == self._wanted_ref(version, head):
            return
        lane = self.queue / BACKGROUND_LANE if background else self.queue
        lane.mkdir(parents=True, exist_ok=True)
        if background and (self.queue / marker).exists():
            return
        queued = lane / marker
        if queued.exists():
            return
        queued.touch()

    def is_queued(self, marker):
        """Whether ``marker`` waits in either lane.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        return (self.queue / marker).exists() or (
            self.queue / BACKGROUND_LANE / marker
        ).exists()

    def _dequeue(self, marker):
        """Drop ``marker`` from both lanes.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        (self.queue / marker).unlink(missing_ok=True)
        (self.queue / BACKGROUND_LANE / marker).unlink(missing_ok=True)

    def next_queued(self, skip=()):
        """Return the oldest marker a visitor is waiting on, else the oldest background one.

        Args:
            skip: markers to pass over, normally the ones already building.
        """
        for lane in (self.queue, self.queue / BACKGROUND_LANE):
            if not lane.is_dir():
                continue
            waiting = sorted(
                (
                    marker
                    for marker in lane.iterdir()
                    if marker.is_file() and marker.name not in skip
                ),
                key=lambda marker: marker.stat().st_mtime,
            )
            if waiting:
                return waiting[0].name
        return None

    def _buildable(self, marker, head):
        """Whether ``marker`` can be built now rather than bounced.

        A translated site needs its version current. Deciding that here and
        not in ``build_language`` keeps a free slot from claiming the marker,
        bouncing it back into the lane and claiming it again for as long as
        the version takes to build.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
            head: the mirror's current commit.
        """
        version, separator, _code = marker.partition(QUEUE_SEPARATOR)
        return not separator or self._current(version, head)

    def next_free(self):
        """Claim the oldest marker a slot can build now, or None.

        The build functions dequeue their marker only when they finish, so
        without a claim the same marker would be handed to every free slot.
        """
        head, _ = self.refs()
        with self._lock:
            skip = set(self._in_flight)
            while True:
                marker = self.next_queued(skip=frozenset(skip))
                if marker is None:
                    return None
                if self._buildable(marker, head):
                    self._in_flight.add(marker)
                    return marker
                skip.add(marker)

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

    def _build_marker(self, marker):
        """Build what ``marker`` names, then release its slot.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        try:
            version, separator, code = marker.partition(QUEUE_SEPARATOR)
            if separator:
                self.build_language(version, code)
            else:
                self.build(version)
        except Exception as exc:  # noqa: BLE001 - a slot must not die silently
            print(f"build {marker} crashed: {exc!r}", file=sys.stderr, flush=True)
            self._dequeue(marker)
        finally:
            with self._lock:
                self._in_flight.discard(marker)

    def run_builder(self, interval, parallel=1):
        """Serve the queue until the process ends.

        Args:
            interval: seconds between fetches of the mirror.
            parallel: builds to run at once. A translated site waits for its
                version to be current, so the first pair still serialises; the
                slots pay off on the languages queued behind a built version.
        """
        while not self.acquire_builder():
            time.sleep(POLL_SECONDS)
        if self.snapshot.is_dir():
            self.request(DEPLOYED)
        next_fetch = 0.0
        with ThreadPoolExecutor(max_workers=max(1, int(parallel))) as pool:
            while True:
                if time.monotonic() >= next_fetch:
                    try:
                        self.fetch()
                    except (OSError, subprocess.CalledProcessError) as exc:
                        print(
                            f"fetch of {self.repository} failed: {exc}", file=sys.stderr
                        )
                    next_fetch = time.monotonic() + interval
                marker = self.next_free()
                if marker is None:
                    time.sleep(POLL_SECONDS)
                    continue
                pool.submit(self._build_marker, marker)
