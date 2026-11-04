"""The profile this contributor's address names is public and answers.

``.mailmap`` folds a commit address into an ``@infinito.nexus`` one, whose
local part is the slug of a profile on the social instance. That profile is
the single point of truth for an author's details, so it has to exist and be
readable without logging in.

Only the address this checkout commits under is probed. Probing every declared
author would fail for people who have not created their profile yet, and a
suite that is red for someone else's omission stops being read.

This is an external test because it performs a live HTTP request. A request
that never gets an answer is reported as unverified rather than as a missing
profile: the run could not reach the instance, so it learned nothing. The
canary below separates the two.
"""

from __future__ import annotations

import unittest

import requests

from utils.annotations.message import warning
from utils.meta.identity import DOMAIN, canonical, committing_as, profile_url

CANARY = f"https://social.{DOMAIN}/"
TIMEOUT = 20
READABLE = (200, 301, 302)


def _probe(url: str) -> tuple[int | None, str]:
    try:
        response = requests.get(url, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return None, str(exc)
    return response.status_code, response.reason or ""


class TestAuthorProfile(unittest.TestCase):
    def setUp(self) -> None:
        name, email = committing_as()
        if not email:
            raise unittest.SkipTest("git config user.email is unset here")
        _name, self.email = canonical(name, email)
        self.url = profile_url(self.email)
        if not self.url:
            raise unittest.SkipTest(
                f"{email!r} is not mapped to an @{DOMAIN} address yet; "
                "tests/integration/meta/test_commit_identity.py reports that"
            )

    def test_the_profile_is_publicly_readable(self) -> None:
        status, detail = _probe(CANARY)
        if status is None:
            raise unittest.SkipTest(f"social.{DOMAIN} is unreachable here: {detail}")

        status, detail = _probe(self.url)
        if status is None:
            warning(f"{self.url} was not answered ({detail}); profile unverified")
            raise unittest.SkipTest(
                "the instance answered the canary but not the probe"
            )

        self.assertIn(
            status,
            READABLE,
            f"{self.url} answered {status} {detail}. Your author details are read "
            f"from that profile, so create it and make it public. It is derived "
            f"from {self.email!r}, the address .mailmap folds your commits into.",
        )


if __name__ == "__main__":
    unittest.main()
