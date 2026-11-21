import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-svc-translate"
SERVICES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_SERVICES)))
VARS = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
README = read_text(str(ROLE / "README.md"))
ORDER = SERVICES["translate"]["router"]["order"]
ENGINE_NAMES = re.findall(r"'name': '([^']+)'", VARS["TRANSLATE_ENGINES"])
LIBRETRANSLATE = "libretranslate-engine"


class TestEngineNames(unittest.TestCase):
    def test_every_routed_engine_has_a_place_in_the_order(self) -> None:
        self.assertEqual(sorted(ORDER), sorted(ENGINE_NAMES))

    def test_the_libretranslate_backend_carries_its_consumer_key(self) -> None:
        self.assertIn(LIBRETRANSLATE, SERVICES)
        self.assertIn(LIBRETRANSLATE, ENGINE_NAMES)
        self.assertIn(LIBRETRANSLATE, ORDER)
        self.assertIn(f"| `{LIBRETRANSLATE}` | [`svc-ai-{LIBRETRANSLATE}`]", README)
        self.assertNotIn("libretranslate", [*ENGINE_NAMES, *ORDER])


if __name__ == "__main__":
    unittest.main()
