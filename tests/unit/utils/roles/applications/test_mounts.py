from __future__ import annotations

import unittest

from utils.roles.applications.mounts import (
    VolumesSchemaError,
    content_hash,
    mount_default_read_only,
    mounts_for_service,
    normalize_volumes_meta,
    validate_volumes_meta,
)


class TestNormalizeVolumesMeta(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(normalize_volumes_meta(None), {})

    def test_canonical_dict_shape(self) -> None:
        canonical = {
            "data": {
                "type": "volume",
                "name": "matrix_synapse_data",
                "mounts": [{"service": "synapse", "target": "/data"}],
            },
            "config": {
                "type": "bind",
                "source": "/etc/synapse/config",
                "read_only": True,
                "mounts": [{"service": "synapse", "target": "/etc/synapse/config"}],
            },
        }
        result = normalize_volumes_meta(canonical)
        self.assertEqual(set(result.keys()), {"data", "config"})
        self.assertEqual(result["data"]["type"], "volume")
        self.assertEqual(result["data"]["name"], "matrix_synapse_data")
        self.assertEqual(result["config"]["type"], "bind")
        self.assertEqual(result["config"]["source"], "/etc/synapse/config")

    def test_default_type_volume(self) -> None:
        result = normalize_volumes_meta({"data": {}})
        self.assertEqual(result["data"]["type"], "volume")

    def test_docker_name_optional(self) -> None:
        result = normalize_volumes_meta({"data": {"type": "volume"}})
        self.assertNotIn("name", result["data"])

    def test_list_shape_rejected(self) -> None:
        with self.assertRaises(VolumesSchemaError) as ctx:
            normalize_volumes_meta([{"name": "x", "type": "volume"}])
        self.assertIn("list-shape", str(ctx.exception))

    def test_invalid_root_shape_raises(self) -> None:
        with self.assertRaises(VolumesSchemaError):
            normalize_volumes_meta("foo")

    def test_entry_must_be_dict(self) -> None:
        with self.assertRaises(VolumesSchemaError):
            normalize_volumes_meta({"data": "not-a-dict"})

    def test_empty_key_rejected(self) -> None:
        with self.assertRaises(VolumesSchemaError):
            normalize_volumes_meta({"": {"type": "volume"}})


class TestValidateVolumesMeta(unittest.TestCase):
    def test_clean_dict_passes(self) -> None:
        result = validate_volumes_meta(
            {"data": {"type": "volume", "name": "myapp_data"}},
            "test-role",
        )
        self.assertEqual(result, [])

    def test_clean_canonical_passes(self) -> None:
        result = validate_volumes_meta(
            {
                "cfg": {
                    "type": "config",
                    "source": "/etc/foo.yml",
                    "mode": "0440",
                },
                "data": {"type": "volume", "nfs": True, "read_only": False},
            },
            "test-role",
        )
        self.assertEqual(result, [])

    def test_unknown_type_flagged(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "weird"}},
            "r",
        )
        self.assertTrue(any("'type' must be one of" in v for v in violations))

    def test_bind_requires_source(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "bind"}},
            "r",
        )
        self.assertTrue(any("requires a non-empty 'source'" in v for v in violations))

    def test_volume_forbids_source(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "volume", "source": "/foo"}},
            "r",
        )
        self.assertTrue(any("MUST NOT carry 'source'" in v for v in violations))

    def test_mode_only_on_config_secret(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "volume", "mode": "0440"}},
            "r",
        )
        self.assertTrue(any("'mode' is only valid for" in v for v in violations))

    def test_mode_must_be_octal_string(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "config", "source": "/a", "mode": "440"}},
            "r",
        )
        self.assertTrue(any("octal string" in v for v in violations))

    def test_read_only_only_on_bind_volume(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "config", "source": "/a", "read_only": True}},
            "r",
        )
        self.assertTrue(any("'read_only' is only valid for" in v for v in violations))

    def test_nfs_dict_form_accepted(self) -> None:
        result = validate_volumes_meta(
            {
                "data": {
                    "type": "volume",
                    "nfs": {"uid": 33, "gid": 33, "mode": "0755"},
                }
            },
            "r",
        )
        self.assertEqual(result, [])

    def test_swarm_safe_only_on_bind(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "volume", "swarm_safe": False}},
            "r",
        )
        self.assertTrue(any("'swarm_safe' opt-out is only" in v for v in violations))

    def test_mount_requires_service_and_target(self) -> None:
        violations = validate_volumes_meta(
            {
                "x": {
                    "type": "config",
                    "source": "/a",
                    "mounts": [{"target": "/etc/x"}],
                }
            },
            "r",
        )
        self.assertTrue(any("'service' is required" in v for v in violations))

    def test_docker_name_must_be_non_empty_string(self) -> None:
        violations = validate_volumes_meta(
            {"x": {"type": "volume", "name": ""}},
            "r",
        )
        self.assertTrue(
            any(
                "'name' (container volume name) must be a non-empty string" in v
                for v in violations
            )
        )

    def test_list_shape_returns_violation(self) -> None:
        violations = validate_volumes_meta(
            [{"name": "x", "type": "volume"}],
            "r",
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("list-shape", violations[0])


class TestContentHash(unittest.TestCase):
    def test_stable_for_same_input(self) -> None:
        self.assertEqual(content_hash("foo"), content_hash("foo"))

    def test_differs_for_different_input(self) -> None:
        self.assertNotEqual(content_hash("foo"), content_hash("bar"))

    def test_default_length_8(self) -> None:
        self.assertEqual(len(content_hash("anything")), 8)


class TestDefaults(unittest.TestCase):
    def test_config_default_read_only(self) -> None:
        self.assertTrue(mount_default_read_only({"type": "config"}))

    def test_secret_default_read_only(self) -> None:
        self.assertTrue(mount_default_read_only({"type": "secret"}))

    def test_bind_default_rw(self) -> None:
        self.assertFalse(mount_default_read_only({"type": "bind"}))

    def test_volume_default_rw(self) -> None:
        self.assertFalse(mount_default_read_only({"type": "volume"}))


class TestMountsForService(unittest.TestCase):
    def test_filters_by_service(self) -> None:
        entry = {
            "mounts": [
                {"service": "a", "target": "/x"},
                {"service": "b", "target": "/y"},
                {"service": "a", "target": "/z"},
            ]
        }
        result = list(mounts_for_service(entry, "a"))
        self.assertEqual(len(result), 2)
        targets = sorted(m["target"] for m in result)
        self.assertEqual(targets, ["/x", "/z"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
