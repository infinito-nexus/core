from __future__ import annotations

import contextlib
import io
import unittest

import cli.contributing.security.runtimes.__main__ as runtimes_main
from utils.docker.image.discovery import ImageRef

FLOORS = {"8.2": "8.2.35", "8.3": "8.3.36", "8.4": "8.4.27", "8.5": "8.5.12"}


def _ref(role, service):
    return ImageRef(
        role=role,
        service=service,
        name=f"acme/{service}",
        version="1.0",
        source=f"docker.io/acme/{service}:1.0",
    )


class TestReport(unittest.TestCase):
    def _report(self, refs, probed):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = runtimes_main.report(refs, probed, FLOORS)
        return code, out.getvalue()

    def test_an_eol_image_fails_the_report(self):
        code, output = self._report(
            [_ref("web-app-akaunting", "akaunting")], [["ENV PHP_VERSION=8.1.34"]]
        )
        self.assertEqual(code, 1)
        self.assertIn("runs the end-of-life line 8.1", output)

    def test_patched_images_and_images_without_php_pass(self):
        code, _output = self._report(
            [
                _ref("web-app-wordpress", "wordpress"),
                _ref("svc-db-postgres", "postgres"),
            ],
            [["ENV PHP_VERSION=8.4.27"], ["ENV PG_VERSION=17.2"]],
        )
        self.assertEqual(code, 0)

    def test_an_unanswered_image_fails_the_report(self):
        code, output = self._report([_ref("web-app-lam", "lam")], [None])
        self.assertEqual(code, 1)
        self.assertIn(
            "web-app-lam:lam (docker.io/acme/lam:1.0): the registry gave no answer",
            output,
        )

    def test_a_distro_line_without_patch_level_is_listed_but_passes(self):
        code, output = self._report(
            [_ref("web-app-lam", "lam")], [["RUN apt-get install -y php8.4-ldap"]]
        )
        self.assertEqual(code, 0)
        self.assertIn("PHP line 8.4: patch level not in the registry metadata", output)

    def test_an_unversioned_php_package_is_listed_with_unknown_patch_level(self):
        code, output = self._report(
            [_ref("web-app-lam", "lam")], [["RUN apt-get install -y php-cli"]]
        )
        self.assertEqual(code, 0)
        self.assertIn(
            "PHP package php-cli: patch level not in the registry metadata", output
        )
        self.assertIn("1 ship PHP", output)

    def test_an_eol_package_line_fails_next_to_a_patched_php_version(self):
        code, output = self._report(
            [_ref("web-app-lam", "lam")],
            [["ENV PHP_VERSION=8.4.27", "RUN apk add php7 php7-fpm"]],
        )
        self.assertEqual(code, 1)
        self.assertIn("PHP 8.4.27: line 7 is end of life", output)

    def test_an_eol_php_base_argument_fails_the_report(self):
        code, output = self._report(
            [_ref("web-app-fusiondirectory", "fusiondirectory")],
            [["ARG PHP_BASE=7.4", "RUN |1 PHP_BASE=7.4 /bin/bash -c install"]],
        )
        self.assertEqual(code, 1)
        self.assertIn("PHP line 7.4: line 7.4 is end of life", output)


if __name__ == "__main__":
    unittest.main()
