from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ADDON = PROJECT_ROOT / "roles/web-app-nextcloud/meta/addons/onlyoffice.yml"


class TestOnlyofficeConfigurationOrder(unittest.TestCase):
    def test_the_document_server_url_is_written_last(self) -> None:
        config = load_yaml_str(read_text(str(ADDON)))["config"]["plugin_configuration"]
        self.assertEqual(
            config[-1]["configkey"],
            "DocumentServerUrl",
            "a cron.php that caches app config before the last write must see no "
            "DocumentServerUrl, or onlyoffice's EditorsCheck runs without jwt_secret "
            "and latches settings_error",
        )


if __name__ == "__main__":
    unittest.main()
