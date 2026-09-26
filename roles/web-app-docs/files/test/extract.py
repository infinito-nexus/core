"""Read a role's production instructions off the documentation site.

Standard library only: this is staged onto the stack host, which carries no
repository and no virtualenv.

The site builds a version on first request and answers 202 until it is ready,
so the fetch polls. The block is taken from the first ``<pre>`` after the
Production heading, which is what a reader copies.

Usage:
  extract.py <base-url> <role> [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import html
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

VERSION = "latest"
HEADING = "production"
BUILDING = 202


class Block(HTMLParser):
    """Collect the text of the first ``<pre>`` after the Production heading."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.reached = False
        self.inside = False
        self.done = False
        self.parts: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if not self.reached and dict(attrs).get("id") == HEADING:
            self.reached = True
        elif self.reached and tag == "pre":
            self.inside = True
            self._depth = 0
        elif self.inside:
            self._depth += 1

    def handle_endtag(self, tag):
        if self.inside and tag == "pre" and self._depth == 0:
            self.inside = False
            self.done = True
        elif self.inside:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self.inside:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return html.unescape("".join(self.parts))


def page_url(base: str, role: str) -> str:
    """Return the address of ``role``'s documentation page.

    Args:
        base: scheme, host and port of the documentation service.
        role: the role whose page to read.
    """
    return f"{base.rstrip('/')}/{VERSION}/roles/{role}/README.html"


def fetch(url: str, timeout: float, poll: float = 15.0) -> str:
    """Return the page body, waiting while the site builds the version.

    Args:
        url: the page to read.
        timeout: seconds to keep waiting for the build.
        poll: seconds between attempts.

    Raises:
        TimeoutError: the site kept answering 202 until the deadline.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — http to the local stack
                if response.status != BUILDING:
                    return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code != BUILDING:
                raise
        except urllib.error.URLError as exc:
            print(
                f"  {url} not answering yet ({exc.reason})", file=sys.stderr, flush=True
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"{url}: still unavailable after {timeout:.0f}s")
        print(
            f"  waiting for the page; retrying in {poll:.0f}s",
            file=sys.stderr,
            flush=True,
        )
        time.sleep(poll)


def block(base: str, role: str, timeout: float) -> str:
    """Return the production commands ``role``'s published page shows.

    Args:
        base: documentation service URL.
        role: the role whose instructions to read.
        timeout: seconds to wait for an on-demand build.

    Raises:
        ValueError: the page carries no production block.
    """
    parser = Block()
    parser.feed(fetch(page_url(base, role), timeout))
    if not parser.text.strip():
        raise ValueError(f"{role}: the published page shows no {HEADING} block")
    return parser.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("role")
    parser.add_argument("--timeout", type=float, default=2400)
    args = parser.parse_args(argv)

    print(block(args.base, args.role, args.timeout), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
