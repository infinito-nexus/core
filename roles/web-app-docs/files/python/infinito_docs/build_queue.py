"""The build queue, the cross-replica builder lock and the daemon loop.

``Queue`` is a mixin of :class:`infinito_docs.library.Library`. A marker is a
file named ``version`` or ``version:code``; the background lane holds the
builds nobody is waiting on - the daemon's own prefetch and every language no
visitor has asked for.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from infinito_docs.builder import DEPLOYED, LATEST, QUEUE_SEPARATOR

POLL_SECONDS = 2
BACKGROUND_LANE = "background"
KEPT_TAGS = 3


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

    def failed(self, version, code=None):
        """Whether this target's last build failed at the ref it would build now.

        Args:
            version: version directory name.
            code: language code of a translation, or None for the site itself.
        """
        head, _ = self.refs()
        marker = version if code is None else f"{version}{QUEUE_SEPARATOR}{code}"
        failed_ref = self._failed_at(marker)
        return bool(failed_ref) and failed_ref == self._wanted_ref(version, head)

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

    def _slot_free(self, slots):
        """Whether fewer than ``slots`` markers are claimed now.

        A claim taken while every slot is busy waits in the pool's own FIFO,
        so a background build claimed early would run ahead of a visitor's
        marker that became buildable after it.

        Args:
            slots: builds the pool runs at once.
        """
        with self._lock:
            return len(self._in_flight) < slots

    def _claim(self, marker):
        """Claim ``marker`` for a slot when it waits and no slot holds it yet.

        Args:
            marker: queue file name, ``version`` or ``version:code``.

        Returns:
            ``True`` when the caller owns the build of ``marker`` now.
        """
        with self._lock:
            if marker in self._in_flight or not self.is_queued(marker):
                return False
            self._in_flight.add(marker)
            return True

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

    def _tags_on_disk(self):
        """Return every release tag that has a site, translation or prepared tree."""
        names = set()
        for parent in (self.sites, self.translations):
            if parent.is_dir():
                names.update(entry.name for entry in parent.iterdir())
        if self.prepared.is_dir():
            names.update(
                entry.name.rpartition(".")[0] for entry in self.prepared.iterdir()
            )
        names -= {LATEST, DEPLOYED}
        return {name for name in names if name and not name.startswith(".")}

    def _opened_at(self, tag):
        """Return when a visitor last opened ``tag``, 0 when nobody has.

        Args:
            tag: release tag.
        """
        mark = self.opened / tag
        return mark.stat().st_mtime if mark.is_file() else 0.0

    def _prune_tags(self):
        """Drop every release tag on disk beyond the ``KEPT_TAGS`` opened last.

        The trees move out under the lock ``next_free`` claims with, so no slot
        starts cloning a prepared tree that is on its way out, and are deleted
        after it. A tag stays while one of its markers builds or its own marker
        is queued. A queued language alone keeps nothing: every finished tag
        queues its preloaded languages, so it would keep every tag a crawler
        opens, and no slot claims a language of a tag whose site is gone.
        """
        trash = self.scratch / f".pruned.{os.getpid()}.{threading.get_ident()}"
        with self._lock:
            ranked = sorted(self._tags_on_disk(), key=self._opened_at, reverse=True)
            building = {
                marker.partition(QUEUE_SEPARATOR)[0] for marker in self._in_flight
            }
            for tag in ranked[KEPT_TAGS:]:
                if tag not in building and not self.is_queued(tag):
                    self._discard_tag(tag, trash)
        shutil.rmtree(trash, ignore_errors=True)

    def _discard_tag(self, tag, trash):
        """Move the trees of ``tag`` into ``trash``, drop its states and languages.

        Args:
            tag: release tag to drop.
            trash: directory on the same volume, deleted by the caller.
        """
        trash.mkdir(parents=True, exist_ok=True)
        trees = (
            self.sites / tag,
            self.translations / tag,
            *self.prepared.glob(f"{tag}.*"),
        )
        for tree in trees:
            if tree.exists():
                tree.rename(trash / f"{tree.parent.name}.{tree.name}")
        (self.states / f"{tag}.json").unlink(missing_ok=True)
        for state in self.states.glob(f"{tag}{QUEUE_SEPARATOR}*.json"):
            state.unlink(missing_ok=True)
        for lane in (self.queue, self.queue / BACKGROUND_LANE):
            for language in lane.glob(f"{tag}{QUEUE_SEPARATOR}*"):
                language.unlink(missing_ok=True)

    def _build_marker(self, marker):
        """Build what ``marker`` names, prune the tags, then release its slot.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        try:
            version, separator, code = marker.partition(QUEUE_SEPARATOR)
            if separator:
                self.build_language(version, code)
            else:
                self.build(version)
            self._prune_tags()
        except Exception as exc:
            print(f"build {marker} crashed: {exc!r}", file=sys.stderr, flush=True)
            self._dequeue(marker)
        finally:
            with self._lock:
                self._in_flight.discard(marker)

    def run_builder(self, interval, parallel=1):
        """Serve the queue until the process ends.

        Only the lock holder writes the scratch, so what a killed holder left
        there, a build or a pruned tag halfway deleted, would stay forever
        unless the next holder clears it before its first build.

        Args:
            interval: seconds between fetches of the mirror.
            parallel: builds to run at once. A translated site waits for its
                version to be current, so the first pair still serialises; the
                slots pay off on the languages queued behind a built version.
        """
        while not self.acquire_builder():
            time.sleep(POLL_SECONDS)
        shutil.rmtree(self.scratch, ignore_errors=True)
        next_fetch = 0.0
        slots = max(1, int(parallel))
        with ThreadPoolExecutor(max_workers=slots) as pool:
            if self.snapshot.is_dir():
                self.request(DEPLOYED)
                if self._claim(DEPLOYED):
                    pool.submit(self._build_marker, DEPLOYED)
            while True:
                if time.monotonic() >= next_fetch:
                    try:
                        self.fetch()
                    except (OSError, subprocess.SubprocessError) as exc:
                        print(
                            f"fetch of {self.repository} failed: {exc}", file=sys.stderr
                        )
                    next_fetch = time.monotonic() + interval
                marker = self.next_free() if self._slot_free(slots) else None
                if marker is None:
                    time.sleep(POLL_SECONDS)
                    continue
                pool.submit(self._build_marker, marker)
