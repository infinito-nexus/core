from __future__ import annotations

import unittest

import yaml

from plugins.filter.container_volumes import container_volumes


def _apps(volumes_meta):
    return {"my-app": {"volumes": volumes_meta}}


def _parse(out: str) -> dict:
    if not out:
        return {}
    parsed = yaml.safe_load(out)  # nocheck: direct-yaml  plugin output string
    return parsed or {}


class TestContainerVolumesShortFormBind(unittest.TestCase):
    def test_canonical_bind_renders_short_form(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "mounts": [{"service": "app", "target": "/app/foo.conf"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(data, {"volumes": ["/etc/foo.conf:/app/foo.conf"]})

    def test_bind_read_only_emits_ro_suffix(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "read_only": True,
                "mounts": [{"service": "app", "target": "/app/foo.conf"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(data, {"volumes": ["/etc/foo.conf:/app/foo.conf:ro"]})

    def test_per_mount_read_only_overrides_volume_level(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "read_only": True,
                "mounts": [
                    {"service": "app", "target": "/app/foo.conf", "read_only": False}
                ],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(data, {"volumes": ["/etc/foo.conf:/app/foo.conf"]})


class TestContainerVolumesNamed(unittest.TestCase):
    def test_canonical_volume_with_mount_uses_semantic_name(self) -> None:
        """Per-service mount references the SEMANTIC name (YAML key), so
        the top-level `volumes:` key from compose_volumes (also keyed by
        semantic name) resolves the mount. Using the docker name here would
        produce a compose project referencing an undefined top-level key
        and `docker compose up` would fail with 'undefined volume'."""
        meta = {
            "data": {
                "type": "volume",
                "name": "myapp_data",
                "mounts": [{"service": "app", "target": "/data"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(data, {"volumes": ["data:/data"]})


class TestContainerVolumesConfigSecret(unittest.TestCase):
    def test_config_renders_per_service_reference(self) -> None:
        meta = {
            "appcfg": {
                "type": "config",
                "source": "/opt/render/foo.yaml",
                "mode": "0440",
                "mounts": [{"service": "app", "target": "/app/foo.yaml"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(
            data,
            {
                "configs": [
                    {"source": "appcfg", "target": "/app/foo.yaml", "mode": 0o440}
                ]
            },
        )

    def test_secret_renders_per_service_reference(self) -> None:
        meta = {
            "tlskey": {
                "type": "secret",
                "source": "/etc/ssl/key.pem",
                "mode": "0400",
                "mounts": [{"service": "app", "target": "/run/secrets/key"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(
            data,
            {
                "secrets": [
                    {"source": "tlskey", "target": "/run/secrets/key", "mode": 0o400}
                ]
            },
        )


class TestContainerVolumesTmpfs(unittest.TestCase):
    def test_tmpfs_renders_long_form_dict(self) -> None:
        meta = {
            "scratch": {
                "type": "tmpfs",
                "mounts": [{"service": "app", "target": "/scratch", "size": "64m"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        data = _parse(out)
        self.assertEqual(
            data,
            {
                "volumes": [
                    {
                        "type": "tmpfs",
                        "target": "/scratch",
                        "tmpfs": {"size": "64m"},
                    }
                ]
            },
        )


class TestContainerVolumesServiceFilter(unittest.TestCase):
    def test_only_emits_mounts_for_requested_service(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "mounts": [
                    {"service": "a", "target": "/etc/foo.conf"},
                    {"service": "b", "target": "/opt/foo.conf"},
                ],
            }
        }
        out_a = container_volumes(_apps(meta), "my-app", "a")
        out_b = container_volumes(_apps(meta), "my-app", "b")
        self.assertEqual(_parse(out_a), {"volumes": ["/etc/foo.conf:/etc/foo.conf"]})
        self.assertEqual(_parse(out_b), {"volumes": ["/etc/foo.conf:/opt/foo.conf"]})


class TestContainerVolumesWhen(unittest.TestCase):
    def test_when_false_filters_out(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "mounts": [
                    {"service": "app", "target": "/etc/foo.conf", "when": False},
                ],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        self.assertEqual(out, "")

    def test_when_true_keeps(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "mounts": [
                    {"service": "app", "target": "/etc/foo.conf", "when": True},
                ],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        self.assertEqual(_parse(out), {"volumes": ["/etc/foo.conf:/etc/foo.conf"]})

    def test_when_string_falsy_filters_out(self) -> None:
        meta = {
            "cfg": {
                "type": "bind",
                "source": "/etc/foo.conf",
                "mounts": [
                    {"service": "app", "target": "/etc/foo.conf", "when": "false"},
                ],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        self.assertEqual(out, "")

    def test_when_jinja_evaluated_via_render_callable(self) -> None:
        """Callers (lookup plugin) pass a templar-backed render callable;
        verifies the contract: a Jinja expression resolves to a usable
        truthy/falsy value through that callable."""
        rendered_calls: list[str] = []

        def render_jinja(expr: str) -> str:
            rendered_calls.append(expr)
            return "true" if "FLAG" in expr else "false"

        meta = {
            "cfg": {
                "type": "bind",
                "source": "/a",
                "mounts": [
                    {
                        "service": "app",
                        "target": "/a",
                        "when": "{{ FLAG | bool }}",
                    },
                    {
                        "service": "app",
                        "target": "/b",
                        "when": "{{ OTHER | bool }}",
                    },
                ],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app", render_jinja=render_jinja)
        self.assertEqual(_parse(out), {"volumes": ["/a:/a"]})
        self.assertEqual(rendered_calls, ["{{ FLAG | bool }}", "{{ OTHER | bool }}"])


class TestContainerVolumesExtras(unittest.TestCase):
    def test_extra_volumes_appended(self) -> None:
        meta = {
            "data": {
                "type": "volume",
                "name": "myapp_data",
                "mounts": [{"service": "app", "target": "/data"}],
            }
        }
        out = container_volumes(
            _apps(meta), "my-app", "app", extra_volumes=["/host:/extra:ro"]
        )
        self.assertEqual(
            _parse(out),
            {"volumes": ["data:/data", "/host:/extra:ro"]},
        )

    def test_extra_configs_and_secrets(self) -> None:
        out = container_volumes(
            _apps(None),
            "my-app",
            "app",
            extra_configs=[{"source": "cfg", "target": "/etc/x"}],
            extra_secrets=[{"source": "s", "target": "/run/secrets/y"}],
        )
        data = _parse(out)
        self.assertEqual(
            data,
            {
                "configs": [{"source": "cfg", "target": "/etc/x"}],
                "secrets": [{"source": "s", "target": "/run/secrets/y"}],
            },
        )


class TestContainerVolumesOutputShape(unittest.TestCase):
    def test_empty_meta_returns_empty_string(self) -> None:
        out = container_volumes(_apps(None), "my-app", "app")
        self.assertEqual(out, "")

    def test_output_starts_at_column_0(self) -> None:
        meta = {
            "data": {
                "type": "volume",
                "name": "x",
                "mounts": [{"service": "app", "target": "/data"}],
            }
        }
        out = container_volumes(_apps(meta), "my-app", "app")
        first_line = out.splitlines()[0]
        self.assertFalse(first_line.startswith(" "))
        self.assertEqual(first_line, "volumes:")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
