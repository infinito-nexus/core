from __future__ import annotations

import os
import re
import unittest
import unittest.mock as mock
from typing import ClassVar

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import docker, repository

ROLE = "web-app-nextcloud"
SERVICES_FILE = PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_SERVICES
JANUS = "https://github.com/meetecho/janus-gateway.git"
RECORDING = "https://github.com/nextcloud/nextcloud-talk-recording.git"


def _pinned(service: str, key: str) -> str:
    return str(load_yaml_any(str(SERVICES_FILE))[service][key])


class TestTalkPinsAreWatched(unittest.TestCase):
    IMAGES: ClassVar[dict[str, str]] = {
        "talk_signaling": "strukturag/nextcloud-spreed-signaling",
        "talk_nats": "nats",
        "talk": "alpine",
        "talk_recording": "python",
    }
    REFS: ClassVar[dict[str, str]] = {"talk": JANUS, "talk_recording": RECORDING}

    def test_the_docker_updater_watches_every_talk_image(self):
        entries = {
            (entry.service, entry.image): entry.version
            for entry in docker.collect_entries(PROJECT_ROOT)
            if entry.role == ROLE
        }
        for service, image in self.IMAGES.items():
            with self.subTest(service=service):
                self.assertEqual(
                    entries.get((service, image)), _pinned(service, "version")
                )

    def test_the_repository_updater_watches_both_built_sources(self):
        entries = {
            entry.entity_path: (entry.repository, entry.ref)
            for entry in repository.collect_entries(PROJECT_ROOT)
            if entry.role == ROLE
        }
        for service, url in self.REFS.items():
            with self.subTest(service=service):
                self.assertEqual(
                    entries.get((service,)), (url, _pinned(service, "ref"))
                )

    def test_no_talk_pin_opts_out_of_the_updaters(self):
        lines = read_text(str(SERVICES_FILE)).splitlines()
        owner = None
        for number, line in enumerate(lines):
            if match := re.match(r"^([a-z_]+):", line):
                owner = match.group(1)
            if owner in self.IMAGES and re.match(r"^\s+(version|ref):", line):
                with self.subTest(service=owner, line=number + 1):
                    self.assertNotIn("nocheck", lines[number - 1])
                    self.assertNotIn("nocheck", line)

    def test_a_newer_upstream_release_is_reported_for_every_pin(self):
        newer = {
            "strukturag/nextcloud-spreed-signaling": ["2.1.1", "9.0.0", "9.0.0-proxy"],
            "nats": ["2.12.6-alpine", "9.0.0-alpine", "9.1.0"],
            "alpine": ["3.23.3", "9.0.0"],
            "python": ["3.14.3-alpine3.23", "3.14.9-alpine3.23", "3.15.0-slim"],
        }
        tags = {JANUS: ["v1.4.0", "v9.0.0"], RECORDING: ["v0.2.1", "v9.0.0"]}
        with (
            mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "2"}),
            mock.patch.object(
                docker, "fetch_dockerhub_tags", lambda image: newer.get(image, [])
            ),
            mock.patch.object(docker, "fetch_ghcr_tags", lambda image: []),
            mock.patch.object(docker, "fetch_mcr_tags", lambda image: []),
            mock.patch.object(
                docker, "fetch_registry_tags", lambda image, last=None: []
            ),
            mock.patch.object(
                repository, "git_ls_remote_tags", lambda url: tags.get(url, [])
            ),
        ):
            images = {
                (update.entry.service, update.latest)
                for update in docker.find_outdated_updates(PROJECT_ROOT)
                if update.entry.role == ROLE
            }
            refs = {
                (update.entry.entity_path, update.latest)
                for update in repository.find_outdated_updates(PROJECT_ROOT)
                if update.entry.role == ROLE
            }
        self.assertTrue(
            {
                ("talk_signaling", "9.0.0"),
                ("talk_nats", "9.0.0-alpine"),
                ("talk", "9.0.0"),
                ("talk_recording", "3.14.9-alpine3.23"),
            }
            <= images,
            images,
        )
        self.assertEqual(refs, {(("talk",), "v9.0.0"), (("talk_recording",), "v9.0.0")})

    def test_negative_control_current_tags_report_nothing(self):
        current = {
            image: [_pinned(service, "version")]
            for service, image in self.IMAGES.items()
        }
        with (
            mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "2"}),
            mock.patch.object(
                docker, "fetch_dockerhub_tags", lambda image: current.get(image, [])
            ),
            mock.patch.object(docker, "fetch_ghcr_tags", lambda image: []),
            mock.patch.object(docker, "fetch_mcr_tags", lambda image: []),
            mock.patch.object(
                docker, "fetch_registry_tags", lambda image, last=None: []
            ),
        ):
            reported = {
                update.entry.service
                for update in docker.find_outdated_updates(PROJECT_ROOT)
                if update.entry.role == ROLE
            }
        self.assertFalse(reported & set(self.IMAGES), reported)


if __name__ == "__main__":
    unittest.main()
