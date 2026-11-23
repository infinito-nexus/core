from __future__ import annotations

import os
import re
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.docker.image.discovery import RUNNER_ROLE
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_TEMPL_COMPOSE
from utils.update import docker

COMPOSE = """\
---
x-ci-defaults: &ci_defaults
  dns_opt:
    - ndots:1

services:
  coredns:
    image: coredns/coredns:1.14.4
    command: ["-conf", "/Corefile"]
  infinito:
    <<: *ci_defaults
    image: "${INFINITO_IMAGE}"
"""

CACHE_OVERRIDE = """\
---
# Layered on compose.yml by the dev tooling.

services:
  registry-cache:
    image: rpardini/docker-registry-proxy:0.6.5
    container_name: infinito-registry-cache
  package-cache:
    image: "sonatype/nexus3:3.91.1-ubi"  # Keep comment
  package-cache-frontend:
    image: nginx:1.27-alpine
  frozen:
    # nocheck: docker-version upstream dropped the arm64 build
    image: busybox:1.36.1
  moving:
    image: alpine:latest
  untagged:
    image: busybox
  pinned:
    image: nginx@sha256:d5591131b1d898cd02fc7a17adb8ea026352d67809bc9289707778e9e03a76a4
  interpolated:
    image: "${INFINITO_IMAGE}:1.0.0"
"""

STACK = """\
services:
  mirror:
    image: registry:2.8.3
    restart: unless-stopped
"""

SWARM = """\
x-node: &node
  image: infinito-swarm-node
services:
  manager:
    <<: *node
"""

PLAYBOOK = """\
---
- name: a playbook, not a compose file
  command: /bin/true
"""

HARNESS = """\
services:
  outside:
    image: postgres:16.4
"""

TEMPLATE = """\
services:
  registry:
    image: "{{ REGISTRY_IMAGE }}:{{ REGISTRY_VERSION }}"
  literal:
    image: redis:7.4.1
"""

SERVICES = """\
moodle:
  image: bitnamilegacy/moodle
  version: "4.5"
services:
  image: redis
  version: "7.4.1"
"""

SYMFONY = """\
services:
  _defaults:
    autowire: true
  session.handler:
    class: Symfony\\Component\\HttpFoundation\\Session\\Storage\\Handler\\PdoSessionHandler
"""

TWO_DOCUMENTS = """\
services:
  first:
    image: redis:7.4.1
---
services:
  second:
    image: redis:7.4.1
"""

UNPARSABLE = """\
services:
  broken: [redis:7.4.1
"""

TRACKED = {
    "compose.yml": COMPOSE,
    "compose/cache.override.yml": CACHE_OVERRIDE,
    "compose/swarm/compose.yml": SWARM,
    "compose/swarm/playbook.yml": PLAYBOOK,
    "ci/registry.stack.yaml": STACK,
    f"roles/svc-x/{ROLE_FILE_META_SERVICES}": SERVICES,
    f"roles/svc-x/{ROLE_FILE_TEMPL_COMPOSE}": TEMPLATE,
    "roles/svc-x/files/test/compose.yml": HARNESS,
    "roles/svc-x/files/docker-compose.yaml": HARNESS,
    "roles/svc-x/files/session.yaml": SYMFONY,
    "tests/fixtures/stack.yml": STACK,
    "ops/two.yml": TWO_DOCUMENTS,
    "ops/broken.yml": UNPARSABLE,
}

UNTRACKED = {"scratch/stack.yml": STACK}

OWNED = ["ci/registry.stack.yaml", "compose/cache.override.yml"]

TAGS = {
    "coredns/coredns": ["1.14.4", "1.14.5", "1.15.0"],
    "rpardini/docker-registry-proxy": ["0.6.5", "0.8.0", "latest"],
    "sonatype/nexus3": ["3.91.1-ubi", "3.92.0-ubi", "3.93.0", "3.93.0-java21"],
    "nginx": ["1.27-alpine", "1.29-alpine", "1.29.3-alpine", "1.30"],
    "busybox": ["1.36.1", "1.37.0"],
    "alpine": ["latest", "3.20.3"],
    "registry": ["2.8.3", "3.0.0"],
    "postgres": ["16.4", "17.2"],
    "redis": ["7.4.1", "8.0.0"],
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(root: Path) -> Path:
    for rel, text in {**TRACKED, **UNTRACKED}.items():
        _write(root / rel, text)
    return root


def _registry(tags: dict[str, list[str]]):
    def _tags(image: str, *_args, **_kwargs) -> list[str]:
        return tags.get(image, [])

    return mock.patch.multiple(
        docker,
        fetch_dockerhub_tags=mock.Mock(side_effect=_tags),
        fetch_ghcr_tags=mock.Mock(side_effect=_tags),
        fetch_mcr_tags=mock.Mock(side_effect=_tags),
        fetch_registry_tags=mock.Mock(side_effect=_tags),
    )


def _bump(root: Path, tracked: list[str], tags: dict[str, list[str]]) -> list[Path]:
    with (
        mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "2"}),
        _registry(tags),
    ):
        return docker.apply_updates(docker.find_outdated_compose_updates(root, tracked))


def _compose_update(path: Path, service: str, image: str, current: str, latest: str):
    return docker.DockerImageVersionUpdate(
        entry=docker.DockerImageVersionEntry(
            role=RUNNER_ROLE,
            service=service,
            image=image,
            version=current,
            config_path=path,
        ),
        latest=latest,
    )


class TestComposeDiscovery(unittest.TestCase):
    def test_compose_files_are_recognized_by_their_services_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            files = docker.compose_files(root, list(TRACKED))
        self.assertEqual(files, OWNED)

    def test_the_tagged_semver_pins_of_the_compose_files_are_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            found = [
                (
                    entry.config_path.relative_to(root).as_posix(),
                    entry.role,
                    entry.service,
                    entry.image,
                    entry.version,
                )
                for entry in docker.collect_compose_entries(root, list(TRACKED))
            ]
        self.assertEqual(
            found,
            [
                ("ci/registry.stack.yaml", RUNNER_ROLE, "mirror", "registry", "2.8.3"),
                (
                    "compose/cache.override.yml",
                    RUNNER_ROLE,
                    "registry-cache",
                    "rpardini/docker-registry-proxy",
                    "0.6.5",
                ),
                (
                    "compose/cache.override.yml",
                    RUNNER_ROLE,
                    "package-cache",
                    "sonatype/nexus3",
                    "3.91.1-ubi",
                ),
                (
                    "compose/cache.override.yml",
                    RUNNER_ROLE,
                    "package-cache-frontend",
                    "nginx",
                    "1.27-alpine",
                ),
            ],
        )

    def test_an_image_inherited_through_a_merge_anchor_is_not_collected(self):
        merged = (
            "x-base: &base\n"
            "  image: redis:7.4.1\n"
            "services:\n"
            "  inherited:\n"
            "    <<: *base\n"
            "  literal:\n"
            "    image: nginx:1.27-alpine\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "ops/merged.yml", merged)
            entries = docker.collect_compose_entries(root, ["ops/merged.yml"])
        self.assertEqual(
            [(entry.service, entry.image) for entry in entries],
            [("literal", "nginx")],
        )

    def test_the_version_policy_of_role_pins_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            with (
                mock.patch.dict(os.environ, {"INFINITO_WORKER_FETCH": "2"}),
                _registry(TAGS),
            ):
                moves = {
                    update.entry.service: update.latest
                    for update in docker.find_outdated_compose_updates(
                        root, list(TRACKED)
                    )
                }
        self.assertEqual(
            moves,
            {
                "mirror": "3.0.0",
                "registry-cache": "0.8.0",
                "package-cache": "3.92.0-ubi",
                "package-cache-frontend": "1.29-alpine",
            },
        )


class TestComposeBump(unittest.TestCase):
    def test_only_the_due_tags_move_and_every_other_file_and_byte_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp))
            changed = _bump(root, list(TRACKED), TAGS)
            _reset_cache_for_tests()
            after = {rel: read_text(str(root / rel)) for rel in TRACKED}

        self.assertEqual(
            sorted(path.relative_to(root).as_posix() for path in changed), OWNED
        )
        expected = {
            **TRACKED,
            "ci/registry.stack.yaml": STACK.replace("registry:2.8.3", "registry:3.0.0"),
            "compose/cache.override.yml": CACHE_OVERRIDE.replace(
                "docker-registry-proxy:0.6.5", "docker-registry-proxy:0.8.0"
            )
            .replace('nexus3:3.91.1-ubi"', 'nexus3:3.92.0-ubi"')
            .replace("nginx:1.27-alpine", "nginx:1.29-alpine"),
        }
        self.assertEqual(after, expected)

    def test_the_real_registry_cache_pin_moves_to_the_newest_tag_alone(self):
        rel = "compose/cache.override.yml"
        original = read_text(str(PROJECT_ROOT / rel))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / rel, original)
            entries = docker.collect_compose_entries(root, [rel])
            tags = {entry.image: [entry.version] for entry in entries}
            current = tags["rpardini/docker-registry-proxy"][0]
            newest = re.sub(
                r"\d+", lambda major: str(int(major.group()) + 1), current, count=1
            )
            tags["rpardini/docker-registry-proxy"] = [current, newest, "latest"]
            changed = _bump(root, [rel], tags)
            _reset_cache_for_tests()
            after = read_text(str(root / rel))

        self.assertEqual(changed, [root / rel])
        old = f"rpardini/docker-registry-proxy:{current}"
        self.assertEqual(original.count(old), 1)
        self.assertEqual(
            after,
            original.replace(old, f"rpardini/docker-registry-proxy:{newest}"),
        )

    def test_quoted_and_commented_tags_keep_their_quotes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.override.yml"
            path.write_text(CACHE_OVERRIDE, encoding="utf-8")

            changed = docker.apply_updates(
                [
                    _compose_update(
                        path,
                        "package-cache",
                        "sonatype/nexus3",
                        "3.91.1-ubi",
                        "3.92.0-ubi",
                    ),
                ]
            )

            self.assertEqual(changed, [path])
            self.assertEqual(
                read_text(str(path)),
                CACHE_OVERRIDE.replace(
                    'image: "sonatype/nexus3:3.91.1-ubi"  # Keep comment',
                    'image: "sonatype/nexus3:3.92.0-ubi"  # Keep comment',
                ),
            )

    def test_role_pins_still_move_through_their_version_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "roles" / "web-app-moodle" / ROLE_FILE_META_SERVICES
            _write(config, SERVICES)

            docker.apply_updates(
                [
                    docker.DockerImageVersionUpdate(
                        entry=docker.DockerImageVersionEntry(
                            role="web-app-moodle",
                            service="moodle",
                            image="bitnamilegacy/moodle",
                            version="4.5",
                            config_path=config,
                        ),
                        latest="5.0",
                    )
                ]
            )

            self.assertEqual(read_text(str(config)), SERVICES.replace('"4.5"', '"5.0"'))


if __name__ == "__main__":
    unittest.main()
