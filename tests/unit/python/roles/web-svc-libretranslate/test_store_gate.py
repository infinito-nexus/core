from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from jinja2 import BaseLoader, Environment, meta
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.libretranslate_store import FROM_SOURCE, MINISBD_ROOT
from plugins.filter.libretranslate_store import FilterModule as StoreFilters
from plugins.lookup.cache_artefacts import LookupModule as CacheArtefacts
from utils import PROJECT_ROOT
from utils.cache.artefacts import records as declared_records
from utils.cache.artefacts import tree_root, unpack_path
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ENGINE = "svc-ai-libretranslate-engine"
WEB = "web-svc-libretranslate"
SERVICES = {ENGINE: "libretranslate-engine", WEB: "libretranslate"}
FILES = {
    "vars": ROLE_FILE_VARS_MAIN,
    "compose": ROLE_FILE_TEMPL_COMPOSE,
    "env": "templates/env.j2",
    "dockerfile": "files/Dockerfile",
    "core": "tasks/00_core.yml",
    "volumes": ROLE_FILE_META_VOLUMES,
}
VOLUMES = "    volumes: "
STORE = "/srv/cache/models"
HOME = "/home/libretranslate"
MINISBD_CACHE = f"{HOME}/.cache/minisbd"
PACKAGES_DIR = f"{HOME}/.local/share/argos-translate/packages"
BAKE_ARG = '        LIBRETRANSLATE_BAKE_MODELS: "{{ LIBRETRANSLATE_BAKE_MODELS }}"\n'
BAKE_LINE = '        LIBRETRANSLATE_BAKE_MODELS: "{}"\n'
BAKE_GUARD = (
    'RUN case "${LIBRETRANSLATE_BAKE_MODELS}" in \\\n'
    "      true) ;; \\\n"
    "      false) exit 0 ;; \\\n"
)
ROLES = {
    WEB: {
        "prefix": "LIBRETRANSLATE",
        "today": [
            ("volumes: {{ LIBRETRANSLATE_STORE_MOUNTS | to_json }}", "volumes: []"),
            (BAKE_ARG, ""),
        ],
    },
    ENGINE: {
        "prefix": "LIBRETRANSLATE_ENGINE",
        "today": [(", extra_volumes=LIBRETRANSLATE_ENGINE_STORE_MOUNTS", "")],
    },
}
LOADING_MODELS = ("lazy", "build", "task")


def _record(name: str, url: str, sha256: str, role: str = ENGINE) -> dict:
    return {
        "name": name,
        "upstream": url,
        "root": tree_root(url),
        "unpack": unpack_path(url, sha256),
        "sha256": sha256,
        "role": role,
    }


ARGOS = _record(
    "argos-en-de", "https://argos-net.com/v1/translate-en_de-1_9.argosmodel", "a" * 64
)
ARGOS_FR = _record(
    "argos-en-fr", "https://argos-net.com/v1/translate-en_fr-1_9.argosmodel", "d" * 64
)
MINISBD = _record(
    "minisbd-en-onnx",
    "https://github.com/LibreTranslate/MiniSBD/releases/download/v0.0.1/en.onnx",
    "b" * 64,
)
GATE_ON = [ARGOS, ARGOS_FR, MINISBD]


def _declared() -> list[dict]:
    return [
        record for record in declared_records("").values() if record["role"] == ENGINE
    ]


def _gated(prefix: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\{{% if {prefix}_STORED \| bool %\}}\n(.*?)^\{{% endif %\}}\n",
        re.DOTALL | re.MULTILINE,
    )


def _texts(role: str) -> dict[str, str]:
    base = Path(PROJECT_ROOT) / "roles" / role
    return {
        key: read_text(str(base / path))
        for key, path in FILES.items()
        if (base / path).is_file()
    }


def _with_filters(
    env: Environment,
    records: list[dict],
    loading_model: str,
    directions: str = FROM_SOURCE,
    load_only: tuple[str, ...] = (),
    store: bool = True,
):
    env.filters.update(FilterModule().filters())
    env.filters.update(StoreFilters().filters())
    env.tests.update(TestModule().tests())
    config = {
        ".directions": directions,
        ".load_only": list(load_only),
        ".model_store": store,
    }

    def lookup(name: str, *terms, **_):
        if name == "cache_artefacts":
            return {r["name"]: r for r in records} if terms == (ENGINE,) else {}
        if name == "config":
            return next(
                (value for key, value in config.items() if terms[-1].endswith(key)),
                loading_model,
            )
        raise KeyError(name)

    env.globals["lookup"] = lookup
    return env


def _resolved(
    role: str,
    raw_vars: str,
    records: list[dict],
    loading_model: str = "lazy",
    directions: str = FROM_SOURCE,
    load_only: tuple[str, ...] = (),
    store: bool = True,
) -> dict:
    prefix = ROLES[role]["prefix"]
    raw = load_yaml_str(raw_vars)
    env = _with_filters(
        NativeEnvironment(), records, loading_model, directions, load_only, store
    )
    values = {
        f"{prefix}_APP_USER": "libretranslate",
        "AI_MODELS_STORE_PATH": STORE,
        "application_id": role,
    }

    def resolve(name: str):
        if name not in values:
            names = meta.find_undeclared_variables(env.parse(raw[name]))
            context = {n: resolve(n) for n in names if n in raw or n in values}
            values[name] = env.from_string(raw[name]).render(context)
        return values[name]

    for name in raw:
        if name.startswith(f"{prefix}_STORE") or name in (
            "LIBRETRANSLATE_BAKE_MODELS",
            "LIBRETRANSLATE_ENGINE_LOADING_MODEL",
        ):
            resolve(name)
    return values


def _models_artefacts(expression: str) -> set[str]:
    env = NativeEnvironment()
    env.filters.update(FilterModule().filters())
    env.filters.update(StoreFilters().filters())

    def lookup(name: str, *terms, base: str):
        if name != "cache_artefacts":
            raise KeyError(name)
        return CacheArtefacts().run(list(terms), base=base)[0]

    env.globals["lookup"] = lookup
    roles = sorted({record["role"] for record in declared_records("").values()})
    rendered = env.from_string(expression).render(
        MODELS_DEPLOYED_ROLES=roles, MODELS_ARTEFACT_BASE=""
    )
    return {record["name"] for record in rendered}


class _Stub(BaseLoader):
    def get_source(self, environment, template):
        return "", template, lambda: True


class _Looked(str):
    __slots__ = ()
    title = "Title"


def _render(text: str, values: dict) -> str:
    env = _with_filters(
        Environment(loader=_Stub(), trim_blocks=True),  # noqa: S701 compose and env files, never HTML
        [],
        "",
    )

    def lookup(name: str, *args, **kwargs):
        if kwargs.get("extra_volumes"):
            return "volumes: " + json.dumps(list(kwargs["extra_volumes"]))
        return _Looked(f"<lookup {name}>")

    env.globals["lookup"] = lookup
    return env.from_string(text).render(values | {"LIBRETRANSLATE_MCP_ENABLED": False})


def _today(role: str, text: str) -> str:
    text = _gated(ROLES[role]["prefix"]).sub("", text)
    for new, old in ROLES[role]["today"]:
        text = text.replace(new, old)
    return text


def _bind_mounted(
    texts: dict[str, str],
    records: list[dict],
    model: str,
    directions: str = FROM_SOURCE,
    load_only: tuple[str, ...] = (),
) -> bool:
    when = load_yaml_str(texts["volumes"])["models"]["mounts"][0]["when"]
    env = _with_filters(NativeEnvironment(), records, model, directions, load_only)
    return bool(env.from_string(when).render())


def _gate_off_findings(role: str, texts: dict[str, str]) -> list[str]:
    prefix = ROLES[role]["prefix"]
    found = []
    for model in LOADING_MODELS:
        off = _resolved(role, texts["vars"], [], model)
        for key in ("compose", "env"):
            baked = BAKE_LINE.format("true") if (role, key) == (WEB, "compose") else ""
            rendered = _render(texts[key], off)
            if baked and baked not in rendered:
                found.append(f"{model}: gate off does not bake the models")
            if rendered.replace(baked, "", 1) != _render(
                _today(role, texts[key]), off
            ) or (STORE in rendered or "ARGOS_PACKAGES_DIR" in rendered):
                found.append(f"{model}: gate off changes the {key} file")
        if role == ENGINE:
            if off[f"{prefix}_LOADING_MODEL"] != model:
                found.append(f"{model}: gate off changes the loading model")
            if _bind_mounted(texts, [], model) != (model != "build"):
                found.append(f"{model}: gate off changes the models bind mount")
    if role == WEB:
        runs = [
            block
            for block in texts["dockerfile"].split("\nRUN ")
            if "prefetch_models.py" in block and "--directions" in block
        ]
        if len(runs) != 1 or not ("RUN " + runs[0]).startswith(BAKE_GUARD):
            found.append("the prefetch does not skip when the gate turns baking off")
    return sorted(set(found))


def _gate_on_findings(role: str, texts: dict[str, str]) -> list[str]:
    prefix = ROLES[role]["prefix"]
    on = _resolved(role, texts["vars"], GATE_ON)
    store = on[f"{prefix}_STORE"]
    compose = _render(texts["compose"], on)
    env = _render(texts["env"], on)
    found = []
    baking = (
        BAKE_LINE.format("false") not in compose
        if role == WEB
        else on[f"{prefix}_LOADING_MODEL"] != "store"
    )
    if baking:
        found.append("gate on still bakes, installs or fetches the models")
    if role == ENGINE and _bind_mounted(texts, GATE_ON, "lazy"):
        found.append("gate on keeps the writable models bind mount")
    line = next((row for row in compose.splitlines() if row.startswith(VOLUMES)), "")
    mounts = json.loads(line[len(VOLUMES) :] or "[]")
    found.extend(f"writable mount {m}" for m in mounts if not m.endswith(":ro"))
    read_only = [m.split(":")[1] for m in mounts if m.endswith(":ro")]
    packages = str(store["packages"])
    selected = {
        f"{packages}/{record['name']}"
        for record in store["artefacts"]
        if record.get("unpack")
    }
    listed = {target for target in read_only if target.startswith(f"{packages}/")}
    if (
        f"ARGOS_PACKAGES_DIR={packages}" not in env.splitlines()
        or not selected
        or listed != selected
    ):
        found.append("the Argos packages are not read from the read-only store")
    if not store["minisbd"] or store["minisbd"] not in read_only:
        found.append("the MiniSBD cache is not a read-only store mount")
    return found


def _gate_findings(role: str, texts: dict[str, str]) -> list[str]:
    prefix = ROLES[role]["prefix"]
    found = [
        f"the gate opens on {kind}"
        for kind, records in (
            ("Argos alone", [ARGOS, ARGOS_FR]),
            ("MiniSBD alone", [MINISBD]),
            ("a single package", [ARGOS, MINISBD]),
        )
        if _resolved(role, texts["vars"], records)[f"{prefix}_STORED"]
    ]
    if _resolved(role, texts["vars"], GATE_ON, store=False)[f"{prefix}_STORED"]:
        found.append("the gate opens with model_store off")
    dumped = [dump_yaml_str(task) for task in load_yaml_str(texts["core"])]
    start = next(i for i, t in enumerate(dumped) if "flush_handlers" in t)
    for step in ("utils/seed.yml", "utils/require.yml"):
        at = next((i for i, t in enumerate(dumped) if step in t), len(dumped))
        if at > start or f"{prefix}_STORED | bool" not in dumped[at]:
            found.append(f"{step} does not run gated before the start")
        elif f"{prefix}_STORE.artefacts" not in dumped[at]:
            found.append(f"{step} is not handed the selected artefacts")
    return found


def _owner_findings(records: list[dict]) -> list[str]:
    return [
        f"{record['role']} declares {record['name']}; only {ENGINE} owns them"
        for record in records
        if (record.get("unpack") or record["root"].startswith(MINISBD_ROOT))
        and record["role"] != ENGINE
    ]


def _writable_and_ungated(role: str) -> dict[str, str]:
    texts = _texts(role)
    texts["env"] = _gated(ROLES[role]["prefix"]).sub(r"\1", texts["env"])
    texts["vars"] = texts["vars"].replace(
        "STORE.mounts }}", "STORE.mounts | map('replace', ':ro', '') | list }}"
    )
    return texts


class TestLibretranslateStoreGate(unittest.TestCase):
    def test_gate_off_renders_todays_files_in_every_loading_model(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(_gate_off_findings(role, _texts(role)), [])

    def test_gate_on_reads_both_stores_read_only_without_fetching(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(_gate_on_findings(role, _texts(role)), [])

    def test_both_roles_gate_on_the_engines_entries_and_check_first(self) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(_gate_findings(role, _texts(role)), [])

    def test_both_directions_need_every_pinned_pair_in_reverse(self) -> None:
        reverse = _record(
            "argos-de-en",
            "https://argos-net.com/v1/translate-de_en-1_9.argosmodel",
            "c" * 64,
        )
        for role in ROLES:
            stored = f"{ROLES[role]['prefix']}_STORED"
            raw = _texts(role)["vars"]
            with self.subTest(role=role):
                self.assertFalse(
                    _resolved(role, raw, GATE_ON, directions="both")[stored]
                )
                self.assertTrue(
                    _resolved(role, raw, [ARGOS, reverse, MINISBD], directions="both")[
                        stored
                    ]
                )

    def test_the_declared_pins_open_the_gate_in_both_directions(self) -> None:
        declared = _declared()
        stored = StoreFilters().filters()["libretranslate_stored"]
        for directions in (FROM_SOURCE, "both"):
            with self.subTest(directions=directions):
                self.assertTrue(stored(declared, directions, "", True))
            for role in ROLES:
                with self.subTest(directions=directions, role=role):
                    self.assertTrue(
                        _resolved(
                            role, _texts(role)["vars"], declared, directions=directions
                        )[f"{ROLES[role]['prefix']}_STORED"]
                    )
        unpaired = [
            record
            for record in declared
            if not record["upstream"].endswith("/translate-de_en-1_3.argosmodel")
        ]
        self.assertEqual(len(unpaired), len(declared) - 1)
        self.assertFalse(stored(unpaired, "both", "", True))

    def test_the_store_holds_only_the_selected_pairs_for_each_consumer(
        self,
    ) -> None:
        declared = _declared()
        select = StoreFilters().filters()["libretranslate_store"]
        minisbd = sorted(r["name"] for r in declared if not r.get("unpack"))
        for directions, load_only, names in (
            ("both", "en,de", ["argos-de_en-1_3", "argos-en_de-1_3"]),
            (FROM_SOURCE, "en,de,fr", ["argos-en_de-1_3", "argos-en_fr-1_9"]),
        ):
            with self.subTest(directions=directions):
                store = select(declared, STORE, HOME, directions, load_only, True)
                argos = sorted(r["name"] for r in store["artefacts"] if r["unpack"])
                self.assertEqual(argos, names)
                self.assertEqual(
                    sorted(r["name"] for r in store["artefacts"] if not r["unpack"]),
                    minisbd,
                )
                self.assertEqual(
                    sorted(
                        m.split(":")[1]
                        for m in store["mounts"]
                        if m.split(":")[1].startswith(f"{PACKAGES_DIR}/")
                    ),
                    [f"{PACKAGES_DIR}/{name}" for name in names],
                )
        self.assertFalse(select(declared, STORE, HOME, "both", "en,xx", True)["stored"])
        self.assertFalse(
            select(declared, STORE, HOME, "both", "en,de", False)["stored"]
        )
        self.assertFalse(
            select(declared, STORE, HOME, FROM_SOURCE, "en,de", True)["stored"]
        )

    def test_both_roles_hand_their_load_only_to_the_selection(self) -> None:
        declared = _declared()
        names = ["argos-de_en-1_3", "argos-en_de-1_3"]
        for role in ROLES:
            prefix = ROLES[role]["prefix"]
            raw = _texts(role)["vars"]
            with self.subTest(role=role):
                store = _resolved(
                    role, raw, declared, directions="both", load_only=("en", "de")
                )[f"{prefix}_STORE"]
                self.assertEqual(
                    sorted(r["name"] for r in store["artefacts"] if r["unpack"]),
                    names,
                )
                self.assertEqual(
                    sorted(
                        m.split(":")[1]
                        for m in store["mounts"]
                        if m.split(":")[1].startswith(f"{PACKAGES_DIR}/")
                    ),
                    [f"{PACKAGES_DIR}/{name}" for name in names],
                )
                self.assertFalse(
                    _resolved(role, raw, declared, load_only=("en", "de"))[
                        f"{prefix}_STORED"
                    ]
                )
        texts = _texts(ENGINE)
        self.assertFalse(_bind_mounted(texts, declared, "lazy"))
        self.assertTrue(_bind_mounted(texts, declared, "lazy", load_only=("en", "de")))

    def test_the_store_role_leaves_the_selection_to_the_consumers(self) -> None:
        raw = read_text(
            str(Path(PROJECT_ROOT) / "roles" / "svc-ai-models" / ROLE_FILE_VARS_MAIN)
        )
        expression = load_yaml_str(raw)["MODELS_ARTEFACTS"]
        unfiltered = expression.replace(" | libretranslate_unselected", "")
        self.assertNotEqual(unfiltered, expression)
        every = set(declared_records(""))
        engine = {r["name"] for r in _declared()}
        others = every - engine
        self.assertTrue(engine)
        self.assertTrue(others)
        self.assertEqual(_models_artefacts(expression), others)
        self.assertEqual(_models_artefacts(unfiltered), every)

    def test_the_variants_keep_the_bake_path_covered(self) -> None:
        services = {}
        for role, service in SERVICES.items():
            path = Path(PROJECT_ROOT) / "roles" / role / ROLE_FILE_META_VARIANTS
            services[role] = [
                variant["services"][service]
                for variant in load_yaml_str(read_text(str(path)))
            ]
            with self.subTest(role=role):
                self.assertEqual(
                    {variant.get("model_store", True) for variant in services[role]},
                    {True, False},
                )
        off = {
            variant.get("loading_model")
            for variant in services[ENGINE]
            if variant.get("model_store") is False
        }
        self.assertEqual(off, {"build", "task"})

    def test_only_the_engine_declares_argos_and_minisbd(self) -> None:
        self.assertEqual(_owner_findings(list(declared_records("").values())), [])

    def test_the_guard_reports_an_ungated_switch_and_writable_mounts(
        self,
    ) -> None:
        for role in ROLES:
            with self.subTest(role=role):
                texts = _writable_and_ungated(role)
                self.assertEqual(
                    [*_gate_off_findings(role, texts), *_gate_on_findings(role, texts)],
                    [
                        f"{model}: gate off changes the env file"
                        for model in sorted(LOADING_MODELS)
                    ]
                    + [
                        f"writable mount {STORE}:{STORE}",
                        f"writable mount {STORE}/{MINISBD['root']}:{MINISBD_CACHE}",
                        *(
                            f"writable mount {STORE}/{record['unpack']}:"
                            f"{PACKAGES_DIR}/{record['name']}"
                            for record in (ARGOS, ARGOS_FR)
                        ),
                        "the Argos packages are not read from the read-only store",
                        "the MiniSBD cache is not a read-only store mount",
                    ],
                )

    def test_the_guard_reports_a_web_role_reading_its_own_entries(self) -> None:
        texts = _texts(WEB)
        texts["vars"] = texts["vars"].replace(
            f"'cache_artefacts', '{ENGINE}'", "'cache_artefacts', application_id"
        )
        self.assertIn(
            "gate on still bakes, installs or fetches the models",
            _gate_on_findings(WEB, texts),
        )
        self.assertEqual(len(_owner_findings([ARGOS | {"role": WEB}, MINISBD])), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
