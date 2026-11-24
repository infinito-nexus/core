from __future__ import annotations

import importlib.util
import sys
import unittest

from utils import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


declared_mod = _load_module(
    "roles/svc-ai-lmstudio/filter_plugins/lmstudio_declared_models.py",
    "lmstudio_declared_models",
)
lmstudio_declared_models = declared_mod.lmstudio_declared_models


def _model(file, url, mirrors=None):
    model = {"repo": "org/Probe-GGUF", "file": file, "url": url}
    if mirrors is not None:
        model["mirrors"] = mirrors
    return model


class LmstudioDeclaredModelsTests(unittest.TestCase):
    def test_a_single_declaration_keeps_its_url_and_mirrors(self):
        models = [_model("probe.gguf", "https://a/probe", ["https://m1/probe"])]

        self.assertEqual(
            lmstudio_declared_models(models),
            [{**models[0], "mirrors": ["https://m1/probe"]}],
        )

    def test_a_declaration_without_mirrors_gets_an_empty_list(self):
        models = [_model("probe.gguf", "https://a/probe")]

        self.assertEqual(lmstudio_declared_models(models)[0]["mirrors"], [])

    def test_a_repeated_path_merges_the_sources_of_every_declaration_once(self):
        models = [
            _model("probe.gguf", "https://a/probe", ["https://m1/probe"]),
            _model(
                "probe.gguf", "https://b/probe", ["https://m1/probe", "https://a/probe"]
            ),
        ]

        merged = lmstudio_declared_models(models)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["url"], "https://a/probe")
        self.assertEqual(merged[0]["mirrors"], ["https://m1/probe", "https://b/probe"])

    def test_paths_that_differ_only_in_case_stay_two_models_in_order(self):
        models = [
            _model("Probe.gguf", "https://a/upper"),
            _model("probe.gguf", "https://a/lower"),
        ]

        self.assertEqual(
            [model["file"] for model in lmstudio_declared_models(models)],
            ["Probe.gguf", "probe.gguf"],
        )

    def test_the_declarations_are_left_untouched(self):
        models = [
            _model("probe.gguf", "https://a/probe"),
            _model("probe.gguf", "https://b/probe"),
        ]

        lmstudio_declared_models(models)

        self.assertNotIn("mirrors", models[0])
        self.assertNotIn("mirrors", models[1])


if __name__ == "__main__":
    unittest.main()
