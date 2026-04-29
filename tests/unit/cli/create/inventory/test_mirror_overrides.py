# tests/unit/cli/create/inventory/test_mirror_overrides.py
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ruamel.yaml import YAML

from cli.create.inventory.mirror_overrides import apply_mirror_overrides


class TestApplyMirrorOverrides(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

        self.yaml_rt = YAML(typ="rt")
        self.yaml_rt.preserve_quotes = True

        self.host_vars = self.root / "host_vars.yml"
        self.mirrors = self.root / "mirrors.yml"

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            self.yaml_rt.dump(data, f)

    def _read_yaml(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            doc = self.yaml_rt.load(f)
        if doc is None:
            return {}
        return dict(doc)

    def test_default_policy_manual_override_wins(self) -> None:
        """
        Default policy is 'if_missing' -> if host_vars already has image/version,
        mirror must NOT overwrite them in applications.
        """
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "docker.io/library/nextcloud",
                            "version": "30.0.0",
                        }
                    }
                }
            }
        }

        mirrors_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            "version": "30.0.1",
                        }
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]

        # applications: manual values win
        self.assertEqual(svc["image"], "docker.io/library/nextcloud")
        self.assertEqual(svc["version"], "30.0.0")

        self.assertNotIn("images_overrides", out)

    def test_force_policy_overwrites_image_and_version(self) -> None:
        """
        mirror_policy: force -> mirror always overwrites image/version.
        """
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "mirror_policy": "force",
                            "image": "docker.io/library/nextcloud",
                            "version": "30.0.0",
                            "env": {"FOO": "bar"},
                            "replicas": 2,
                        }
                    }
                }
            }
        }

        mirrors_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            "version": "30.0.1",
                        }
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]

        self.assertEqual(svc["image"], "ghcr.io/acme/mirror/nextcloud")
        self.assertEqual(svc["version"], "30.0.1")
        self.assertEqual(svc["env"], {"FOO": "bar"})
        self.assertEqual(svc["replicas"], 2)
        self.assertEqual(svc["mirror_policy"], "force")

        self.assertNotIn("images_overrides", out)

    def test_skip_policy_never_overwrites(self) -> None:
        """
        mirror_policy: skip -> mirror never touches applications service.
        """
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "mirror_policy": "skip",
                            "image": "docker.io/library/nextcloud",
                            "version": "30.0.0",
                        }
                    }
                }
            }
        }

        mirrors_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            "version": "30.0.1",
                        }
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]

        self.assertEqual(svc["image"], "docker.io/library/nextcloud")
        self.assertEqual(svc["version"], "30.0.0")
        self.assertEqual(svc["mirror_policy"], "skip")

        self.assertNotIn("images_overrides", out)

    def test_if_missing_fills_only_missing_keys(self) -> None:
        """
        Default policy: if_missing -> fill missing image/version only in applications.
        """
        host_vars_data = {
            "applications": {
                "svc-ai-ollama": {
                    "services": {
                        "ollama": {
                            "env": {"A": "b"},
                        }
                    }
                },
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "docker.io/library/nextcloud",
                        }
                    }
                },
            }
        }

        mirrors_data = {
            "applications": {
                "svc-ai-ollama": {
                    "services": {
                        "ollama": {
                            "image": "ghcr.io/acme/mirror/ollama",
                            "version": "1.2.3",
                        }
                    }
                },
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            "version": "30.0.1",
                        }
                    }
                },
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)

        svc_ollama = out["applications"]["svc-ai-ollama"]["services"]["ollama"]
        self.assertEqual(svc_ollama["image"], "ghcr.io/acme/mirror/ollama")
        self.assertEqual(svc_ollama["version"], "1.2.3")
        self.assertEqual(svc_ollama["env"], {"A": "b"})

        svc_nc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc_nc["image"], "docker.io/library/nextcloud")
        self.assertEqual(svc_nc["version"], "30.0.1")

        self.assertNotIn("images_overrides", out)

    def test_creates_missing_app_and_service(self) -> None:
        """
        If host_vars lacks the app/service, mirror creates it.
        """
        host_vars_data = {"TLS_ENABLED": True}

        mirrors_data = {
            "applications": {
                "svc-db-postgres": {
                    "services": {
                        "postgres": {
                            "image": "ghcr.io/acme/mirror/postgres",
                            "version": "16",
                        }
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)

        self.assertTrue(out["TLS_ENABLED"])
        svc = out["applications"]["svc-db-postgres"]["services"]["postgres"]
        self.assertEqual(svc["image"], "ghcr.io/acme/mirror/postgres")
        self.assertEqual(svc["version"], "16")

        self.assertNotIn("images_overrides", out)

    def test_ignores_entries_without_image_or_version(self) -> None:
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {"app": {"image": "x", "version": "1"}}
                }
            }
        }

        mirrors_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            # missing version -> should be ignored
                        }
                    }
                },
                "web-app-wordpress": {
                    "services": {
                        "wp": {
                            # missing image -> ignored
                            "version": "6.4",
                        }
                    }
                },
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)

        svc_nc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc_nc["image"], "x")
        self.assertEqual(svc_nc["version"], "1")

        self.assertNotIn("web-app-wordpress", out.get("applications", {}))

    def test_noop_when_mirrors_has_no_applications_or_images(self) -> None:
        host_vars_data = {
            "applications": {"a": {"services": {"s": {"image": "i", "version": "v"}}}}
        }
        mirrors_data = {"not_applications_or_images": {"x": 1}}

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["a"]["services"]["s"]
        self.assertEqual(svc["image"], "i")
        self.assertEqual(svc["version"], "v")

    def test_raises_system_exit_if_mirrors_file_missing(self) -> None:
        self._write_yaml(self.host_vars, {"applications": {}})

        missing = self.root / "does-not-exist.yml"
        with self.assertRaises(SystemExit):
            apply_mirror_overrides(self.host_vars, missing)

    def test_treats_empty_strings_as_missing_for_if_missing(self) -> None:
        """
        If host_vars has empty/whitespace image/version, treat them as missing and fill.
        """
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "   ",
                            "version": "",
                            "env": {"FOO": "bar"},
                        }
                    }
                }
            }
        }
        mirrors_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "ghcr.io/acme/mirror/nextcloud",
                            "version": "30.0.1",
                        }
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc["image"], "ghcr.io/acme/mirror/nextcloud")
        self.assertEqual(svc["version"], "30.0.1")
        self.assertEqual(svc["env"], {"FOO": "bar"})

        self.assertNotIn("images_overrides", out)

    def test_images_entries_merge_into_images_overrides_only(self) -> None:
        host_vars_data = {
            "applications": {
                "web-app-nextcloud": {
                    "services": {
                        "app": {
                            "image": "docker.io/library/nextcloud",
                            "version": "30.0.0",
                        }
                    }
                }
            }
        }
        mirrors_data = {
            "images": {
                "test-e2e-playwright": {
                    "playwright": {
                        "image": "ghcr.io/acme/mirror/mcr.microsoft.com/playwright",
                        "version": "v1.58.2-noble",
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        svc = out["applications"]["web-app-nextcloud"]["services"]["app"]
        self.assertEqual(svc["image"], "docker.io/library/nextcloud")
        self.assertEqual(svc["version"], "30.0.0")

        img = out["images_overrides"]["test-e2e-playwright"]["playwright"]
        self.assertEqual(
            img["image"], "ghcr.io/acme/mirror/mcr.microsoft.com/playwright"
        )
        self.assertEqual(img["version"], "v1.58.2-noble")

    def test_images_entries_fill_only_missing_override_fields(self) -> None:
        host_vars_data = {
            "images_overrides": {
                "test-e2e-playwright": {
                    "playwright": {
                        "image": "ghcr.io/custom/playwright",
                    }
                }
            }
        }
        mirrors_data = {
            "images": {
                "test-e2e-playwright": {
                    "playwright": {
                        "image": "ghcr.io/acme/mirror/mcr.microsoft.com/playwright",
                        "version": "v1.58.2-noble",
                    }
                }
            }
        }

        self._write_yaml(self.host_vars, host_vars_data)
        self._write_yaml(self.mirrors, mirrors_data)

        apply_mirror_overrides(self.host_vars, self.mirrors)

        out = self._read_yaml(self.host_vars)
        img = out["images_overrides"]["test-e2e-playwright"]["playwright"]
        self.assertEqual(img["image"], "ghcr.io/custom/playwright")
        self.assertEqual(img["version"], "v1.58.2-noble")


if __name__ == "__main__":
    unittest.main()
