from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.artefacts import records
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

APPLICATION = "svc-ai-nllb-engine"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
FILES = {
    "core": ROLE / "tasks" / "00_core.yml",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "env": ROLE / "templates" / "env.j2",
    "compose": ROLE / ROLE_FILE_TEMPL_COMPOSE,
}
GATE = "NLLB_STORED | bool"
REQUIRE = "utils/require.yml"
START = "network/routine.yml"
OFFLINE = ("HF_HUB_OFFLINE=1", "TRANSFORMERS_OFFLINE=1")


def _texts() -> dict[str, str]:
    return {key: read_text(str(path)) for key, path in FILES.items()}


def _first(tasks: list[dict], needle: str) -> int:
    return next(
        (index for index, task in enumerate(tasks) if needle in dump_yaml_str(task)),
        len(tasks),
    )


def _findings(texts: dict[str, str]) -> list[str]:
    tasks = load_yaml_str(texts["core"])
    variables = load_yaml_str(texts["vars"])
    found = []
    require = _first(tasks, REQUIRE)
    if require >= _first(tasks, START):
        found.append("the store's require.yml does not run before the start")
    elif GATE not in dump_yaml_str(tasks[require]):
        found.append("the require.yml include is not gated on the manifest entry")
    gated = texts["env"].split("{% if " + GATE + " %}", 1)
    if len(gated) != 2 or not all(line in gated[1] for line in OFFLINE):
        found.append("the offline switches are not set behind the manifest gate")
    if any(line in gated[0] for line in OFFLINE):
        found.append("an offline switch is set without a manifest entry")
    if "NLLB_MODEL={{ NLLB_MODEL_SOURCE }}" not in texts["env"]:
        found.append("the engine does not load the store layout")
    if "extra_volumes=NLLB_STORE_MOUNTS" not in texts["compose"]:
        found.append("the compose file does not mount the store")
    mounts = str(variables.get("NLLB_STORE_MOUNTS", ""))
    if ":ro']" not in mounts or "else []" not in mounts:
        found.append("the store mount is not read-only and gated")
    if ".root]" not in str(variables.get("NLLB_MODEL_SOURCE", "")):
        found.append("the model directory is not the artefacts' tree root")
    return found


class TestNllbStoreGate(unittest.TestCase):
    def test_the_engine_reads_the_store_offline_behind_its_manifest_gate(self) -> None:
        self.assertEqual(_findings(_texts()), [])

    def test_the_engine_pins_its_model_in_one_tree(self) -> None:
        declared = [r for r in records("").values() if r["role"] == APPLICATION]
        self.assertEqual(len({record["root"] for record in declared}), 1, declared)

    def test_the_guard_reports_an_ungated_offline_switch_and_a_writable_mount(
        self,
    ) -> None:
        texts = _texts()
        texts["env"] = "HF_HUB_OFFLINE=1\n" + texts["env"]
        texts["vars"] = texts["vars"].replace(":ro']", "']")
        self.assertEqual(len(_findings(texts)), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
