import unittest
import unittest.mock as mock
import urllib.error

from utils.i18n.libretranslate import LibreTranslate


class TestTranslateFailures(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LibreTranslate("http://libretranslate", 1)

    def test_an_unreachable_server_stops_the_run(self) -> None:
        refused = urllib.error.URLError(ConnectionRefusedError())
        with (
            mock.patch.object(self.client, "_call", side_effect=refused),
            self.assertRaises(OSError),
        ):
            self.client.translate(["Hello", "World"], "de")

    def test_a_rejected_request_discards_only_its_texts(self) -> None:
        rejected = urllib.error.HTTPError(
            "http://libretranslate", 500, "boom", {}, None
        )
        with mock.patch.object(self.client, "_call", side_effect=rejected):
            self.assertEqual(
                self.client.translate(["Hello", "World"], "de"), [None, None]
            )


if __name__ == "__main__":
    unittest.main()
