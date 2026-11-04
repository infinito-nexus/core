import importlib.util
import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles" / "web-app-atmo" / "files" / "python" / "cron.py"


def _load():
    spec = importlib.util.spec_from_file_location("atmo_cron_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cron = _load()

ENV = {
    "ATMO_CRON_URL": "http://atmo:8080/api/cron",
    "ATMO_CRON_SECRET": "s3cr3t",
    "ATMO_CRON_INTERVAL_SECONDS": "60",
    "ATMO_CRON_TIMEOUT_SECONDS": "120",
    "ATMO_CRON_BEAT_PATH": "/tmp/atmo-cron.beat",
}


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestTick(unittest.TestCase):
    def test_tick_posts_json_with_the_cron_secret(self):
        seen = []

        def opener(request, timeout):
            seen.append((request, timeout))
            return FakeResponse(b"OK")

        self.assertEqual(cron.tick(cron.load_config(ENV), opener), 200)
        request, timeout = seen[0]
        self.assertEqual(request.full_url, "http://atmo:8080/api/cron")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_header("X-cron-secret"), "s3cr3t")
        self.assertEqual(request.data, b"{}")
        self.assertEqual(timeout, 120)

    def test_rejected_tick_raises(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url, 401, "Unauthorized", {}, None
            )

        with self.assertRaises(urllib.error.HTTPError):
            cron.tick(cron.load_config(ENV), opener)


class TestHealth(unittest.TestCase):
    def test_health_follows_the_beat_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            beat = Path(tmp) / "beat"
            self.assertFalse(cron.healthy(beat, 1000.0, 60))
            cron.beat(beat, 1000.0)
            self.assertTrue(cron.healthy(beat, 1180.0, 60))
            self.assertFalse(cron.healthy(beat, 1181.0, 60))
            beat.write_text("garbage", encoding="utf-8")
            self.assertFalse(cron.healthy(beat, 1000.0, 60))


class TestConfig(unittest.TestCase):
    def test_missing_or_invalid_environment_refuses_to_start(self):
        for key in ENV:
            with self.subTest(missing=key), self.assertRaises(SystemExit):
                cron.load_config({k: v for k, v in ENV.items() if k != key})
        for key in ("ATMO_CRON_INTERVAL_SECONDS", "ATMO_CRON_TIMEOUT_SECONDS"):
            for value in ("0", "x"):
                with self.subTest(key=key, value=value), self.assertRaises(SystemExit):
                    cron.load_config({**ENV, key: value})
        with self.subTest(scheme="file"), self.assertRaises(SystemExit):
            cron.load_config({**ENV, "ATMO_CRON_URL": "file:///etc/passwd"})

    def test_unknown_command_is_rejected(self):
        self.assertEqual(cron.main(["cron.py", "tick"], ENV), 2)


if __name__ == "__main__":
    unittest.main()
