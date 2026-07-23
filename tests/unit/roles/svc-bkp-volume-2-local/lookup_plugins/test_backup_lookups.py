import importlib.util
import unittest
from pathlib import Path
from unittest import mock

from ansible.errors import AnsibleError

ROLE_LOOKUPS = (
    Path(__file__).parent / "../../../../../roles/svc-bkp-volume-2-local/lookup_plugins"
).resolve()


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, str(ROLE_LOOKUPS / f"{name}.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


db_mod = _load("backup_database_containers")
proj_mod = _load("backup_hard_restart_projects")
img_mod = _load("backup_image")


APPS = {
    "web-app-mastodon": {
        "services": {
            "mastodon": {
                "name": "mastodon",
                "image": "ghcr.io/mastodon/mastodon",
                "version": "v4.6.2",
                "backup": {"no_stop_required": True},
            },
            "redis": {
                "name": "mastodon-redis",
                "backup": {"disabled": True},
            },
        }
    },
    "svc-db-redis": {
        "services": {
            "redis": {
                "name": "redis-central",
                "image": "redis",
                "version": "alpine",
                "backup": {"disabled": True},
            }
        }
    },
    "web-app-mailu": {
        "services": {
            "mailu": {
                "name": "mailu",
                "version": "2024.06",
                "backup": {"project_hard_restart": True},
            },
            "database": {
                "name": "mailu-database",
                "backup": {"database_routine": True},
            },
        }
    },
    "app_no_docker": {"meta": "skip"},
}


def _bare(lm_module, terms):
    lm = lm_module.LookupModule()
    lm._loader = mock.MagicMock()
    lm._templar = mock.MagicMock(available_variables={})
    return lm


class TestBackupDatabaseContainers(unittest.TestCase):
    def test_returns_names_with_database_routine(self):
        lm = _bare(db_mod, [])
        with mock.patch.object(db_mod, "lookup_loader") as ll:
            ll.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [APPS])
            out = lm.run([], variables={})
        self.assertEqual(out, [["mailu-database"]])

    def test_empty_when_none_marked(self):
        lm = _bare(db_mod, [])
        with mock.patch.object(db_mod, "lookup_loader") as ll:
            ll.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [{}])
            out = lm.run([], variables={})
        self.assertEqual(out, [[]])


class TestBackupHardRestartProjects(unittest.TestCase):
    def test_returns_entity_names_with_marker(self):
        lm = _bare(proj_mod, [])
        with mock.patch.object(proj_mod, "lookup_loader") as ll:
            ll.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [APPS])
            out = lm.run([], variables={})
        self.assertEqual(out, [["mailu"]])


def _image_loader(apps, prefix=""):
    def fake_get(name, **_kw):
        m = mock.MagicMock()
        if name == "applications":
            m.run = lambda *_a, **_k: [apps]
        elif name == "image":

            def image_run(terms, variables=None, custom=False, **_k):
                app_id, svc_key = terms
                svc = apps[app_id]["services"][svc_key]
                custom = custom or svc.get("custom") or False
                if isinstance(custom, str):
                    name = f"{custom}_custom"
                elif custom:
                    name = f"{svc.get('image') or svc_key}_custom"
                else:
                    name = svc.get("image") or svc_key
                return [f"{prefix}{name}:{svc['version']}"]

            m.run = image_run
        return m

    return fake_get


class TestBackupImage(unittest.TestCase):
    def test_no_stop_required_compose(self):
        lm = _bare(img_mod, ["no_stop_required"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(APPS)
            out = lm.run(["no_stop_required"], variables={})
        self.assertEqual(out, [["ghcr.io/mastodon/mastodon:v4.6.2"]])

    def test_disabled_skips_imageless_refs(self):
        lm = _bare(img_mod, ["disabled"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(APPS)
            out = lm.run(["disabled"], variables={})
        self.assertEqual(out, [["redis:alpine"]])

    def test_swarm_prefix_flows_through_image_lookup(self):
        prefix = "mgr:5000/"
        lm = _bare(img_mod, ["no_stop_required"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(APPS, prefix=prefix)
            out = lm.run(["no_stop_required"], variables={})
        self.assertEqual(out, [[prefix + "ghcr.io/mastodon/mastodon:v4.6.2"]])

    def test_forwards_custom_for_custom_built_service(self):
        apps = {
            "web-app-mediawiki": {
                "services": {
                    "mediawiki": {
                        "name": "mediawiki",
                        "image": "mediawiki",
                        "version": "1.46",
                        "custom": True,
                        "backup": {"no_stop_required": True},
                    }
                }
            }
        }
        lm = _bare(img_mod, ["no_stop_required"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(apps, prefix="mgr:5000/")
            out = lm.run(["no_stop_required"], variables={})
        self.assertEqual(out, [["mgr:5000/mediawiki_custom:1.46"]])

    def test_forwards_string_custom_for_distinct_custom_image(self):
        apps = {
            "web-app-nextcloud": {
                "services": {
                    "whiteboard": {
                        "name": "nextcloud-whiteboard",
                        "image": "ghcr.io/nextcloud-releases/whiteboard",
                        "version": "v1.5.9",
                        "custom": "nextcloud-whiteboard",
                        "backup": {"no_stop_required": True},
                    }
                }
            }
        }
        lm = _bare(img_mod, ["no_stop_required"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(apps, prefix="mgr:5000/")
            out = lm.run(["no_stop_required"], variables={})
        self.assertEqual(out, [["mgr:5000/nextcloud-whiteboard_custom:v1.5.9"]])

    def test_includes_custom_service_without_image_field(self):
        apps = {
            "web-app-x": {
                "services": {
                    "x": {
                        "name": "x",
                        "version": "1.0",
                        "custom": True,
                        "backup": {"no_stop_required": True},
                    }
                }
            }
        }
        lm = _bare(img_mod, ["no_stop_required"])
        with mock.patch.object(img_mod, "lookup_loader") as ll:
            ll.get.side_effect = _image_loader(apps)
            out = lm.run(["no_stop_required"], variables={})
        self.assertEqual(out, [["x_custom:1.0"]])

    def test_requires_exactly_one_term(self):
        lm = _bare(img_mod, [])
        with self.assertRaises(AnsibleError):
            lm.run([], variables={})
        with self.assertRaises(AnsibleError):
            lm.run(["a", "b"], variables={})


if __name__ == "__main__":
    unittest.main()
