from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest import TestCase, main, mock

from utils.docker.image import runtime

FLOORS = {"8.2": "8.2.35", "8.3": "8.3.36", "8.4": "8.4.27", "8.5": "8.5.12"}


def _php(version=None, lines=(), packages=()):
    return runtime.PhpRuntime(
        version=version, lines=tuple(lines), packages=tuple(packages)
    )


class TestPhpRuntime(TestCase):
    def test_reads_php_version_from_an_env_instruction(self):
        self.assertEqual(
            runtime.php_runtime(
                ["ENV PHP_INI_DIR=/usr/local/etc/php", "ENV PHP_VERSION=8.4.15"]
            ),
            _php("8.4.15"),
        )

    def test_the_last_php_version_wins(self):
        self.assertEqual(
            runtime.php_runtime(
                ["ENV PHP_VERSION=8.3.1", "ENV PHP_VERSION=8.4.27"]
            ).version,
            "8.4.27",
        )

    def test_alpine_packages_name_their_line(self):
        found = runtime.php_runtime(
            ["RUN /bin/sh -c apk add php83 php83-fpm php83-ldap"]
        )
        self.assertEqual(found, _php(lines=["8.3"]))

    def test_debian_packages_name_their_line(self):
        found = runtime.php_runtime(
            ["RUN apt-get install -y php8.4-cli libapache2-mod-php8.4 php8.4-ldap"]
        )
        self.assertEqual(found, _php(lines=["8.4"]))

    def test_an_unversioned_alpine_php7_package_names_its_major(self):
        self.assertEqual(
            runtime.php_runtime(["RUN apk add php7 php7-fpm"]), _php(lines=["7"])
        )

    def test_a_php_base_build_argument_names_its_line(self):
        self.assertEqual(
            runtime.php_runtime(
                ["ARG PHP_BASE=7.4", "RUN |1 PHP_BASE=7.4 /bin/bash -c build"]
            ),
            _php(lines=["7.4"]),
        )

    def test_a_php_directory_outside_a_package_install_is_not_php(self):
        self.assertIsNone(
            runtime.php_runtime(
                ["COPY /app/snuffleupagus.so /usr/lib/php83/modules/ # buildkit"]
            )
        )

    def test_apk_options_before_add_still_name_the_line(self):
        self.assertEqual(
            runtime.php_runtime(["RUN apk --no-cache add php7 php7-fpm"]),
            _php(lines=["7"]),
        )

    def test_apk_in_a_path_or_comment_is_no_package_install(self):
        for instruction in (
            "RUN rm -rf /var/cache/apk/* && cp php7 /srv/add",
            "RUN echo php7 # apk cache: add nothing",
        ):
            with self.subTest(instruction=instruction):
                self.assertIsNone(runtime.php_runtime([instruction]))

    def test_a_pinned_alpine_package_names_its_line(self):
        found = runtime.php_runtime(["RUN apk add --no-cache php84=8.4.27-r0 nginx;"])
        self.assertEqual(found, _php(lines=["8.4"]))

    def test_php_paths_are_not_packages(self):
        self.assertIsNone(
            runtime.php_runtime(
                ['RUN mkdir -p "$PHP_INI_DIR/conf.d" /usr/local/etc/php']
            )
        )

    def test_an_unversioned_debian_runtime_package_is_php(self):
        self.assertEqual(
            runtime.php_runtime(["RUN apt-get install -y php-cli"]),
            _php(packages=["php-cli"]),
        )

    def test_unversioned_runtime_packages_are_php(self):
        found = runtime.php_runtime(
            [
                "RUN dnf install -y php php-fpm php-mysqlnd",
                "RUN apt-get install -y libapache2-mod-php php-cgi=2:8.2+93 \\",
            ]
        )
        self.assertEqual(
            found, _php(packages=["libapache2-mod-php", "php", "php-cgi", "php-fpm"])
        )

    def test_php_libraries_extensions_and_paths_are_not_a_runtime(self):
        self.assertIsNone(
            runtime.php_runtime(
                [
                    (
                        "RUN apt-get install -y php-common php-pear php-mysql phpmyadmin"
                        " && docker-php-ext-install gd && cp php-fpm.conf /etc/php-fpm.d/"
                    )
                ]
            )
        )

    def test_an_image_without_php_has_no_runtime(self):
        self.assertIsNone(
            runtime.php_runtime(
                ["ENV PG_VERSION=17.2", "RUN apt-get install -y postgresql"]
            )
        )


class TestPhpFinding(TestCase):
    def test_a_version_below_its_floor_is_a_finding(self):
        self.assertIn(
            "below the security floor 8.4.27",
            runtime.php_finding(_php("8.4.15"), FLOORS),
        )

    def test_a_version_at_its_floor_is_fine(self):
        self.assertIsNone(runtime.php_finding(_php("8.2.35"), FLOORS))

    def test_php_8_1_is_end_of_life(self):
        self.assertIn(
            "end-of-life line 8.1", runtime.php_finding(_php("8.1.34"), FLOORS)
        )

    def test_a_line_newer_than_every_floor_is_fine(self):
        self.assertIsNone(runtime.php_finding(_php("8.6.0"), FLOORS))

    def test_a_distro_php7_is_end_of_life(self):
        self.assertEqual(
            runtime.php_finding(_php(lines=["7"]), FLOORS), "line 7 is end of life"
        )

    def test_a_distro_php_8_1_is_end_of_life(self):
        self.assertEqual(
            runtime.php_finding(_php(lines=["8.1"]), FLOORS), "line 8.1 is end of life"
        )

    def test_a_supported_distro_line_is_no_finding(self):
        self.assertIsNone(runtime.php_finding(_php(lines=["8.3"]), FLOORS))

    def test_an_eol_line_fails_next_to_a_patched_php_version(self):
        self.assertEqual(
            runtime.php_finding(_php("8.4.27", lines=["7"]), FLOORS),
            "line 7 is end of life",
        )

    def test_a_php_version_below_its_floor_outranks_an_eol_line(self):
        self.assertIn(
            "below the security floor 8.4.27",
            runtime.php_finding(_php("8.4.15", lines=["7"]), FLOORS),
        )

    def test_an_unversioned_package_alone_is_no_finding(self):
        self.assertIsNone(runtime.php_finding(_php(packages=["php-cli"]), FLOORS))


class TestLoadPhpFloors(TestCase):
    def test_reads_the_php_floors_from_the_vars_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.yml"
            path.write_text(
                "HEALTH_RUNTIME_FLOORS:\n  php:\n    '8.4': '8.4.27'\n",
                encoding="utf-8",
            )
            with mock.patch.object(runtime, "FLOORS_FILE", path):
                self.assertEqual(runtime.load_php_floors(), {"8.4": "8.4.27"})


class TestBuildInstructions(TestCase):
    def test_a_docker_hub_tag_is_read_through_the_hub_api(self):
        with (
            mock.patch.object(
                runtime, "_hub_instructions", return_value=["ENV A=1"]
            ) as hub,
            mock.patch.object(runtime, "config_blob") as blob,
        ):
            found = runtime.build_instructions(
                "docker.io/wordpress", "6.8", os_name="linux", architecture="amd64"
            )
        self.assertEqual(found, ["ENV A=1"])
        hub.assert_called_once_with("library/wordpress", "6.8", "linux", "amd64")
        blob.assert_not_called()

    def test_another_registry_is_read_through_the_config_blob(self):
        blob = {
            "history": [{"created_by": "RUN apk add php84"}],
            "config": {"Env": ["PHP_VERSION=8.4.27"]},
        }
        with mock.patch.object(runtime, "config_blob", return_value=blob):
            found = runtime.build_instructions(
                "ghcr.io/acme/app", "1.0", os_name="linux", architecture="amd64"
            )
        self.assertEqual(found, ["RUN apk add php84", "ENV PHP_VERSION=8.4.27"])

    def test_a_docker_hub_digest_pin_is_read_through_the_config_blob(self):
        with (
            mock.patch.object(runtime, "_hub_instructions") as hub,
            mock.patch.object(runtime, "config_blob", return_value=None),
        ):
            found = runtime.build_instructions(
                "docker.io/acme/app",
                "sha256:" + "a" * 64,
                os_name="linux",
                architecture="amd64",
            )
        self.assertIsNone(found)
        hub.assert_not_called()


class TestHubInstructions(TestCase):
    def _respond(self, payload):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
        return mock.patch.object(
            runtime.urllib.request, "urlopen", return_value=response
        )

    def test_picks_the_layers_of_the_requested_platform(self):
        payload = [
            {
                "os": "linux",
                "architecture": "arm64",
                "layers": [{"instruction": "ENV PHP_VERSION=1"}],
            },
            {
                "os": "linux",
                "architecture": "amd64",
                "layers": [{"instruction": "ENV PHP_VERSION=2"}],
            },
        ]
        with self._respond(payload):
            found = runtime._hub_instructions("library/php", "8.4", "linux", "amd64")
        self.assertEqual(found, ["ENV PHP_VERSION=2"])

    def test_a_tag_without_the_platform_is_unanswered(self):
        with self._respond([{"os": "linux", "architecture": "arm64", "layers": []}]):
            self.assertIsNone(
                runtime._hub_instructions("library/php", "8.4", "linux", "amd64")
            )

    def test_a_network_error_is_unanswered(self):
        with mock.patch.object(
            runtime.urllib.request,
            "urlopen",
            side_effect=runtime.urllib.error.URLError("down"),
        ):
            self.assertIsNone(
                runtime._hub_instructions("library/php", "8.4", "linux", "amd64")
            )


if __name__ == "__main__":
    main()
