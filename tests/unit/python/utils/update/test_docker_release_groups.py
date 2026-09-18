"""Several images of one role at one version move together or not at all.

Upstream does not push a release group atomically. Measured on Docker Hub:
``jitsi/prosody``, ``jitsi/jicofo`` and ``jitsi/jvb`` all publish
``stable-9457`` while ``jitsi/web`` does not, so a bump run landing in that
window would raise three components and leave the fourth behind.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.docker import (
    DockerImageVersionEntry,
    DockerImageVersionUpdate,
    _held_to_release_groups,
)

JITSI = ("web", "prosody", "jicofo", "jvb")


def _entry(role: str, service: str, image: str, version: str):
    return DockerImageVersionEntry(
        role=role,
        service=service,
        image=image,
        version=version,
        config_path=Path(ROLE_FILE_META_SERVICES),
    )


def _jitsi_updates(version: str, latest: str):
    return [
        DockerImageVersionUpdate(
            entry=_entry("web-app-jitsi", name, f"jitsi/{name}", version),
            latest=latest,
        )
        for name in JITSI
    ]


class TestReleaseGroupsMoveTogether(unittest.TestCase):
    def test_a_partial_publish_holds_the_whole_group_back(self):
        tags = {
            "jitsi/web": ["stable-9400", "stable-9646"],
            "jitsi/prosody": ["stable-9400", "stable-9646", "stable-9700"],
            "jitsi/jicofo": ["stable-9400", "stable-9646", "stable-9700"],
            "jitsi/jvb": ["stable-9400", "stable-9646", "stable-9700"],
        }
        updates = _jitsi_updates("stable-9400", "stable-9700")

        held = _held_to_release_groups(updates, tags)

        self.assertEqual({update.latest for update in held}, {"stable-9646"})
        self.assertEqual(len(held), 4)

    def test_a_group_all_publish_moves_to_the_head(self):
        tags = {f"jitsi/{name}": ["stable-9400", "stable-9700"] for name in JITSI}
        updates = _jitsi_updates("stable-9400", "stable-9700")

        held = _held_to_release_groups(updates, tags)

        self.assertEqual({update.latest for update in held}, {"stable-9700"})

    def test_a_group_with_nothing_in_common_is_dropped(self):
        tags = {
            "jitsi/web": ["stable-9400", "stable-9701"],
            "jitsi/prosody": ["stable-9400", "stable-9702"],
            "jitsi/jicofo": ["stable-9400", "stable-9703"],
            "jitsi/jvb": ["stable-9400", "stable-9704"],
        }
        updates = _jitsi_updates("stable-9400", "stable-9704")

        self.assertEqual(_held_to_release_groups(updates, tags), [])

    def test_a_lone_entry_is_untouched(self):
        update = DockerImageVersionUpdate(
            entry=_entry("web-app-fider", "fider", "getfider/fider", "v0.35.0"),
            latest="v0.36.0",
        )

        held = _held_to_release_groups([update], {"getfider/fider": ["v0.36.0"]})

        self.assertEqual(held, [update])

    def test_two_roles_on_one_version_are_not_one_group(self):
        tags = {
            "jitsi/web": ["stable-9400", "stable-9700"],
            "other/thing": ["stable-9400"],
        }
        updates = [
            DockerImageVersionUpdate(
                entry=_entry("web-app-jitsi", "web", "jitsi/web", "stable-9400"),
                latest="stable-9700",
            ),
            DockerImageVersionUpdate(
                entry=_entry("web-app-other", "thing", "other/thing", "stable-9400"),
                latest="stable-9400",
            ),
        ]

        held = _held_to_release_groups(updates, tags)

        self.assertEqual(
            [update.latest for update in held], ["stable-9700", "stable-9400"]
        )


if __name__ == "__main__":
    unittest.main()
