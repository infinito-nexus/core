from __future__ import annotations

import importlib
import unittest

from utils.cache.artefacts import records

gates = importlib.import_module(
    "tests.unit.python.roles.svc-ai-models.test_engine_gates"
)

APPLICATION = "svc-ai-nllb-engine"
SPEC = {
    "prefix": "NLLB",
    "start": gates.ROUTINE,
    "source": ("NLLB_MODEL_SOURCE", "root"),
    "env": "NLLB_MODEL",
    "offline": gates.OFFLINE,
    "fakes": {"NLLB_MODEL": "facebook/nllb-200-distilled-600M"},
}


class TestNllbStoreGate(unittest.TestCase):
    def test_the_engine_reads_the_store_offline_behind_its_manifest_gate(self) -> None:
        self.assertEqual(
            gates.engine_findings(APPLICATION, SPEC, gates.sources(APPLICATION)), []
        )

    def test_the_engine_pins_its_model_in_one_tree(self) -> None:
        declared = [r for r in records("").values() if r["role"] == APPLICATION]
        self.assertEqual(len({record["root"] for record in declared}), 1, declared)

    def test_the_guard_reports_an_ungated_offline_switch_and_a_writable_mount(
        self,
    ) -> None:
        texts = gates.sources(APPLICATION)
        texts["env"] = "HF_HUB_OFFLINE=1\n" + texts["env"]
        texts["vars"] = texts["vars"].replace(":ro']", "']")
        self.assertEqual(
            {
                "unstored: the offline switches are ['HF_HUB_OFFLINE']",
                f"stored: the store mount is ['{gates.STORE}:{gates.STORE}']",
            }
            - set(gates.engine_findings(APPLICATION, SPEC, texts)),
            set(),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
