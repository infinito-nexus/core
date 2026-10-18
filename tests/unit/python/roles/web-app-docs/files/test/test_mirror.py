"""``mirror.sh`` attaches the GHCR mirror to the published production block.

The injection is two ``sed`` patterns matched against the block the role README
template publishes. A template edit that renames the provision command takes
every guide row down with ``mirror.sh``'s own hard failure, so this renders the
template and asserts the patterns still land on what it publishes.

Both published shapes are covered, because the server recipe and the host
install reach provision through different working directories.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import jinja2

from utils.cache.files import read_text

from . import PROJECT_ROOT

MIRROR = PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "test" / "mirror.sh"
TEMPLATE_DIR = PROJECT_ROOT / "templates" / "roles"
TEMPLATE_NAME = "README.md.j2.tmpl"
PRODUCTION = re.compile(r"### Production\b.*?```bash\n(.*?)```", re.DOTALL)
ENVIRONMENT = {
    "DOCS_TEST_SRC_DIR": str(PROJECT_ROOT),
    "GITHUB_REPOSITORY": "Owner/Core",
    "GITHUB_REPOSITORY_OWNER": "Owner",
}
PREFIX = next(
    line.partition("=")[2]
    for line in read_text(str(PROJECT_ROOT / "default.env")).splitlines()
    if line.startswith("INFINITO_GHCR_MIRROR_PREFIX=")
)
CONTEXT = {
    "application_id": "web-app-example",
    "application_name": "Example",
    "application_invokable": True,
    "application_url": "https://example.com/",
    "application_description": "is an example.",
    "application_overview": "Deploys the example.",
    "application_features": [{"name": "Example", "description": "A feature."}],
    "application_author": "Kevin Veen-Birkenbach",
    "application_deploy_ids": "web-app-example",
    "application_needs_clearnet_resolver": False,
    "application_deploy_image": "ghcr.io/example/core/debian:latest",
    "software_repository": "https://github.com/example/core.git",
}


def _block(*, is_host: bool) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(),
    )
    rendered = environment.get_template(TEMPLATE_NAME).render(
        **CONTEXT, application_is_host=is_host
    )
    found = PRODUCTION.search(rendered)
    assert found, "the template publishes no Production block"
    return found.group(1)


def _inject(block: str, environment: dict) -> str:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "block.sh"
        path.write_text(block, encoding="utf-8")
        subprocess.run(
            ["bash", str(MIRROR), str(path)],
            check=True,
            capture_output=True,
            env=environment,
            text=True,
        )
        return path.read_text(
            encoding="utf-8"
        )  # nocheck: cache-read -- mirror.sh rewrote this tempfile in the same flow


class TestMirror(unittest.TestCase):
    def test_both_shapes_provision_against_the_mirror(self) -> None:
        for is_host, root in ((False, '"$INFINITO_SRC_DIR"'), (True, '"$PWD"')):
            with self.subTest(is_host=is_host):
                injected = _inject(_block(is_host=is_host), ENVIRONMENT)
                self.assertIn('provision --mirror "$INVENTORY/mirrors.yml"', injected)
                self.assertIn(
                    f"cli.contributing.mirror.resolver --repo-root {root} "
                    "--ghcr-namespace Owner --ghcr-repository Core "
                    f"--ghcr-prefix {PREFIX}",
                    injected,
                )
                subprocess.run(["bash", "-n"], input=injected, check=True, text=True)

    def test_an_unmirrored_run_leaves_the_block_alone(self) -> None:
        block = _block(is_host=False)
        outside = {"DOCS_TEST_SRC_DIR": str(PROJECT_ROOT)}
        self.assertEqual(_inject(block, outside), block)

    def test_a_block_without_provision_is_a_failure(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            _inject("echo nothing to mirror\n", ENVIRONMENT)


if __name__ == "__main__":
    unittest.main()
