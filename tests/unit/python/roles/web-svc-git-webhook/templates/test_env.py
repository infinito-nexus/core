"""``WEBHOOK_PROVIDERS`` reaches the swarm receiver as one JSON object.

``docker stack deploy`` passes an env-file value through verbatim, so the value
the template renders in swarm mode is exactly what the receiver decodes. The
line is extracted from the template rather than restated here, so a change to
the template is a change to what this test renders.
"""

from __future__ import annotations

import json
import re
import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, read_text

_TEMPLATE = PROJECT_ROOT / "roles/web-svc-git-webhook/templates/env.j2"
_LINE = re.compile(r"^WEBHOOK_PROVIDERS=.*$", re.MULTILINE)
_PROVIDERS = {
    "/github": {
        "provider": "github",
        "secret": "s3cr3t",
        "api_url": "https://api.github.com",
        "token": "",
    },
    "/gitea": {
        "provider": "gitea",
        "secret": "",
        "api_url": "https://gitea.invalid/api/v1",
        "token": "",
    },
}


def _render(mode: str) -> str:
    line = _LINE.search(read_text(str(_TEMPLATE)))
    assert line, f"{_TEMPLATE} no longer renders WEBHOOK_PROVIDERS"
    templar = Templar(
        loader=DataLoader(),
        variables={"DEPLOYMENT_MODE": mode, "GIT_WEBHOOK_PROVIDERS": _PROVIDERS},
    )
    rendered = templar.template(trust_as_template(line.group(0)))
    return rendered.split("=", 1)[1]


class TestWebhookProvidersEnv(unittest.TestCase):
    def test_swarm_value_decodes_to_the_provider_map_in_one_load(self):
        self.assertEqual(json.loads(_render("swarm")), _PROVIDERS)


if __name__ == "__main__":
    unittest.main()
