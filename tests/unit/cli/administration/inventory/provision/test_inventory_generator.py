import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.inventory.provision.inventory_generator import (
    generate_dynamic_inventory,
)


class TestInventoryGenerator(unittest.TestCase):
    def test_generate_dynamic_inventory_runs_module_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tmp_inventory = tmp / "_tmp.yml"
            tmp_inventory.write_text("all: {}\n", encoding="utf-8")

            fake_loaded = {"all": {"children": {}}}

            with (
                patch(
                    "cli.administration.inventory.provision.inventory_generator.run_subprocess"
                ) as rs,
                patch(
                    "cli.administration.inventory.provision.inventory_generator.load_yaml",
                    return_value=fake_loaded,
                ) as ly,
            ):
                data = generate_dynamic_inventory(
                    host="localhost",
                    roles_dir=tmp / "roles",
                    categories_file=tmp / "categories.yml",
                    tmp_inventory=tmp_inventory,
                    project_root=tmp / "repo",
                    env={"PYTHONPATH": "x"},
                )

            self.assertEqual(data, fake_loaded)
            rs.assert_called()
            cmd = rs.call_args[0][0]
            self.assertIn("-m", cmd)
            self.assertIn("cli.administration.inventory.devices", cmd)
            ly.assert_called_once()
            self.assertFalse(tmp_inventory.exists())
