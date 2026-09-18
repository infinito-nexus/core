"""Enforce the pin ranking: a semver tag, else a digest, and nothing else.

Two states fail here, and neither is a matter of taste:

* A pin that is neither a semver tag nor a digest names something the registry
  can move under us. Nothing in this repository can tell whether it still points
  where it did when it was written.
* A digest where the registry does publish semver tags. The digest is the
  fallback for upstreams that offer no orderable tag; taking it anyway opts the
  entry out of the freshness pipeline for no gain.

Both are declarable when the choice is deliberate, with ``# nocheck:
docker-version`` respectively ``# nocheck: docker-digest`` on the ``version:``
line or the one above it. The mirror case is the reason the second one exists:
a tag whose bytes moved is worth pinning past, even though the tag exists.

Opt-in external test: it reads live third-party registries and runs only under
the external suite. The offline sibling at
[test_semver_pinning.py](../../../lint/ansible/services/test_semver_pinning.py)
warns about the same pins without failing.
"""

from __future__ import annotations

import concurrent.futures
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.docker.image.discovery import iter_role_images
from utils.docker.image.pin import DIGEST, REF, RULE_BY_CLASS, pin_class
from utils.docker.registry import fetch_registry_tags
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import is_semver, resolve_max_fetch_workers
from utils.update.docker import is_supported_registry

from . import PROJECT_ROOT


def _pull_image(ref) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


def _declared(ref, rule: str) -> bool:
    """Whether the ``version:`` line carrying this pin opts out of *rule*."""
    path = PROJECT_ROOT / "roles" / ref.role / ROLE_FILE_META_SERVICES
    lines = read_text(path).splitlines()
    needle = ref.version.strip()
    numbers = [
        number
        for number, line in enumerate(lines, start=1)
        if line.split("#", 1)[0].strip().startswith("version:")
        and needle in line.split("#", 1)[0]
    ]
    return bool(numbers) and all(
        is_suppressed_at(lines, number, rule) for number in numbers
    )


def _offers_semver(image: str) -> bool:
    return any(is_semver(tag) for tag in fetch_registry_tags(image))


class TestImagePinPolicy(unittest.TestCase):
    """A pin is a semver tag, a justified digest, or a declared exception."""

    def test_unpinned_and_unversioned_entries_are_rejected(self) -> None:
        refs = list(iter_role_images(PROJECT_ROOT))
        self.assertTrue(refs, "No role images discovered")

        offenders = [
            f"  roles/{ref.role}/{ROLE_FILE_META_SERVICES}: {ref.service} pins "
            f"{ref.version!r}, which is neither a version nor a digest"
            for ref in refs
            if pin_class(ref.version) == REF and not _declared(ref, RULE_BY_CLASS[REF])
        ]

        if offenders:
            listing = "\n".join(sorted(offenders))
            self.fail(
                "These entries pin a name the registry can move under them. "
                "Pin a semver tag, or a digest when upstream publishes none, or "
                f"declare the choice with `# nocheck: {RULE_BY_CLASS[REF]}`:\n"
                f"{listing}"
            )

    def test_a_digest_is_rejected_where_semver_is_published(self) -> None:
        refs = [
            ref
            for ref in iter_role_images(PROJECT_ROOT)
            if pin_class(ref.version) == DIGEST
            and is_supported_registry(ref.name)
            and not _declared(ref, RULE_BY_CLASS[DIGEST])
        ]
        if not refs:
            self.skipTest("no undeclared digest pins to check")

        images = {_pull_image(ref) for ref in refs}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=resolve_max_fetch_workers()
        ) as pool:
            offers = dict(zip(images, pool.map(_offers_semver, images), strict=True))

        offenders = [
            f"  roles/{ref.role}/{ROLE_FILE_META_SERVICES}: {ref.service} pins a "
            f"digest while {_pull_image(ref)} publishes semver tags"
            for ref in refs
            if offers.get(_pull_image(ref))
        ]

        if offenders:
            listing = "\n".join(sorted(offenders))
            self.fail(
                "A digest is the fallback for an upstream that publishes no "
                "orderable tag. These have one, so the digest only hides them "
                f"from the update job. Use the tag, or declare why not with "
                f"`# nocheck: {RULE_BY_CLASS[DIGEST]}`:\n{listing}"
            )


if __name__ == "__main__":
    unittest.main()
