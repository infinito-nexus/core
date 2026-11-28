from __future__ import annotations

import importlib
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

gates = importlib.import_module(
    "tests.unit.python.roles.svc-ai-models.test_engine_gates"
)

APPLICATION = "svc-ai-ollama"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FILES = {
    "core": ROLE / "tasks" / "00_core.yml",
    "manager": ROLE / "tasks" / "01_manager_ops.yml",
    "create": ROLE / "tasks" / "03_create.yml",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "compose": ROLE / ROLE_FILE_TEMPL_COMPOSE,
}
CID = "0123456789ab"
SHA256 = "c" * 64
MODELS = [
    {
        "alias": "small",
        "url": "https://huggingface.co/org/small-GGUF/resolve/main/small.gguf",
        "sha256": SHA256,
    }
]
LINKS = {f"blobs/sha256-{SHA256}": f"store/{SHA256}"}


def _texts() -> dict[str, str]:
    return {key: read_text(str(path)) for key, path in FILES.items()}


def _mount(declared: str) -> str:
    """
    Args:
        declared: the text of the role's ``vars/main.yml``.

    Returns:
        ``OLLAMA_STORE_MOUNT`` as Ansible renders it.
    """
    return gates.resolve(APPLICATION, declared, ("OLLAMA_STORE_MOUNT",), {}, {})[
        "OLLAMA_STORE_MOUNT"
    ]


def _linked(manager: str, create: str) -> dict[str, str]:
    """Args:
        manager: the text of ``tasks/01_manager_ops.yml``, which names the
            store file and the blob of the import.
        create: the text of ``tasks/03_create.yml``.

    Returns:
        The blob of the file's digest, mapped to where it links, relative to
        the container root; empty when it is no link.

    Raises:
        AssertionError: the step runs outside the Ollama container.
    """
    (include,) = [
        task
        for task in load_yaml_str(manager)
        if task.get("ansible.builtin.include_tasks") == "02_import.yml"
    ]
    (task,) = [
        task
        for task in load_yaml_str(create)
        if "ansible.builtin.shell" in task and "loop" not in task
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        values = {
            "OLLAMA_LOCAL_CID": CID,
            "OLLAMA_BLOBS_DIR": str(root / "blobs"),
            "OLLAMA_IMPORT_DIR": str(root / "import"),
            "AI_MODELS_STORE_PATH": str(root / "store"),
            "ollama_file": MODELS[0],
        }
        for name in ("ollama_handed", "ollama_blob"):
            values[name] = gates.render(include["vars"][name], values, gates.no_lookup)
        argv = shlex.split(
            gates.render(task["ansible.builtin.shell"], values, gates.no_lookup)
        )
        if argv[:3] != ["container", "exec", CID]:
            raise AssertionError(f"the step runs outside the container: {argv}")
        subprocess.run(argv[3:], capture_output=True, text=True, check=False)
        paths = {path: root / path for path in LINKS}
        return {
            path: str(link.readlink().relative_to(root)) if link.is_symlink() else ""
            for path, link in paths.items()
        }


class TestOllamaStoreLink(unittest.TestCase):
    def test_ollama_takes_its_models_from_the_store_without_a_copy(self) -> None:
        texts = _texts()
        self.assertEqual(
            gates.require_gate(
                texts["core"], gates.ROUTINE, {"OLLAMA_PRELOAD_MODELS": MODELS}
            ),
            (True, MODELS),
        )
        self.assertEqual(
            gates.require_gate(
                texts["core"], gates.ROUTINE, {"OLLAMA_PRELOAD_MODELS": []}
            ),
            (False, []),
        )
        mount = _mount(texts["vars"])
        self.assertEqual(mount, gates.MOUNT)
        self.assertEqual(
            gates.compose_volumes(texts["compose"], {"OLLAMA_STORE_MOUNT": mount}),
            [[gates.MOUNT]],
        )
        self.assertEqual(_linked(texts["manager"], texts["create"]), LINKS)
        self.assertNotIn("get_url_retry", texts["create"])

    def test_negative_control_a_late_require_a_writable_mount_or_a_copy_fails(
        self,
    ) -> None:
        texts = _texts()
        tasks = load_yaml_str(texts["core"])
        late = dump_yaml_str(
            [task for task in tasks if gates.target(task) != gates.REQUIRE]
            + [task for task in tasks if gates.target(task) == gates.REQUIRE]
        )
        writable = texts["vars"].replace(':ro"', '"')
        copied = texts["create"].replace(" && ln -sfn ", " && cp ")
        self.assertNotEqual(writable, texts["vars"])
        self.assertNotEqual(copied, texts["create"])
        self.assertIsNone(
            gates.require_gate(late, gates.ROUTINE, {"OLLAMA_PRELOAD_MODELS": MODELS})
        )
        self.assertNotEqual(_mount(writable), gates.MOUNT)
        self.assertNotEqual(_linked(texts["manager"], copied), LINKS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
