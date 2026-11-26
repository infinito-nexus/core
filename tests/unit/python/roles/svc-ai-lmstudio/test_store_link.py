from __future__ import annotations

import importlib
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

gates = importlib.import_module(
    "tests.unit.python.roles.svc-ai-models.test_engine_gates"
)

APPLICATION = "svc-ai-lmstudio"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FILES = {
    "core": ROLE / "tasks" / "00_core.yml",
    "node": ROLE / "tasks" / "utils" / "preload" / "node.yml",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "compose": ROLE / ROLE_FILE_TEMPL_COMPOSE,
}
DOWNLOADS = ("lms get", "get_url_retry", "preseed.yml", "pull.yml")
CID = "0123456789ab"
MODELS = [
    {
        "alias": "small",
        "repo": "org/small-GGUF",
        "file": "small-Q4_K_M.gguf",
        "sha256": "a" * 64,
    },
    {
        "alias": "large",
        "repo": "org/large-GGUF",
        "file": "large-Q4_K_M.gguf",
        "sha256": "b" * 64,
    },
]
LINKS = {
    f"{model['repo']}/{model['file']}": f"store/{model['sha256']}" for model in MODELS
}


def _texts() -> dict[str, str]:
    return {key: read_text(str(path)) for key, path in FILES.items()}


def _mount(declared: str) -> str:
    """
    Args:
        declared: the text of the role's ``vars/main.yml``.

    Returns:
        ``LMSTUDIO_STORE_MOUNT`` as Ansible renders it.
    """
    return gates.resolve(APPLICATION, declared, ("LMSTUDIO_STORE_MOUNT",), {}, {})[
        "LMSTUDIO_STORE_MOUNT"
    ]


def _linked(node: str) -> dict[str, str]:
    """Args:
        node: the text of ``tasks/utils/preload/node.yml``.

    Returns:
        Each model path below the models volume, mapped to where it links,
        relative to the container root; empty when it is no link.

    Raises:
        AssertionError: the step runs outside the LM Studio container.
    """
    (task,) = [
        task
        for task in load_yaml_str(node)
        if task.get("loop") == "{{ LMSTUDIO_PRELOAD_MODELS }}"
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        values = {
            "LMSTUDIO_LOCAL_CID": CID,
            "LMSTUDIO_MODELS_TARGET": str(root / "models"),
            "AI_MODELS_STORE_PATH": str(root / "store"),
        }
        for model in MODELS:
            argv = shlex.split(
                gates.render(
                    task["ansible.builtin.shell"],
                    {**values, "model": model},
                    gates.no_lookup,
                )
            )
            if argv[:3] != ["container", "exec", CID]:
                raise AssertionError(f"the step runs outside the container: {argv}")
            subprocess.run(argv[3:], capture_output=True, text=True, check=False)
        paths = {path: root / "models" / path for path in LINKS}
        return {
            path: str(link.readlink().relative_to(root)) if link.is_symlink() else ""
            for path, link in paths.items()
        }


class TestLmStudioStoreLink(unittest.TestCase):
    def test_lm_studio_links_its_models_to_the_store(self) -> None:
        texts = _texts()
        preload = {"LMSTUDIO_PRELOAD_MODELS": MODELS}
        self.assertEqual(
            gates.require_gate(texts["core"], gates.ROUTINE, preload), (True, MODELS)
        )
        self.assertEqual(
            gates.require_gate(
                texts["core"], gates.ROUTINE, {"LMSTUDIO_PRELOAD_MODELS": []}
            ),
            (False, []),
        )
        mount = _mount(texts["vars"])
        self.assertEqual(mount, gates.MOUNT)
        self.assertEqual(
            gates.compose_volumes(texts["compose"], {"LMSTUDIO_STORE_MOUNT": mount}),
            [[gates.MOUNT]],
        )
        self.assertEqual(_linked(texts["node"]), LINKS)
        self.assertEqual(
            [needle for needle in DOWNLOADS if needle in texts["core"] + texts["node"]],
            [],
        )

    def test_negative_control_a_writable_mount_or_a_copied_model_fails(self) -> None:
        texts = _texts()
        writable = texts["vars"].replace(':ro"', '"')
        copied = texts["node"].replace(" && ln -sfn ", " && cp ")
        self.assertNotEqual(writable, texts["vars"])
        self.assertNotEqual(copied, texts["node"])
        self.assertNotEqual(_mount(writable), gates.MOUNT)
        self.assertNotEqual(_linked(copied), LINKS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
