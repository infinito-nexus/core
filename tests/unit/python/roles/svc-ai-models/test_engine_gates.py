from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.artefacts import records
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

REQUIRE = "utils/require.yml"
OFFLINE = ("HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1")
GATE_WINDOW = 3
ENGINES = {
    "svc-ai-s1": {
        "prefix": "S1",
        "start": "network/routine.yml",
        "env": ["JEFF_MODEL={{ S1_JEFF_MODEL_SOURCE }}", *OFFLINE],
        "source": "S1_JEFF_MODEL_SOURCE",
    },
    "svc-ai-ltengine": {
        "prefix": "LTENGINE",
        "start": "network/routine.yml",
        "env": ["LTENGINE_MODEL_FILE={{ LTENGINE_MODEL_FILE }}"],
        "source": "LTENGINE_MODEL_FILE",
        "dockerfile": '--model-file \\"${LTENGINE_MODEL_FILE}\\"',
    },
    "web-app-openwebui": {
        "prefix": "OPENWEBUI",
        "start": "consumer.yml",
        "env": [
            "RAG_EMBEDDING_MODEL={{ OPENWEBUI_EMBEDDING_SOURCE }}",
            "TRANSFORMERS_OFFLINE=1",
            "HF_HUB_OFFLINE={{ 1 if (OPENWEBUI_STORED | bool) else",
        ],
        "source": "OPENWEBUI_EMBEDDING_SOURCE",
    },
}


def _texts(role: str) -> dict[str, str]:
    base = PROJECT_ROOT / "roles" / role
    paths = {
        "core": base / "tasks" / "00_core.yml",
        "vars": base / ROLE_FILE_VARS_MAIN,
        "env": base / "templates" / "env.j2",
        "compose": base / ROLE_FILE_TEMPL_COMPOSE,
        "dockerfile": base / "files" / "Dockerfile",
    }
    return {key: read_text(str(path)) for key, path in paths.items() if path.is_file()}


def _first(tasks: list[dict], needle: str) -> int:
    return next(
        (index for index, task in enumerate(tasks) if needle in dump_yaml_str(task)),
        len(tasks),
    )


def _ungated(env: str, gate: str) -> list[str]:
    lines = env.splitlines()
    return [
        line
        for index, line in enumerate(lines)
        if line in OFFLINE
        and not any(gate in lines[j] for j in range(max(0, index - GATE_WINDOW), index))
    ]


def _findings(spec: dict, texts: dict[str, str]) -> list[str]:
    prefix = spec["prefix"]
    gate = f"{prefix}_STORED | bool"
    tasks = load_yaml_str(texts["core"])
    variables = load_yaml_str(texts["vars"])
    found = []
    require = _first(tasks, REQUIRE)
    if require >= _first(tasks, spec["start"]):
        found.append("the store's require.yml does not run before the start")
    elif gate not in dump_yaml_str(tasks[require]):
        found.append("the require.yml include is not gated on the manifest entry")
    found.extend(
        f"env misses {needle!r}" for needle in spec["env"] if needle not in texts["env"]
    )
    found.extend(
        f"ungated offline switch {line}" for line in _ungated(texts["env"], gate)
    )
    if f"extra_volumes={prefix}_STORE_MOUNTS" not in texts["compose"]:
        found.append("the compose file does not mount the store")
    mounts = str(variables.get(f"{prefix}_STORE_MOUNTS", ""))
    if ":ro']" not in mounts or "else []" not in mounts:
        found.append("the store mount is not read-only and gated")
    if "cache_artefacts', application_id" not in str(
        variables.get(f"{prefix}_ARTEFACTS")
    ):
        found.append("the gate does not read the role's manifest entries")
    if "AI_MODELS_STORE_PATH" not in str(variables.get(spec["source"], "")):
        found.append("the engine does not load from the store")
    if "dockerfile" in spec and spec["dockerfile"] not in texts.get("dockerfile", ""):
        found.append("the image does not hand the store file to the engine")
    return found


class TestEngineGates(unittest.TestCase):
    def test_every_engine_reads_the_store_offline_behind_its_manifest_gate(
        self,
    ) -> None:
        for role, spec in ENGINES.items():
            with self.subTest(role=role):
                self.assertEqual(_findings(spec, _texts(role)), [])

    def test_every_engine_pins_its_model_in_one_tree(self) -> None:
        roots: dict[str, set[str]] = {}
        for record in records("").values():
            roots.setdefault(record["role"], set()).add(record["root"])
        for role in ENGINES:
            with self.subTest(role=role):
                self.assertEqual(len(roots.get(role, set())), 1, roots.get(role))

    def test_the_guard_reports_an_ungated_switch_and_a_writable_mount(self) -> None:
        for role, spec in ENGINES.items():
            with self.subTest(role=role):
                texts = _texts(role)
                texts["env"] = "TRANSFORMERS_OFFLINE=1\n" + texts["env"]
                texts["vars"] = texts["vars"].replace(":ro']", "']")
                self.assertEqual(len(_findings(spec, texts)), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
