from __future__ import annotations

import json
import re
import unittest

from jinja2 import (
    ChoiceLoader,
    DictLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    select_autoescape,
)

from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

APP = "web-svc-logout"
EXTRAS = f"roles/{APP}/templates/csp/extras.yml.j2"
LOGOUT_PROTOCOL = "https"
CLEARNET = "cloud.example.test"
ONION = "cloudexampleonionaddress.onion"
ORIGINS = {
    CLEARNET: f"https://{CLEARNET}",
    ONION: f"http://{ONION}",
}
SWEPT = [ONION, CLEARNET, ONION]
HAND_BUILT = (
    "connect-src: {{ (lookup('applications') | logout_domains(group_names, lookup('domains')))"
    " | unique | sort | map('regex_replace', '^(.*)$', lookup('tls', application_id, 'protocols.web')"
    " ~ '://\\\\1') | list | to_json }}"
)


def _lookup(name, *terms):
    if name in ("applications", "domains"):
        return {}
    if name == "tls" and terms == (APP, "protocols.web"):
        return LOGOUT_PROTOCOL
    if name == "tls" and len(terms) == 2 and terms[1] == "url.origin":
        return ORIGINS[terms[0]]
    raise AssertionError(f"unexpected lookup {name} {terms}")


def render(template: str = EXTRAS) -> dict:
    """
    Args:
        template: the template name to render, the role's own by default.
    """
    env = Environment(
        loader=ChoiceLoader(
            [
                DictLoader({"hand-built.yml.j2": HAND_BUILT}),
                FileSystemLoader(str(PROJECT_ROOT)),
            ]
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["logout_domains"] = lambda applications, group_names, domains: SWEPT
    env.filters["to_json"] = json.dumps
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )
    env.globals["lookup"] = _lookup
    return load_yaml_str(
        env.get_template(template).render(application_id=APP, group_names=[APP])
    )


class TestLogoutCspExtras(unittest.TestCase):
    def test_every_swept_domain_is_allowed_at_its_own_origin(self):
        self.assertEqual(
            {"connect-src": [ORIGINS[CLEARNET], ORIGINS[ONION]]},
            render(),
        )

    def test_negative_control_one_protocol_for_every_domain_blocks_the_onion(self):
        self.assertNotIn(ORIGINS[ONION], render("hand-built.yml.j2")["connect-src"])


if __name__ == "__main__":
    unittest.main()
