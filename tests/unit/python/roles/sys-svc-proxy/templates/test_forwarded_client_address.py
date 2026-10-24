from __future__ import annotations

import unittest

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.on_off import on_off
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

TEMPLATE_DIR = PROJECT_ROOT / "roles/sys-svc-proxy/templates/headers"
FORWARDED_LINE = 'proxy_set_header Forwarded "for=$remote_addr";'


def render(**context) -> str:
    """Return forwarded.conf.j2 rendered with a stubbed `tls` lookup.

    Args:
        context: variables the template reads.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = lambda value: boolean(value, strict=False)
    env.filters["on_off"] = on_off
    return env.get_template("forwarded.conf.j2").render(
        application_id="web-app-stalwart",
        lookup=lambda *_a, **_k: True,
        **context,
    )


class TestForwardedClientAddress(unittest.TestCase):
    def test_an_opted_in_vhost_sends_the_client_address(self):
        rendered = render(proxy_forwarded_client_address=True)
        self.assertEqual(rendered.count(FORWARDED_LINE), 1)

    def test_other_vhosts_send_no_forwarded_header(self):
        self.assertNotIn('Forwarded "', render())
        self.assertNotIn('Forwarded "', render(proxy_forwarded_client_address=False))

    def test_stalwart_opts_its_vhost_in(self):
        tasks = load_yaml_any(PROJECT_ROOT / "roles/web-app-stalwart/tasks/00_core.yml")
        full_stack = [
            task
            for task in tasks
            if (task.get("include_role") or {}).get("name") == "sys-stk-full"
        ]
        self.assertEqual(len(full_stack), 1)
        self.assertIs(full_stack[0]["vars"]["proxy_forwarded_client_address"], True)


if __name__ == "__main__":
    unittest.main()
