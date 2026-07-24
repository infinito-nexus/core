"""Check Docker image versions in roles/*/meta/services.yml.

For each service with a semver-compatible version tag the latest available
tag on Docker Hub is fetched and compared. Outdated versions are reported as
GitHub Actions ``::warning::`` annotations or plain stdout warnings.

This is an opt-in external test because it depends on live third-party
registries. The test always passes so normal validation stays stable even when
registries are slow or temporarily unavailable. Developers are notified of
available updates via the warning output.

Semver-compatible version formats checked:
  x  /  x.x  /  x.x.x  /  x.x.x.x  (with optional leading ``v``)

Flavored Docker Official Image tags of the form
``<semver>-<flavor>`` (e.g. ``5.4.5-php8.3-apache``) are also recognised;
upgrade candidates must share the same ``-<flavor>`` suffix so the check
never silently proposes a different runtime/webserver variant.

Suppress a check by placing ``# nocheck: docker-version`` on the line
directly above the ``version:`` key (blank lines between are ignored,
but any non-comment line resets the search):

    # nocheck: docker-version
    version: "4.5"
"""

from __future__ import annotations

import unittest

from utils.annotations.message import warning
from utils.update.docker import (
    collect_entries,
    find_outdated_updates,
    is_supported_registry,
)

from . import PROJECT_ROOT

_REPO_ROOT = PROJECT_ROOT


def _emit_annotation(
    config_path: str,
    role: str,
    service: str,
    image: str,
    current: str,
    latest: str,
) -> None:
    msg = f"{role}/{service}: {image} is at {current}, latest semver tag is {latest}"
    warning(msg, title="Outdated Docker image", file=config_path)


def _emit_unchecked_annotation(
    config_path: str,
    role: str,
    service: str,
    image: str,
) -> None:
    msg = (
        f"{role}/{service}: {image} version could not be checked "
        f"(registry not supported)"
    )
    warning(msg, title="🔍 Unchecked Docker image", file=config_path)


class TestDockerImageVersions(unittest.TestCase):
    """Warn about outdated live Docker image versions in roles/*/meta/services.yml."""

    def test_image_versions_are_current(self) -> None:
        entries = collect_entries(_REPO_ROOT)
        self.assertTrue(entries, "No semver-versioned config entries found")

        updates = find_outdated_updates(_REPO_ROOT)

        unchecked = [e for e in entries if not is_supported_registry(e.image)]

        if updates:
            col_w = (35, 20, 40, 15)
            header = (
                f"{'Role':<{col_w[0]}} {'Service':<{col_w[1]}} "
                f"{'Image':<{col_w[2]}} {'Current':<{col_w[3]}} Latest"
            )
            rows = "\n".join(
                f"{u.entry.role:<{col_w[0]}} {u.entry.service:<{col_w[1]}} "
                f"{u.entry.image:<{col_w[2]}} {u.entry.version:<{col_w[3]}} {u.latest}"
                for u in updates
            )
            print(
                f"\n⚠️  Outdated Docker image versions:\n{header}\n{'-' * 120}\n{rows}\n\n💡 To suppress a warning add above the version: key:\n  # nocheck: docker-version"
            )
            for u in updates:
                _emit_annotation(
                    str(u.entry.config_path.relative_to(_REPO_ROOT)),
                    u.entry.role,
                    u.entry.service,
                    u.entry.image,
                    u.entry.version,
                    u.latest,
                )

        if unchecked:
            col_w = (35, 20, 40, 15)
            header = (
                f"{'Role':<{col_w[0]}} {'Service':<{col_w[1]}} "
                f"{'Image':<{col_w[2]}} Current"
            )
            rows = "\n".join(
                f"{e.role:<{col_w[0]}} {e.service:<{col_w[1]}} "
                f"{e.image:<{col_w[2]}} {e.version}"
                for e in unchecked
            )
            print(
                f"\n🔍 Unchecked Docker image versions (registry not supported):\n"
                f"{header}\n{'-' * 100}\n{rows}"
            )
            for e in unchecked:
                _emit_unchecked_annotation(
                    str(e.config_path.relative_to(_REPO_ROOT)),
                    e.role,
                    e.service,
                    e.image,
                )

        self.assertIsNotNone(entries)


if __name__ == "__main__":
    unittest.main()
