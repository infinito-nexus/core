from __future__ import annotations

import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.litellm.local_model import (
    OLLAMA_VERSION,
    PIN_KEYS,
    declared_local_models,
    local_model_directives,
    local_model_modelfile,
    local_model_refusal,
    local_models_missing,
    local_models_pinned,
)
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_COMMIT = "199151125cf15a129ab3b548b26afeed976df066"
_SHA = "f7ede42862ceca07ad1c88a97b67520019c4ac7e5ced250d2e696fa62ab189af"
_URL = (
    "https://huggingface.co/lmstudio-community/Llama-3.2-1B-Instruct-GGUF/"
    "resolve/{ref}/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)
_PINNED = {
    "alias": "llama3.2:1b",
    "url": _URL.format(ref=_COMMIT),
    "revision": _COMMIT,
    "sha256": _SHA,
    "bytes": 807690688,
}
_ARTEFACTS = {"llama": {**_PINNED, "name": "llama", "role": "svc-ai-models"}}
_HANDED = f"/root/.ollama/models/import/{_SHA}.gguf"
_BLOB = f"FROM /root/.ollama/models/blobs/sha256-{_SHA}"
_TUNED = dict(
    _PINNED,
    renderer="qwen3-coder",
    parser="qwen3-coder",
    parameters={
        "temperature": 0.7,
        "stop": ["<|im_start|>", "<|im_end|>"],
        "top_k": 20,
        "repeat_penalty": 1.05,
    },
)
_TUNED_LINES = [
    "RENDERER qwen3-coder",
    "PARSER qwen3-coder",
    "PARAMETER repeat_penalty 1.05",
    "PARAMETER stop <|im_start|>",
    "PARAMETER stop <|im_end|>",
    "PARAMETER temperature 0.7",
    "PARAMETER top_k 20",
]
_INJECTIONS = {
    "a second FROM in a stop token": dict(
        _PINNED, parameters={"stop": ["<|im_end|>\nFROM qwen2.5:0.5b"]}
    ),
    "a second FROM in the renderer": dict(
        _PINNED, renderer="qwen3-coder\nFROM qwen2.5:0.5b"
    ),
    "a second FROM in a parameter name": dict(
        _PINNED, parameters={"top_k 20\nFROM qwen2.5:0.5b": 1}
    ),
    "a second FROM as a parameter value": dict(
        _PINNED, parameters={"temperature": "0.7\nFROM qwen2.5:0.5b"}
    ),
    "a DRAFT in the parser": dict(_PINNED, parser="gemma4\nDRAFT /tmp/draft.gguf"),
    "a DRAFT as a parameter": dict(_PINNED, parameters={"draft": "/tmp/draft.gguf"}),
    "a DRAFT behind a carriage return": dict(
        _PINNED, parameters={"stop": ["<eos>\rDRAFT /tmp/draft.gguf"]}
    ),
}


class TestLocalModelRefusal(unittest.TestCase):
    def test_a_file_pinned_to_one_commit_passes(self) -> None:
        self.assertEqual("", local_model_refusal(_PINNED))

    def test_a_url_on_a_branch_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, url=_URL.format(ref="main")))
        self.assertIn("ref segment 'main'", refusal)

    def test_a_branch_as_revision_is_refused(self) -> None:
        refusal = local_model_refusal(
            dict(_PINNED, url=_URL.format(ref="main"), revision="main")
        )
        self.assertIn("40-digit lowercase hex commit", refusal)

    def test_a_missing_digest_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, sha256=""))
        self.assertIn("sha256", refusal)

    def test_a_missing_size_is_refused(self) -> None:
        unsized = {key: value for key, value in _PINNED.items() if key != "bytes"}
        self.assertIn("bytes", local_model_refusal(unsized))

    def test_a_library_tag_is_refused(self) -> None:
        refusal = local_model_refusal({"alias": "qwen2.5:0.5b", "context": 4096})
        self.assertIn("revision", refusal)
        self.assertIn("sha256", refusal)

    def test_a_bare_tag_string_is_refused(self) -> None:
        self.assertIn("not a mapping", local_model_refusal("qwen2.5:0.5b"))


class TestDirectiveRefusal(unittest.TestCase):
    def test_vetted_directives_pass(self) -> None:
        self.assertEqual("", local_model_refusal(_TUNED))

    def test_every_injection_is_refused(self) -> None:
        for label, entry in _INJECTIONS.items():
            with self.subTest(label):
                self.assertNotEqual("", local_model_refusal(entry))

    def test_an_unvetted_renderer_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, renderer="gemma4-large"))
        self.assertIn("renderer 'gemma4-large' is not one of", refusal)

    def test_a_listed_parser_name_is_refused(self) -> None:
        self.assertIn("parser", local_model_refusal(dict(_PINNED, parser=["gemma4"])))

    def test_num_ctx_is_refused_because_the_entry_context_owns_it(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, parameters={"num_ctx": 8192}))
        self.assertIn("parameter 'num_ctx' is not one of", refusal)

    def test_a_value_float32_cannot_keep_is_refused(self) -> None:
        refusal = local_model_refusal(
            dict(_PINNED, parameters={"temperature": 0.123456789})
        )
        self.assertIn("significant digits", refusal)

    def test_a_boolean_or_textual_number_is_refused(self) -> None:
        for value in (True, "0.7", None, float("nan")):
            with self.subTest(value=value):
                refusal = local_model_refusal(
                    dict(_PINNED, parameters={"temperature": value})
                )
                self.assertIn("is not a number", refusal)

    def test_a_stop_string_instead_of_a_list_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, parameters={"stop": "<eos>"}))
        self.assertIn("parameter stop", refusal)

    def test_parameters_that_are_no_mapping_are_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, parameters=["temperature"]))
        self.assertIn("parameters is not a mapping", refusal)


class TestLocalModelModelfile(unittest.TestCase):
    def test_the_modelfile_is_from_the_handed_file_then_the_directives(self) -> None:
        self.assertEqual(
            "\n".join([f"FROM {_HANDED}", *_TUNED_LINES]) + "\n",
            local_model_modelfile(_TUNED, _HANDED),
        )

    def test_an_entry_without_directives_is_from_only(self) -> None:
        self.assertEqual(f"FROM {_HANDED}\n", local_model_modelfile(_PINNED, _HANDED))

    def test_numbers_render_as_ollama_prints_them(self) -> None:
        entry = dict(_PINNED, parameters={"temperature": 1.0, "top_p": 0.95})
        self.assertEqual(
            ["PARAMETER temperature 1", "PARAMETER top_p 0.95"],
            local_model_directives(entry),
        )

    def test_no_injection_reaches_a_modelfile(self) -> None:
        for label, entry in _INJECTIONS.items():
            with self.subTest(label), self.assertRaises(AnsibleFilterError):
                local_model_modelfile(entry, _HANDED)

    def test_an_accepted_modelfile_has_one_from_and_no_draft(self) -> None:
        lines = local_model_modelfile(_TUNED, _HANDED).splitlines()
        self.assertEqual(1, sum(line.startswith("FROM ") for line in lines))
        self.assertFalse([line for line in lines if line.startswith("DRAFT")])


class TestLocalModelsMissing(unittest.TestCase):
    def test_a_model_held_at_its_pinned_blob_is_present(self) -> None:
        held = {"model": _PINNED, "stdout": f"{_BLOB}\n"}
        self.assertEqual([], local_models_missing([held]))

    def test_a_model_held_at_another_blob_is_missing(self) -> None:
        other = {
            "model": _PINNED,
            "stdout": "FROM /root/.ollama/models/blobs/sha256-" + "0" * 64,
        }
        self.assertEqual([_PINNED], local_models_missing([other]))

    def test_an_absent_model_is_missing(self) -> None:
        absent = {"model": _PINNED, "stdout": "", "rc": 1}
        self.assertEqual([_PINNED], local_models_missing([absent]))

    def test_no_results_means_nothing_missing(self) -> None:
        self.assertEqual([], local_models_missing(None))

    def test_a_model_held_without_its_directives_is_missing(self) -> None:
        bare = {"model": _TUNED, "stdout": f"{_BLOB}\n"}
        self.assertEqual([_TUNED], local_models_missing([bare]))

    def test_directives_in_any_order_beside_added_ones_are_present(self) -> None:
        shown = [_BLOB, "PARAMETER stop <turn|>", *reversed(_TUNED_LINES)]
        held = {"model": _TUNED, "stdout": "\n".join(shown)}
        self.assertEqual([], local_models_missing([held]))

    def test_a_drifted_parameter_is_missing(self) -> None:
        shown = [
            _BLOB,
            *(
                "PARAMETER temperature 0.8"
                if line.endswith("temperature 0.7")
                else line
                for line in _TUNED_LINES
            ),
        ]
        drifted = {"model": _TUNED, "stdout": "\n".join(shown)}
        self.assertEqual([_TUNED], local_models_missing([drifted]))


class TestLocalModelsPinned(unittest.TestCase):
    def test_the_pins_come_from_the_named_artefact(self) -> None:
        [model] = local_models_pinned(
            [{"alias": "llama3.2:1b", "artefact": "llama"}], _ARTEFACTS
        )
        self.assertEqual(
            {key: model[key] for key in PIN_KEYS},
            {key: _PINNED[key] for key in PIN_KEYS},
        )

    def test_a_declaration_that_pins_the_file_itself_is_refused(self) -> None:
        for key in PIN_KEYS:
            with self.subTest(key=key), self.assertRaisesRegex(AnsibleFilterError, key):
                local_models_pinned(
                    [{"alias": "x", "artefact": "llama", key: _PINNED[key]}],
                    _ARTEFACTS,
                )

    def test_an_unknown_artefact_is_refused(self) -> None:
        with self.assertRaisesRegex(AnsibleFilterError, "no role declares"):
            local_models_pinned([{"alias": "x", "artefact": "gone"}], _ARTEFACTS)

    def test_every_shipped_model_resolves_a_40_digit_commit(self) -> None:
        variables = load_yaml_str(
            read_text(str(PROJECT_ROOT / "group_vars" / "all" / "16_ai.yml"))
        )
        models = declared_local_models(variables)
        self.assertTrue(models)
        for model in models:
            with self.subTest(alias=model["alias"]):
                self.assertEqual(
                    [local_model_refusal(model), "/resolve/main/" in model["url"]],
                    ["", False],
                )


class TestOllamaVersion(unittest.TestCase):
    def test_the_vetted_names_belong_to_the_pinned_ollama_version(self) -> None:
        services = PROJECT_ROOT / "roles" / "svc-ai-ollama" / ROLE_FILE_META_SERVICES
        pinned = load_yaml_str(read_text(str(services)))["ollama"]
        self.assertEqual(
            OLLAMA_VERSION,
            str(pinned["version"]),
            "re-vet the renderer and parser names against the new Ollama "
            "version, then raise OLLAMA_VERSION",
        )


if __name__ == "__main__":
    unittest.main()
