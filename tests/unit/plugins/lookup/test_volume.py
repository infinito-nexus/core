"""Unit tests for the ``volume`` lookup plugin.

Pins the SPOT contract that replaces the legacy

    {{ (applications | get_app_conf(application_id, 'docker.volumes', True))[name] }}

ad-hoc list-walk: callers always get a normalised dict with both the
effective docker volume name and the original semantic name, plus the
legacy ``path:`` field surfaced for path-style entries.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.lookup.volume import LookupModule


def _run(
    application_id: str,
    name: str,
    *,
    canonical: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    with (
        patch(
            "plugins.lookup.volume.get_canonical_volumes",
            return_value=canonical if canonical is not None else {},
        ),
        patch("plugins.lookup.volume.get_application_defaults"),
    ):
        return LookupModule().run([application_id, name], variables={})


class TestVolumeLookup(unittest.TestCase):
    def test_returns_docker_name_when_present(self):
        canonical = {
            "data": {
                "type": "volume",
                "name": "mattermost_data",
                "mounts": [
                    {"service": "application", "target": "/mattermost/data"},
                ],
            },
        }
        out = _run("web-app-mattermost", "data", canonical=canonical)
        self.assertEqual(len(out), 1)
        entry = out[0]
        self.assertEqual(entry["name"], "mattermost_data")
        self.assertEqual(entry["semantic_name"], "data")
        self.assertEqual(entry["docker_name"], "mattermost_data")
        self.assertEqual(entry["type"], "volume")
        self.assertEqual(entry["path"], "")
        self.assertEqual(entry["source"], "")
        self.assertIsNone(entry["nfs"])
        self.assertEqual(
            entry["mounts"],
            [{"service": "application", "target": "/mattermost/data"}],
        )

    def test_falls_back_to_semantic_name_when_docker_name_missing(self):
        canonical = {
            "config": {
                "type": "bind",
                "source": "/etc/listmonk/config.toml",
            },
        }
        out = _run("web-app-listmonk", "config", canonical=canonical)
        entry = out[0]
        self.assertEqual(entry["name"], "config")
        self.assertEqual(entry["semantic_name"], "config")
        self.assertEqual(entry["docker_name"], "")
        self.assertEqual(entry["type"], "bind")
        self.assertEqual(entry["source"], "/etc/listmonk/config.toml")

    def test_returns_path_from_path_entries(self):
        canonical = {
            "www": {"type": "volume", "path": "/var/www/"},
            "nginx": {"type": "volume", "path": "/etc/nginx/"},
        }
        out = _run("svc-prx-openresty", "www", canonical=canonical)
        entry = out[0]
        self.assertEqual(entry["semantic_name"], "www")
        self.assertEqual(entry["name"], "www")
        self.assertEqual(entry["path"], "/var/www/")
        self.assertEqual(entry["type"], "volume")

    def test_returns_full_dict_for_various_types(self):
        canonical = {
            "nginx_conf": {
                "type": "config",
                "source": "/etc/nginx/nginx.conf",
                "mounts": [
                    {
                        "service": "openresty",
                        "target": "/usr/local/openresty/nginx/conf/nginx.conf",
                    },
                ],
            },
            "docker_sock": {
                "type": "bind",
                "source": "/var/run/docker.sock",
                "mounts": [
                    {"service": "openresty", "target": "/var/run/docker.sock"},
                ],
            },
            "tls_key": {
                "type": "secret",
                "source": "/run/secrets/tls.key",
            },
            "scratch": {
                "type": "tmpfs",
                "mounts": [{"service": "application", "target": "/tmp"}],
            },
            "shared": {
                "type": "volume",
                "name": "mediawiki_shared",
                "nfs": True,
            },
        }

        config = _run("svc-prx-openresty", "nginx_conf", canonical=canonical)[0]
        self.assertEqual(config["type"], "config")
        self.assertEqual(config["source"], "/etc/nginx/nginx.conf")
        self.assertEqual(len(config["mounts"]), 1)

        bind = _run("svc-prx-openresty", "docker_sock", canonical=canonical)[0]
        self.assertEqual(bind["type"], "bind")
        self.assertEqual(bind["source"], "/var/run/docker.sock")

        secret = _run("svc-prx-openresty", "tls_key", canonical=canonical)[0]
        self.assertEqual(secret["type"], "secret")
        self.assertEqual(secret["source"], "/run/secrets/tls.key")
        self.assertEqual(secret["mounts"], [])

        tmpfs = _run("svc-prx-openresty", "scratch", canonical=canonical)[0]
        self.assertEqual(tmpfs["type"], "tmpfs")
        self.assertEqual(tmpfs["source"], "")

        shared = _run("web-app-mediawiki", "shared", canonical=canonical)[0]
        self.assertEqual(shared["name"], "mediawiki_shared")
        self.assertEqual(shared["semantic_name"], "shared")
        self.assertIs(shared["nfs"], True)

    def test_raises_when_name_not_found(self):
        canonical = {
            "data": {"type": "volume", "name": "mattermost_data"},
        }
        with self.assertRaises(AnsibleError):
            _run("web-app-mattermost", "missing", canonical=canonical)

    def test_raises_when_role_has_no_canonical_meta(self):
        with self.assertRaises(AnsibleError):
            _run("web-app-no-such-role", "data", canonical={})

    def test_missing_terms_raise(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], variables={})
        with self.assertRaises(AnsibleError):
            LookupModule().run(["web-app-mattermost", "data", "extra"], variables={})

    def test_one_term_returns_full_canonical_dict(self):
        canonical = {
            "data": {"type": "volume", "name": "mm_data"},
            "config": {"type": "bind", "source": "/etc/foo"},
        }
        with (
            patch(
                "plugins.lookup.volume.get_canonical_volumes",
                return_value=canonical,
            ),
            patch("plugins.lookup.volume.get_application_defaults"),
        ):
            result = LookupModule().run(["web-app-mattermost"], variables={})
        self.assertEqual(result, [canonical])

    def test_one_term_returns_empty_dict_when_no_meta(self):
        with (
            patch(
                "plugins.lookup.volume.get_canonical_volumes",
                return_value={},
            ),
            patch("plugins.lookup.volume.get_application_defaults"),
        ):
            result = LookupModule().run(["web-app-no-meta"], variables={})
        self.assertEqual(result, [{}])

    def test_empty_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            _run("", "data", canonical={"data": {}})

    def test_empty_name_raises(self):
        with self.assertRaises(AnsibleError):
            _run("web-app-mattermost", "", canonical={"data": {}})

    def test_forces_defaults_build_on_registry_miss(self):
        # Empty on the first read (lookup runs before any consumer built the
        # role); populated after the forced build — the nfs_prep/ollama case.
        populated = {"data": {"type": "volume"}}
        with (
            patch(
                "plugins.lookup.volume.get_canonical_volumes",
                side_effect=[{}, populated],
            ) as gcv,
            patch(
                "plugins.lookup.volume.get_application_defaults",
            ) as gad,
        ):
            result = LookupModule().run(["svc-ai-ollama"], variables={})
        self.assertEqual(result, [populated])
        gad.assert_called_once()
        self.assertEqual(gcv.call_count, 2)

    def test_populated_registry_skips_build(self):
        # Already populated: no forced build, no wasted defaults deepcopy.
        with (
            patch(
                "plugins.lookup.volume.get_canonical_volumes",
                return_value={"data": {"type": "volume"}},
            ),
            patch(
                "plugins.lookup.volume.get_application_defaults",
            ) as gad,
        ):
            LookupModule().run(["web-app-mattermost"], variables={})
        gad.assert_not_called()


if __name__ == "__main__":
    unittest.main()
