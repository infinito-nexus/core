"""The identity this checkout commits under resolves to an Infinito.Nexus one.

A contributor may commit under any address, but ``.mailmap`` has to fold it
into their ``@infinito.nexus`` one, because that address is what names their
public profile and the profile is where an author's details live.

Only the address configured here is checked. A historic address nobody commits
under any more is not this contributor's problem to fix, and failing on it
would make the suite red for everyone.
"""

from __future__ import annotations

import unittest

from utils.meta.identity import DOMAIN, MAILMAP, canonical, committing_as, profile_url


class TestCommitIdentity(unittest.TestCase):
    def setUp(self) -> None:
        self.name, self.email = committing_as()
        if not self.email:
            raise unittest.SkipTest("git config user.email is unset here")

    def test_the_configured_address_maps_to_an_infinito_nexus_one(self) -> None:
        name, email = canonical(self.name, self.email)

        self.assertTrue(
            email.endswith(f"@{DOMAIN}"),
            f"commits from this checkout carry {self.email!r}, which {MAILMAP} "
            f"does not fold into an @{DOMAIN} address. Add a line to {MAILMAP}:\n\n"
            f"    {name} <yourname@{DOMAIN}> <{self.email}>\n\n"
            f"That address names your profile at "
            f"{profile_url(f'yourname@{DOMAIN}')}, which is where your author "
            f"details are read from.",
        )

    def test_the_mapped_address_names_a_profile(self) -> None:
        _name, email = canonical(self.name, self.email)
        if not email.endswith(f"@{DOMAIN}"):
            raise unittest.SkipTest("address is not mapped yet")

        self.assertTrue(
            profile_url(email),
            f"{email!r} yields no profile slug; the local part must not be empty",
        )


if __name__ == "__main__":
    unittest.main()
