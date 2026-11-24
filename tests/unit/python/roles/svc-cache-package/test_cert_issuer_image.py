from __future__ import annotations

import unittest
import unittest.mock as mock
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.lookup.image import LookupModule as ImageLookup
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.docker.image.discovery import canonical_image_name, iter_role_images
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

APP = "svc-cache-package"
ROLE = PROJECT_ROOT / "roles" / APP
APPLICATIONS = {
    APP: {"services": load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))}
}
INIT_IMAGE = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))[
    "CACHE_PACKAGE_INIT_IMAGE"
]


def _lookup(name: str, *terms: str, **kwargs: Any) -> Any:
    """Resolve the lookups the role's vars use against its own services map.

    Args:
        name: lookup plugin name, ``image`` or ``config``.
        terms: the lookup's positional terms.
        kwargs: forwarded to the ``image`` lookup.
    """
    if name == "image":
        with mock.patch("plugins.lookup.image.lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [APPLICATIONS]
            )
            return ImageLookup().run(
                list(terms), variables={"DEPLOYMENT_MODE": "compose"}, **kwargs
            )[0]
    if name == "config":
        application_id, path = terms
        value: Any = APPLICATIONS[application_id]
        for key in path.split("."):
            value = value[key]
        return value
    raise AssertionError(f"unexpected lookup '{name}'")


def _issuer_image() -> str:
    env = Environment(
        autoescape=select_autoescape(default_for_string=False),
        undefined=StrictUndefined,
    )
    return env.from_string(INIT_IMAGE).render(application_id=APP, lookup=_lookup)


class TestCertIssuerImage(unittest.TestCase):
    def test_the_issuer_image_is_one_the_image_discovery_yields(self) -> None:
        discovered = {
            (ref.name, ref.version)
            for ref in iter_role_images(PROJECT_ROOT)
            if ref.role == APP
        }
        name, _, version = _issuer_image().rpartition(":")
        self.assertIn((canonical_image_name(name), version), discovered)

    def test_the_issuer_reuses_the_frontend_image_so_it_pulls_nothing_extra(
        self,
    ) -> None:
        self.assertEqual(_lookup("image", APP, "frontend"), _issuer_image())


if __name__ == "__main__":
    unittest.main()
