from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path

from crossposter import __main__ as cli


class CliFixture:
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        folder = Path(self.directory.name)
        secrets = {
            "openpost_token": "op-token",
            "database_dsn": "postgresql://crossposter@db/openpost",
            "routes": {"press": "source-token"},
        }
        (folder / "crossposter-secrets.json").write_text(json.dumps(secrets))
        self.heartbeat = folder / "heartbeat"
        self.raw = {
            "openpost": {
                "base_url": "http://openpost:8080",
                "host": "publish.example",
                "workspace": "workspace-1",
            },
            "secrets_file": str(folder / "crossposter-secrets.json"),
            "mail": None,
            "heartbeat_file": str(self.heartbeat),
            "poll_interval_seconds": 60,
            "opt_out_tag": "nocrosspost",
            "retry": {"max_attempts": 8, "base_seconds": 30, "cap_seconds": 3600},
            "notify": {"recipients": []},
            "routes": [],
        }
        self.config = folder / "crossposter.json"
        self.write()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write(self) -> None:
        self.config.write_text(json.dumps(self.raw))


class TestHealth(CliFixture, unittest.TestCase):
    def test_a_fresh_active_heartbeat_is_healthy(self) -> None:
        self.heartbeat.write_text(f"{time.time():.0f} active\n")
        self.assertEqual(cli.command_health(str(self.config)), 0)

    def test_a_standby_instance_is_healthy(self) -> None:
        self.heartbeat.write_text(f"{time.time():.0f} standby\n")
        self.assertEqual(cli.command_health(str(self.config)), 0)

    def test_a_stale_heartbeat_is_unhealthy(self) -> None:
        self.heartbeat.write_text(f"{time.time() - 600:.0f} active\n")
        self.assertEqual(cli.command_health(str(self.config)), 1)

    def test_a_missing_heartbeat_is_unhealthy(self) -> None:
        self.assertEqual(cli.command_health(str(self.config)), 1)

    def test_a_waiting_instance_stays_healthy_while_its_configuration_is_incomplete(
        self,
    ) -> None:
        self.raw["routes"] = [{"name": "press", "source": {"platform": "mastodon"}}]
        self.write()
        self.heartbeat.write_text(f"{time.time():.0f} waiting\n")
        self.assertEqual(cli.command_health(str(self.config)), 0)

    def test_waiting_for_provisioning_stays_healthy(self) -> None:
        pause = cli.wait_for_configuration(str(self.config), ValueError("no token yet"))
        self.assertEqual(pause, 60)
        written = self.heartbeat.read_text()  # nocheck: cache-read  tempdir file
        self.assertTrue(written.strip().endswith("waiting"))
        self.assertEqual(cli.command_health(str(self.config)), 0)


class TestValidate(CliFixture, unittest.TestCase):
    def test_an_invalid_route_names_route_and_field(self) -> None:
        self.raw["routes"] = [
            {
                "name": "press",
                "source": {
                    "platform": "myspace",
                    "base_url": "https://microblog.example",
                    "account": "press",
                },
                "filters": {"visibility": ["public"], "media": "any"},
                "targets": {"accounts": ["x-press"]},
                "mode": "review",
                "attribution": {"default": "{text}"},
            }
        ]
        self.write()
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(cli.command_validate(str(self.config)), 2)
        self.assertIn("route 'press': source.platform", errors.getvalue())

    def test_no_routes_validate_without_asking_openpost(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.command_validate(str(self.config)), 0)
        self.assertIn("0 route(s) valid", output.getvalue())
