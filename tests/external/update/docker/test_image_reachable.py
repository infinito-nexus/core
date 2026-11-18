"""Verify every roles/*/meta/services.yml ``image:version`` tag exists.

Unlike its outdated-version sibling this test is a real gate: a pin that
the registry positively reports as absent (HTTP 404) FAILS the suite, so a
typo'd or removed tag can never ship. Indeterminate results (network error,
auth wall, rate limit — ``manifest_exists`` returns ``None``) only warn, so
a slow or private registry never turns into a false failure.

Opt-in external test: it hits live third-party registries and is only run
under the external suite.
"""

from __future__ import annotations

import concurrent.futures
import unittest

from utils.annotations.message import warning
from utils.docker.image.discovery import iter_role_images
from utils.docker.image.pin import pull_reference
from utils.docker.registry import manifest_exists
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import resolve_max_fetch_workers

from . import PROJECT_ROOT


def _pull_image(ref) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


def _display(ref) -> str:
    return pull_reference(_pull_image(ref), ref.version)


class TestDockerImageReachable(unittest.TestCase):
    """Fail on any pinned Docker image:version tag the registry reports absent."""

    def test_pinned_images_are_reachable(self) -> None:
        entries = list(iter_role_images(PROJECT_ROOT))
        self.assertTrue(entries, "No role images discovered")

        pairs = {(_pull_image(ref), ref.version) for ref in entries}

        def _check(pair: tuple[str, str]) -> tuple[tuple[str, str], bool | None]:
            image, version = pair
            return pair, manifest_exists(image, version)

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=resolve_max_fetch_workers()
        ) as pool:
            results = dict(pool.map(_check, pairs))

        missing = []
        indeterminate = []
        for ref in entries:
            status = results.get((_pull_image(ref), ref.version))
            if status is False:
                missing.append(ref)
            elif status is None:
                indeterminate.append(ref)

        for ref in indeterminate:
            warning(
                f"{ref.role}/{ref.service}: {_display(ref)} "
                f"could not be verified (network / auth / rate-limit)",
                title="🔍 Unverified Docker image",
                file=f"roles/{ref.role}/{ROLE_FILE_META_SERVICES}",
            )

        if missing:
            lines = "\n".join(
                f"  {ref.role}/{ref.service}: {_display(ref)}"
                for ref in sorted(missing, key=lambda r: (r.role, r.service))
            )
            self.fail(
                "These pinned Docker images do not exist in their registry "
                f"(HTTP 404):\n{lines}"
            )


if __name__ == "__main__":
    unittest.main()
