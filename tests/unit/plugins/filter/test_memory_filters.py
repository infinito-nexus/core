import unittest
from unittest.mock import patch

import importlib

memory_filters = importlib.import_module("plugins.filter.memory_filters")


class TestMemoryFilters(unittest.TestCase):
    def setUp(self):
        # Dummy applications dict – content does not matter because get is mocked
        self.apps = {"whatever": True}
        self.app_id = "web-app-confluence"  # entity_name will be mocked

    # -----------------------------
    # Helpers
    # -----------------------------
    def _with_conf(self, mem_limit: str, mem_res: str):
        """
        Patch get/get_entity_name so that mem_limit and mem_reservation
        can be controlled in tests.
        """
        patches = [
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ),
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    mem_limit
                    if key.endswith(".mem_limit")
                    else mem_res
                    if key.endswith(".mem_reservation")
                    else None
                ),
            ),
        ]
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])
        return mocks

    # -----------------------------
    # Tests: jvm_max_mb / jvm_min_mb sizing
    # -----------------------------
    def test_sizing_8g_limit_6g_reservation(self):
        # mem_limit = 8g
        # candidates:
        #   70%: (8 * 1024) * 7 // 10 = 5734
        #   limit - 1024: 8192 - 1024 = 7168
        #   cap: 12288
        # -> Xmx = 5734
        # Xms = min(5734 // 2 = 2867, 6144, 5734) = 2867
        self._with_conf("8g", "6g")
        xmx = memory_filters.jvm_max_mb(self.apps, self.app_id)
        xms = memory_filters.jvm_min_mb(self.apps, self.app_id)
        self.assertEqual(xmx, 5734)
        self.assertEqual(xms, 2867)

    def test_sizing_6g_limit_4g_reservation(self):
        # mem_limit = 6g
        # 70%: (6144 * 7) // 10 = 4300
        # limit - 1024: 6144 - 1024 = 5120
        # cap: 12288
        # -> Xmx = 4300
        # Xms = min(4300 // 2 = 2150, 4096, 4300) = 2150
        self._with_conf("6g", "4g")
        xmx = memory_filters.jvm_max_mb(self.apps, self.app_id)
        xms = memory_filters.jvm_min_mb(self.apps, self.app_id)
        self.assertEqual(xmx, 4300)
        self.assertEqual(xms, 2150)

    def test_sizing_16g_limit_12g_reservation_cap_12288(self):
        # mem_limit = 16g
        # 70%: (16384 * 7) // 10 = 11468
        # limit - 1024: 16384 - 1024 = 15360
        # cap: 12288
        # -> Xmx = 11468
        # Xms = min(11468 // 2 = 5734, 12288, 11468) = 5734
        self._with_conf("16g", "12g")
        xmx = memory_filters.jvm_max_mb(self.apps, self.app_id)
        xms = memory_filters.jvm_min_mb(self.apps, self.app_id)
        self.assertEqual(xmx, 11468)
        self.assertEqual(xms, 5734)

    def test_floor_small_limit_results_in_min_1024(self):
        # mem_limit = 1g
        # 70%: ~716 MB, limit - 1024 = 0, cap: 12288
        # -> min candidates = 0 => floored to 1024 MB
        self._with_conf("1g", "512m")
        xmx = memory_filters.jvm_max_mb(self.apps, self.app_id)
        self.assertEqual(xmx, 1024)

    def test_floor_small_reservation_results_in_min_512(self):
        # mem_limit is large enough, but reservation is tiny -> floored to 512
        self._with_conf("4g", "128m")
        xms = memory_filters.jvm_min_mb(self.apps, self.app_id)
        self.assertEqual(xms, 512)

    # -----------------------------
    # Tests: JVM failure cases / validation
    # -----------------------------
    def test_invalid_unit_raises(self):
        with (
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ),
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    "8Q" if key.endswith(".mem_limit") else "4g"
                ),
            ),
        ):
            with self.assertRaises(memory_filters.AnsibleFilterError):
                memory_filters.jvm_max_mb(self.apps, self.app_id)

    def test_zero_limit_raises(self):
        with (
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ),
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    "0" if key.endswith(".mem_limit") else "4g"
                ),
            ),
        ):
            with self.assertRaises(memory_filters.AnsibleFilterError):
                memory_filters.jvm_max_mb(self.apps, self.app_id)

    def test_zero_reservation_raises(self):
        with (
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ),
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    "8g" if key.endswith(".mem_limit") else "0"
                ),
            ),
        ):
            with self.assertRaises(memory_filters.AnsibleFilterError):
                memory_filters.jvm_min_mb(self.apps, self.app_id)

    def test_entity_name_is_derived_not_passed(self):
        """
        Ensure get_entity_name() is called internally and the app_id is not
        passed around manually from the template.
        """
        with (
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ) as mock_entity,
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    "8g" if key.endswith(".mem_limit") else "6g"
                ),
            ),
        ):
            xmx = memory_filters.jvm_max_mb(self.apps, self.app_id)
            xms = memory_filters.jvm_min_mb(self.apps, self.app_id)
            self.assertGreater(xmx, 0)
            self.assertGreater(xms, 0)
            self.assertEqual(mock_entity.call_count, 3)
            for call in mock_entity.call_args_list:
                self.assertEqual(call.args[0], self.app_id)

    # -----------------------------
    # Tests: redis_maxmemory_mb
    # -----------------------------
    def test_redis_maxmemory_default_factor_uses_80_percent_of_limit(self):
        # mem_limit = 1g → 1024 MB
        # factor = 0.8 → int(1024 * 0.8) = 819
        self._with_conf("1g", "512m")
        maxmem = memory_filters.redis_maxmemory_mb(self.apps, self.app_id)
        self.assertEqual(maxmem, 819)

    def test_redis_maxmemory_custom_factor_and_min_mb(self):
        # mem_limit = 1g → 1024 MB
        # factor = 0.5 → 512 MB
        # min_mb = 128 → result stays 512
        self._with_conf("1g", "512m")
        maxmem = memory_filters.redis_maxmemory_mb(
            self.apps,
            self.app_id,
            factor=0.5,
            min_mb=128,
        )
        self.assertEqual(maxmem, 512)

    def test_redis_maxmemory_honors_minimum_floor(self):
        # mem_limit = 32m → 32 MB
        # factor = 0.8 → int(32 * 0.8) = 25 < min_mb(64)
        # → result = 64
        self._with_conf("32m", "16m")
        maxmem = memory_filters.redis_maxmemory_mb(self.apps, self.app_id)
        self.assertEqual(maxmem, 64)

    def test_redis_maxmemory_zero_limit_raises(self):
        # mem_limit = 0 → must raise AnsibleFilterError
        self._with_conf("0", "512m")
        with self.assertRaises(memory_filters.AnsibleFilterError):
            memory_filters.redis_maxmemory_mb(self.apps, self.app_id)

    def test_redis_maxmemory_invalid_unit_raises(self):
        # mem_limit = "8Q" → invalid unit → must raise
        self._with_conf("8Q", "512m")
        with self.assertRaises(memory_filters.AnsibleFilterError):
            memory_filters.redis_maxmemory_mb(self.apps, self.app_id)

    def test_redis_maxmemory_does_not_call_get_entity_name(self):
        """
        Ensure redis_maxmemory_mb does NOT rely on entity name resolution
        (it should always use the hard-coded 'redis' service name).
        """
        patches = [
            patch("plugins.filter.memory_filters.get_entity_name"),
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=lambda apps, app_id, key, required=True, **kwargs: (
                    "4g" if key.endswith(".mem_limit") else "2g"
                ),
            ),
        ]
        mocks = [p.start() for p in patches]
        self.addCleanup(lambda: [p.stop() for p in patches])

        entity_mock = mocks[0]

        maxmem = memory_filters.redis_maxmemory_mb(self.apps, self.app_id)
        # 4g → 4096 MB, factor 0.8 → 3276
        self.assertEqual(maxmem, 3276)
        entity_mock.assert_not_called()

    def test_redis_maxmemory_uses_default_when_mem_limit_missing(self):
        """
        When services.redis.mem_limit is not configured, the filter
        should fall back to its internal default (256m).
        """

        def fake_get(apps, app_id, key, required=True, **kwargs):
            # Simulate missing mem_limit: return the provided default
            if key.endswith(".mem_limit"):
                return kwargs.get("default")
            return None

        with (
            patch(
                "plugins.filter.memory_filters.get",
                side_effect=fake_get,
            ),
            patch(
                "plugins.filter.memory_filters.get_entity_name",
                return_value="confluence",
            ),
        ):
            maxmem = memory_filters.redis_maxmemory_mb(self.apps, self.app_id)

        # default_mb = 256 → factor 0.8 → floor(256 * 0.8) = 204
        self.assertEqual(maxmem, 204)


if __name__ == "__main__":
    unittest.main()
