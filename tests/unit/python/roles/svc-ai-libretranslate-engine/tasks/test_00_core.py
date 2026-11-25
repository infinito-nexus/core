from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

CORE = PROJECT_ROOT / "roles/svc-ai-libretranslate-engine/tasks/00_core.yml"
PRUNE = "🧹 Remove the partial Argos packages of {{ application_id }}"
MKDIR = "📁 Create the node-local model directory of {{ application_id }}"
FLUSH = "🚿 Flush compose handlers for {{ application_id }}"


def _tasks() -> list[dict]:
    """
    Returns:
        The role's core tasks.
    """
    return load_yaml_any(str(CORE), default_if_missing=[])


def _task(name: str) -> dict:
    """
    Args:
        name: the unrendered task name.

    Returns:
        The core task carrying that name.
    """
    return next(task for task in _tasks() if task.get("name") == name)


def _argv(models_dir: Path) -> list[str]:
    """
    Args:
        models_dir: the directory the prune task points at.

    Returns:
        The prune task's argv, rendered.
    """
    templar = Templar(
        loader=DataLoader(),
        variables={"LIBRETRANSLATE_ENGINE_MODELS_DIR": str(models_dir)},
    )
    return [
        str(templar.template(_trust_as_template(str(part))))
        for part in _task(PRUNE)["ansible.builtin.command"]["argv"]
    ]


class TestPrunePartialPackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.scratch = tempfile.TemporaryDirectory()
        root = Path(cls.scratch.name)
        cls.models = root / "models"
        cls.outside = root / "outside"
        cls.partial = cls.models / "translate-de_en-1_3"
        cls.complete = cls.models / "translate-en_de-1_3"
        cls.link = cls.models / "translate-linked-1_0"
        cls.loose_file = cls.models / "README"
        (cls.partial / "model").mkdir(parents=True)
        (cls.partial / "model" / "model.bin").write_bytes(b"half")
        cls.complete.mkdir()
        (cls.complete / "metadata.json").write_text("{}")
        cls.outside.mkdir()
        (cls.outside / "data").write_text("kept")
        cls.link.symlink_to(cls.outside, target_is_directory=True)
        cls.loose_file.write_text("kept")
        cls.result = subprocess.run(
            _argv(cls.models),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.scratch.cleanup()

    def test_the_run_succeeds(self) -> None:
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_a_package_without_metadata_is_removed(self) -> None:
        self.assertFalse(self.partial.exists())

    def test_only_the_removed_package_is_reported(self) -> None:
        self.assertEqual(self.result.stdout.split(), [str(self.partial)])

    def test_a_complete_package_is_kept(self) -> None:
        self.assertTrue((self.complete / "metadata.json").exists())

    def test_a_symlink_and_its_target_are_never_touched(self) -> None:
        self.assertTrue(self.link.is_symlink())
        self.assertTrue((self.outside / "data").exists())

    def test_a_plain_file_is_kept(self) -> None:
        self.assertTrue(self.loose_file.exists())


class TestPruneThroughSymlinkedModelsDir(unittest.TestCase):
    def setUp(self) -> None:
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        real = root / "real-models"
        self.partial = real / "translate-de_en-1_3"
        self.complete = real / "translate-en_de-1_3"
        self.nested_link = real / "translate-linked-1_0"
        (self.partial / "model").mkdir(parents=True)
        self.complete.mkdir()
        (self.complete / "metadata.json").write_text("{}")
        (root / "outside").mkdir()
        self.nested_link.symlink_to(root / "outside", target_is_directory=True)
        self.models = root / "models"
        self.models.symlink_to(real, target_is_directory=True)

    def test_a_partial_package_behind_a_symlinked_models_dir_is_removed(
        self,
    ) -> None:
        result = subprocess.run(
            _argv(self.models), capture_output=True, text=True, check=False, timeout=60
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.partial.exists())
        self.assertTrue((self.complete / "metadata.json").exists())
        self.assertTrue(self.nested_link.is_symlink())


class TestPruneOrder(unittest.TestCase):
    def setUp(self) -> None:
        self.names = [task.get("name") for task in _tasks()]

    def test_the_prune_runs_after_the_directory_exists_and_before_compose_up(
        self,
    ) -> None:
        self.assertLess(self.names.index(MKDIR), self.names.index(PRUNE))
        self.assertLess(self.names.index(PRUNE), self.names.index(FLUSH))

    def test_the_prune_runs_on_every_node_the_directory_exists_on(self) -> None:
        prune, mkdir = _task(PRUNE), _task(MKDIR)

        self.assertEqual(prune["loop"], mkdir["loop"])
        self.assertEqual(prune["delegate_to"], mkdir["delegate_to"])


if __name__ == "__main__":
    unittest.main()
