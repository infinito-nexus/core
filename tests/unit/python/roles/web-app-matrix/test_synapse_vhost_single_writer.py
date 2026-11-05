from __future__ import annotations

import os
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
)

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

PROXY_TEMPLATE = "roles/web-app-matrix/templates/proxy.conf.j2"
TASKS_DIR = PROJECT_ROOT / "roles/web-app-matrix/tasks"
SYNAPSE_VHOST_DEST = "lookup('nginx', 'files.domain', MATRIX_SYNAPSE_DOMAIN)"

STUBS = {
    "roles/web-app-matrix/templates/flavor/ansible/synapse.conf.j2": "ANSIBLE_SYNAPSE",
    "roles/web-app-matrix/templates/synapse.conf.j2": "COMPOSE_SYNAPSE",
    "roles/sys-svc-proxy/templates/vhost/basic.conf.j2": "BASIC",
}

SYNAPSE_DOMAIN = "matrix.example.test"


def _render(*, domain: str, flavor: str) -> str:
    """Render the front-proxy template of web-app-matrix with stubbed includes.

    Args:
        domain: vhost domain the front proxy renders.
        flavor: value of the matrix_flavor fact.

    Returns:
        The rendered marker of the included vhost template.
    """
    env = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        loader=ChoiceLoader([DictLoader(STUBS), FileSystemLoader(str(PROJECT_ROOT))]),
    )
    return (
        env.get_template(PROXY_TEMPLATE)
        .render(
            domain=domain,
            matrix_flavor=flavor,
            MATRIX_SYNAPSE_DOMAIN=SYNAPSE_DOMAIN,
        )
        .strip()
    )


class TestSynapseVhostSingleWriter(unittest.TestCase):
    def test_ansible_flavor_front_proxy_renders_the_ansible_synapse_vhost(
        self,
    ) -> None:
        self.assertEqual(
            _render(domain=SYNAPSE_DOMAIN, flavor="ansible"), "ANSIBLE_SYNAPSE"
        )

    def test_compose_flavor_front_proxy_renders_the_compose_synapse_vhost(
        self,
    ) -> None:
        self.assertEqual(
            _render(domain=SYNAPSE_DOMAIN, flavor="compose"), "COMPOSE_SYNAPSE"
        )

    def test_other_domains_render_the_basic_vhost(self) -> None:
        for flavor in ("ansible", "compose"):
            with self.subTest(flavor=flavor):
                self.assertEqual(
                    _render(domain="element.example.test", flavor=flavor), "BASIC"
                )

    def test_no_matrix_task_rewrites_the_front_proxy_synapse_vhost(self) -> None:
        task_files = [
            path
            for path in sorted(iter_project_files(extensions=(".yml",)))
            if path.startswith(f"{TASKS_DIR}{os.sep}")
        ]
        self.assertTrue(task_files, f"no task files found under {TASKS_DIR}")
        writers = [
            os.path.relpath(path, PROJECT_ROOT)
            for path in task_files
            if SYNAPSE_VHOST_DEST in read_text(path)
        ]
        self.assertEqual(
            writers,
            [],
            "sys-stk-front-proxy owns the Synapse vhost; a second writer flips "
            "its content every deploy and forces an OpenResty redeploy",
        )


if __name__ == "__main__":
    unittest.main()
