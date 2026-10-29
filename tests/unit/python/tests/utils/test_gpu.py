from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests.utils import gpu


class TestGpuTestsEnabled(unittest.TestCase):
    @patch.dict(os.environ, {gpu.FLAG: "true"}, clear=False)
    def test_true_runs_them(self) -> None:
        self.assertTrue(gpu.gpu_tests_enabled())

    @patch.dict(os.environ, {gpu.FLAG: "false"}, clear=False)
    def test_false_skips_them_even_on_a_gpu_host(self) -> None:
        with patch.object(gpu, "accelerated", return_value=True):
            self.assertFalse(gpu.gpu_tests_enabled())

    @patch.dict(os.environ, {gpu.FLAG: "yes"}, clear=False)
    def test_any_other_value_fails_loudly(self) -> None:
        with self.assertRaises(ValueError):
            gpu.gpu_tests_enabled()

    @patch.dict(os.environ, {gpu.FLAG: ""}, clear=False)
    def test_an_unloaded_env_falls_back_to_the_gpu_detection(self) -> None:
        with patch.object(gpu, "accelerated", return_value=True):
            self.assertTrue(gpu.gpu_tests_enabled())
        with patch.object(gpu, "accelerated", return_value=False):
            self.assertFalse(gpu.gpu_tests_enabled())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
