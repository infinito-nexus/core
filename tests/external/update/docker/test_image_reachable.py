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
from utils.docker.image.discovery import iter_role_images, load_yaml
from utils.docker.registry import manifest_exists
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import resolve_max_fetch_workers

from . import PROJECT_ROOT


def _pull_image(ref) -> str:
    return ref.name if ref.registry == "docker.io" else f"{ref.registry}/{ref.name}"


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
                f"{ref.role}/{ref.service}: {_pull_image(ref)}:{ref.version} "
                f"could not be verified (network / auth / rate-limit)",
                title="🔍 Unverified Docker image",
                file=f"roles/{ref.role}/{ROLE_FILE_META_SERVICES}",
            )

        if missing:
            lines = "\n".join(
                f"  {ref.role}/{ref.service}: {_pull_image(ref)}:{ref.version}"
                for ref in sorted(missing, key=lambda r: (r.role, r.service))
            )
            self.fail(
                "These pinned Docker image:version tags do not exist in their "
                f"registry (HTTP 404):\n{lines}"
            )

    def test_incomplete_image_version_pairs_warn(self) -> None:
        """Warn (never fail) on a service that sets only one of image/version.

        A reachable pull tag needs both; a lone ``image:`` or ``version:`` is
        either a typo or a base/shared-image indirection worth reviewing.
        """
        for services_file in sorted(
            (PROJECT_ROOT / "roles").glob(f"**/{ROLE_FILE_META_SERVICES}")
        ):
            role = services_file.parent.parent.name
            services = load_yaml(services_file)
            if not isinstance(services, dict):
                continue
            for service, cfg in services.items():
                if not isinstance(cfg, dict):
                    continue
                has_image = bool(cfg.get("image"))
                has_version = bool(cfg.get("version"))
                if has_image == has_version:
                    continue
                present, missing = (
                    ("image", "version") if has_image else ("version", "image")
                )
                warning(
                    f"{role}/{service}: has `{present}:` but no `{missing}:` — "
                    "a reachable pull tag needs both",
                    title="🔧 Incomplete image/version pair",
                    file=f"roles/{role}/{ROLE_FILE_META_SERVICES}",
                )


if __name__ == "__main__":
    unittest.main()
