"""Hold every role's ``architectures`` to what its images actually publish.

``architectures`` in ``meta/services.yml`` is what narrows a role's rows in
the deploy matrix, and a role that declares nothing takes whatever the
rotation assigns it. Nothing has ever checked either half against a registry:
``test_image_reachable.py`` proves a tag exists, ``test_arm64_images.py``
proves four named roles publish arm64, and the closure lint only proves the
declarations do not intersect to nothing. An amd64-only bump therefore turns
into a scheduling failure on an arm64 row rather than a red test here.

A role can only be placed where *every* image it pins can run, so its
capability is the intersection over its services, not a property of any one
of them. Checking per image would be wrong in both directions: it would
demand arm64 from a sidecar on an amd64-only role, and it would call a
narrowing stale because ``nginx`` publishes arm64 while the application
image does not.

Two rules, one per polarity of the declaration:

* a role that declares no ``architectures`` is offered every architecture in
  ``utils.github.variant.pools.ARCHITECTURES``, so its capability has to
  cover all of them;
* a role that narrows must narrow to exactly its capability. An architecture
  it claims that no longer runs cannot be scheduled, and one its images have
  all since gained is a pin that excludes an architecture the role is
  compatible with, keeping it tested narrower than it could be while nothing
  says so. The second half is what retires a declaration by itself once
  upstream starts publishing the manifest its ``nocheck`` was written for.

A ``version_variants`` ref is skipped: it is a tag the mirror must carry, not
a version a role deploys.

Indeterminate registry answers only warn, matching ``test_image_reachable.py``
and ``test_arm64_images.py``: a rate limit must never read as a missing
architecture. A role is judged on the images that did answer, and skipped
entirely when none did, so a throttled sweep understates rather than invents.

Opt-in external test: it hits live third-party registries and runs only under
the external suite. The sweep is ~160 images and Docker Hub counts its
anonymous allowance per IP, shared with everything else on that address, so
the probe goes through :func:`manifest_platforms_probed`, which reads the
mirror first and caches on disk. The run reports how many answers came from
each source, because a mirror that silently stops answering turns this test
into the thing that exhausts the allowance.
"""

from __future__ import annotations

import collections
import concurrent.futures
import unittest
from typing import ClassVar

from utils.annotations.message import warning
from utils.docker.image.architectures import role_capability
from utils.docker.image.discovery import iter_role_images
from utils.docker.registry import manifest_platforms_probed
from utils.github.variant.pools import ARCHITECTURES
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_architectures
from utils.update.base import resolve_max_fetch_workers

from . import PROJECT_ROOT


def _pull_image(ref) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


class ImageArchitectures(unittest.TestCase):
    """One registry sweep, shared by both rules."""

    probed: ClassVar[dict] = {}
    sources: ClassVar[collections.Counter] = collections.Counter()
    by_role: ClassVar[dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        refs = [ref for ref in iter_role_images(PROJECT_ROOT) if not ref.derived]
        cls.by_role = collections.defaultdict(list)
        for ref in refs:
            cls.by_role[ref.role].append(ref)

        def _probe(pair):
            return pair, manifest_platforms_probed(*pair)

        pairs = {(_pull_image(ref), ref.version) for ref in refs}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=resolve_max_fetch_workers()
        ) as pool:
            for pair, (platforms, source) in pool.map(_probe, pairs):
                cls.probed[pair] = platforms
                cls.sources[source] += 1

    def _capability(self, role: str):
        """Probe every image of *role* and reduce it to where the role runs.

        Args:
            role: role directory name.

        Returns:
            What :func:`role_capability` returns for the role's images.
        """
        offered = {}
        for ref in self.by_role[role]:
            platforms = self.probed.get((_pull_image(ref), ref.version))
            if platforms is None:
                warning(
                    f"{ref.role}/{ref.service}: "
                    f"{_pull_image(ref)}:{ref.version} published architectures "
                    "could not be read (network / auth / rate limit)",
                    title="🔍 Unverified image architectures",
                    file=f"roles/{ref.role}/{ROLE_FILE_META_SERVICES}",
                )
            offered[f"{ref.service} ({_pull_image(ref)}:{ref.version})"] = platforms
        return role_capability(offered)

    @staticmethod
    def _named(blame: dict, architecture: str) -> str:
        return ", ".join(sorted(blame.get(architecture, []))) or "no image"

    def test_the_sweep_reaches_the_registries(self) -> None:
        if self.sources["upstream"]:
            warning(
                f"{self.sources['upstream']} image(s) were read from their "
                "upstream registry because the mirror does not carry them; "
                "that is the half of the sweep which spends a rate limit",
                title="🪞 Mirror miss",
            )
        self.assertGreater(
            len(self.probed) - self.sources["none"],
            0,
            "no registry answered for any pinned image, so both rules below "
            f"would pass vacuously (sources: {dict(self.sources)})",
        )

    def test_an_undeclared_role_runs_on_every_architecture(self) -> None:
        offenders = []
        for role in sorted(self.by_role):
            if get_role_architectures(role):
                continue
            capability, blame, _unread = self._capability(role)
            if capability is None:
                continue
            offenders.extend(
                f"{role}: declares no `architectures`, so the matrix may "
                f"place it on {architecture}, which "
                f"{self._named(blame, architecture)} cannot run"
                for architecture in sorted(set(ARCHITECTURES) - capability)
            )
        self.assertEqual(
            [],
            offenders,
            "role(s) the matrix may place where their images cannot run. "
            "Declare `architectures` on the role, or pin images that publish "
            "them:\n" + "\n".join(f"  - {o}" for o in offenders),
        )

    def test_a_declared_role_narrows_to_what_its_images_publish(self) -> None:
        offenders = []
        for role in sorted(self.by_role):
            declared = set(get_role_architectures(role))
            if not declared:
                continue
            capability, blame, unread = self._capability(role)
            if capability is None:
                continue
            offenders.extend(
                f"{role}: `architectures` claims {architecture}, which "
                f"{self._named(blame, architecture)} cannot run"
                for architecture in sorted(declared - capability)
            )
            stale = sorted(capability - declared)
            if stale and unread:
                warning(
                    f"{role}: every image that answered runs on {stale}, but "
                    f"{len(unread)} did not answer, and an unread image may be "
                    "the one the narrowing exists for",
                    title="🔍 Narrowing not judged",
                    file=f"roles/{role}/{ROLE_FILE_META_SERVICES}",
                )
            elif stale:
                offenders.append(
                    f"{role}: every image it pins now runs on {stale}, which "
                    f"`architectures` excludes; the declaration keeps the role "
                    f"off architectures it is compatible with, so drop it "
                    f"together with the nocheck that justifies it"
                )
        self.assertEqual(
            [],
            offenders,
            "role(s) whose `architectures` disagrees with their images:\n"
            + "\n".join(f"  - {o}" for o in offenders),
        )


if __name__ == "__main__":
    unittest.main()
