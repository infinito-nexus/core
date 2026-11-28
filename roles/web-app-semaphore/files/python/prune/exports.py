from __future__ import annotations

import datetime as dt
import html
import os
import re
import sys
import urllib.parse
from typing import TYPE_CHECKING

from export_task import (
    FAILURES,
    LOGIN_ENV,
    S3_ENV,
    ExportRefusedError,
    ExportTask,
    bao_client,
    presign,
    reason,
    task_opener,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from export_task import Opener

    from utils.openbao_client import OpenBaoClient

ROLE = "prune-exports"
REQUIRED_ENV = (*LOGIN_ENV, *S3_ENV)
MAX_AGE = dt.timedelta(hours=1)
REQUEST_SECONDS = 60
CONTENTS = re.compile(r"<Contents>(.*?)</Contents>", re.DOTALL)
KEY = re.compile(r"<Key>(.*?)</Key>", re.DOTALL)
MODIFIED = re.compile(r"<LastModified>(.*?)</LastModified>")
TRUNCATED = re.compile(r"<IsTruncated>\s*true\s*</IsTruncated>")
NEXT = re.compile(r"<NextContinuationToken>(.*?)</NextContinuationToken>", re.DOTALL)


def listing(text: str) -> tuple[list[tuple[str, dt.datetime]], str | None]:
    """
    Args:
        text: one ``ListObjectsV2`` answer.

    Returns:
        Key and ``LastModified`` of every object it lists, and the
        continuation token while the listing is truncated, else None.
    """
    objects = []
    for block in CONTENTS.findall(text):
        key, modified = KEY.search(block), MODIFIED.search(block)
        if key is None or modified is None:
            raise ExportRefusedError("the listing holds an object without key or time")
        stamp = dt.datetime.fromisoformat(modified.group(1))
        objects.append((html.unescape(key.group(1)), stamp))
    if not TRUNCATED.search(text):
        return objects, None
    token = NEXT.search(text)
    if token is None or not token.group(1):
        raise ExportRefusedError("a truncated listing names no continuation token")
    return objects, html.unescape(token.group(1))


class Pruner(ExportTask):
    def __init__(
        self, environ: Mapping[str, str], opener: Opener, bao: OpenBaoClient
    ) -> None:
        """
        Args:
            environ: the task environment; see ``REQUIRED_ENV``.
            opener: see ``ExportTask``.
            bao: see ``ExportTask``.
        """
        super().__init__(environ, REQUIRED_ENV, opener, bao)

    def _signed(
        self, method: str, url: str, now: dt.datetime, query: Mapping[str, str]
    ) -> str:
        return presign(
            method,
            url,
            self.s3_credentials(),
            self.env["EXPORT_S3_REGION"],
            now,
            REQUEST_SECONDS,
            query,
        )

    def objects(self, now: dt.datetime) -> list[tuple[str, dt.datetime]]:
        """
        Args:
            now: the signing time.

        Returns:
            Every object of the bucket, across every page of the listing.
        """
        found: list[tuple[str, dt.datetime]] = []
        token = None
        while True:
            query = {"list-type": "2"}
            if token is not None:
                query["continuation-token"] = token
            raw = self._call(
                "GET", self._signed("GET", self.bucket_url(), now, query), None, {}
            )
            page, token = listing(raw.decode())
            found.extend(page)
            if token is None:
                return found

    def delete(self, key: str, now: dt.datetime) -> None:
        url = f"{self.bucket_url()}/{urllib.parse.quote(key, safe='/-_.~')}"
        self._call("DELETE", self._signed("DELETE", url, now, {}), None, {})


def run(
    environ: Mapping[str, str], opener: Opener, now: dt.datetime
) -> tuple[list[str], list[str]]:
    """
    Args:
        environ: see ``Pruner``.
        opener: see ``Pruner``.
        now: the current time.

    Returns:
        The key of every deleted object and one line per object whose delete
        failed; one failure never stops the other deletes.
    """
    pruner = Pruner(environ, opener, bao_client(environ))
    pruner.login(ROLE)
    deleted, failures = [], []
    for key, modified in pruner.objects(now):
        if now - modified <= MAX_AGE:
            continue
        try:
            pruner.delete(key, now)
        except FAILURES as exc:
            failures.append(f"{key}: {reason(exc)}")
        else:
            deleted.append(key)
    return deleted, failures


def main(argv: list[str]) -> int:
    if argv:
        print(f"prune exports: takes no argument, got {argv[0]!r}", file=sys.stderr)
        return 2
    try:
        deleted, failures = run(
            os.environ, task_opener(os.environ), dt.datetime.now(dt.UTC)
        )
    except FAILURES as exc:
        print(f"prune exports refused: {reason(exc)}", file=sys.stderr)
        return 1
    for key in deleted:
        print(f"prune exports: deleted {key}")
    for line in failures:
        print(f"prune exports failed: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
