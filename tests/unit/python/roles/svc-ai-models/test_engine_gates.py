from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from jinja2 import (
    ChainableUndefined,
    Environment,
    FunctionLoader,
    nodes,
    select_autoescape,
)
from jinja2.nativetypes import NativeEnvironment

from tests.lint.repository import dockerfile_instructions
from utils import PROJECT_ROOT
from utils.cache.artefacts import records
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

STORE = "/srv/ai-models"
MOUNT = f"{STORE}:{STORE}:ro"
ENTRY = {"root": "org/model", "tree": "org/model/model.gguf"}
REQUIRE = ("role", "svc-ai-models", "utils/require.yml")
ROUTINE = ("tasks", "roles/sys-svc-compose/tasks/utils/network/routine.yml")
OFFLINE = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
INCLUDE_ROLE = ("include_role", "ansible.builtin.include_role")
INCLUDE_TASKS = ("include_tasks", "ansible.builtin.include_tasks")
ARGV_STUB = '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >"${STUB_LOG}"\n'
ENGINES = {
    "svc-ai-s1": {
        "prefix": "S1",
        "start": ROUTINE,
        "source": ("S1_JEFF_MODEL_SOURCE", "root"),
        "env": "JEFF_MODEL",
        "offline": OFFLINE,
        "fakes": {"S1_FLAVOR": "torch", "S1_JEFF_MODEL_PATH": "/opt/jeff"},
    },
    "svc-ai-ltengine": {
        "prefix": "LTENGINE",
        "start": ROUTINE,
        "source": ("LTENGINE_MODEL_FILE", "tree"),
        "env": "LTENGINE_MODEL_FILE",
        "offline": (),
        "fakes": {},
        "program": "ltengine",
    },
    "web-app-openwebui": {
        "prefix": "OPENWEBUI",
        "start": ("role", "svc-stack", "consumer.yml"),
        "source": ("OPENWEBUI_EMBEDDING_SOURCE", "root"),
        "env": "RAG_EMBEDDING_MODEL",
        "offline": OFFLINE,
        "fakes": {},
    },
}


def ansible_bool(value) -> bool:
    """
    Args:
        value: what a template pipes into ``bool``.

    Returns:
        The value as Ansible's ``bool`` filter reads it.
    """
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


def _identity(value, *_args, **_kwargs):
    return value


def _absent(*_args, **_kwargs) -> bool:
    return False


def no_lookup(*_terms, **_kwargs) -> str:
    return ""


def render(
    source: str,
    variables: dict,
    lookup,
    native: bool = False,
    includes: dict[str, str] | None = None,
):
    """Args:
        source: the template text.
        variables: the values it reads; any other variable renders empty.
        lookup: stands in for Ansible's ``lookup``.
        native: return the native value of a lone expression, as Ansible
            does for a variable, instead of text.
        includes: the text of included templates; any other include renders
            empty.

    Returns:
        The rendered text, or the value with ``native``.
    """
    included = includes or {}
    environment = (NativeEnvironment if native else Environment)(
        loader=FunctionLoader(lambda name: included.get(name, "")),
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters.update(
        bool=ansible_bool,
        path_join=lambda parts: str(PurePosixPath(*parts)),
        quote=lambda value: shlex.quote(str(value)),
    )
    parsed = environment.parse(source)
    for node in parsed.find_all(nodes.Filter):
        environment.filters.setdefault(node.name, _identity)
    for node in parsed.find_all(nodes.Test):
        environment.tests.setdefault(node.name, _absent)
    environment.globals["lookup"] = lookup
    return environment.from_string(source).render(**variables)


def sources(role: str) -> dict[str, str]:
    """
    Args:
        role: an engine role.

    Returns:
        The text of its core tasks, vars, env and compose templates and, when
        it builds one, its Dockerfile.
    """
    base = PROJECT_ROOT / "roles" / role
    paths = {
        "core": base / "tasks" / "00_core.yml",
        "vars": base / ROLE_FILE_VARS_MAIN,
        "env": base / "templates" / "env.j2",
        "compose": base / ROLE_FILE_TEMPL_COMPOSE,
        "dockerfile": base / "files" / "Dockerfile",
    }
    return {key: read_text(str(path)) for key, path in paths.items() if path.is_file()}


def resolve(
    role: str, declared: str, names: tuple[str, ...], fakes: dict, manifest: dict
) -> dict:
    """Args:
        role: the role that declares them.
        declared: the text of its ``vars/main.yml``.
        names: the variables to render.
        fakes: values of the other variables they read.
        manifest: what ``lookup('cache_artefacts', role)`` answers.

    Returns:
        The variables with every name rendered.

    Raises:
        AssertionError: a variable looks anything up but the role's own
            manifest entries.
    """
    variables = load_yaml_str(declared)

    def lookup(name, *terms, **_kwargs):
        if (name, terms) != ("cache_artefacts", (role,)):
            raise AssertionError(f"{role} looks up {name}{terms}")
        return manifest

    values = {"application_id": role, "AI_MODELS_STORE_PATH": STORE, **fakes}
    for name in names:
        values[name] = render(variables[name], values, lookup, native=True)
    return values


def target(task: dict) -> tuple:
    """
    Args:
        task: one task of a task file.

    Returns:
        ``("role", name, tasks_from)`` or ``("tasks", path)`` of the include
        the task makes, empty for any other task.
    """
    for key in INCLUDE_ROLE:
        if key in task:
            return ("role", task[key]["name"], task[key].get("tasks_from", "main.yml"))
    for key in INCLUDE_TASKS:
        if key in task:
            path = task[key] if isinstance(task[key], str) else task[key]["file"]
            return ("tasks", render(path, {}, lambda _name, *terms, **_kw: terms[0]))
    return ()


def require_gate(core: str, start: tuple, values: dict) -> tuple | None:
    """
    Args:
        core: the text of the role's ``tasks/00_core.yml``.
        start: the include that starts the service, ``("role", name,
            tasks_from)`` or ``("tasks", path)``.
        values: the variables the gate reads.

    Returns:
        Whether the store's ``require.yml`` runs and the entries it requires,
        or None when the role includes it after the start or not at all.
    """
    tasks = load_yaml_str(core)
    targets = [target(task) for task in tasks]
    if REQUIRE not in targets or start not in targets[targets.index(REQUIRE) :]:
        return None
    task = tasks[targets.index(REQUIRE)]
    when = task.get("when", [])
    conditions = when if isinstance(when, list) else [when]
    runs = all(
        render("{{ " + condition + " }}", values, no_lookup, native=True)
        for condition in conditions
    )
    required = render(task["vars"]["models_required"], values, no_lookup, native=True)
    return runs, required


def compose_volumes(compose: str, values: dict) -> list:
    """
    Args:
        compose: the role's compose template.
        values: the variables it reads.

    Returns:
        The ``extra_volumes`` of every ``container_volumes`` lookup the
        rendered compose file makes.
    """
    handed = []

    def lookup(name, *_terms, **kwargs):
        if name == "container_volumes":
            handed.append(kwargs.get("extra_volumes"))
        return ""

    render(compose, values, lookup)
    return handed


def env_entries(env: str, values: dict) -> dict[str, str]:
    """
    Args:
        env: the role's env template.
        values: the variables it reads.

    Returns:
        Each ``KEY=value`` line of the rendered env file.
    """
    rendered = render(env, values, no_lookup)
    return dict(line.split("=", 1) for line in rendered.splitlines() if "=" in line)


def command_argv(dockerfile: str, program: str, env: dict[str, str]) -> list[str]:
    """Args:
        dockerfile: text of the Dockerfile.
        program: the binary the CMD execs.
        env: the container environment.

    Returns:
        The arguments the CMD hands to the program.
    """
    (command,) = [
        json.loads(arguments)
        for keyword, arguments in dockerfile_instructions(dockerfile)
        if keyword == "CMD"
    ]
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir, log = Path(tmp) / "bin", Path(tmp) / "argv"
        bin_dir.mkdir()
        (bin_dir / program).write_text(ARGV_STUB, encoding="utf-8")
        (bin_dir / program).chmod(0o755)
        subprocess.run(
            command,
            env={
                **env,
                "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "STUB_LOG": str(log),
            },
            capture_output=True,
            text=True,
            check=True,
        )
        written = log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
    return written.splitlines()


def engine_findings(role: str, spec: dict, texts: dict[str, str]) -> list[str]:
    """Args:
        role: the engine role.
        spec: its entry in ``ENGINES``.
        texts: its sources, see ``sources``.

    Returns:
        One line per broken promise, prefixed by the manifest state.
    """
    prefix = spec["prefix"]
    source, field = spec["source"]
    mounts_name = f"{prefix}_STORE_MOUNTS"
    found = []
    for stored in (True, False):
        state = "stored" if stored else "unstored"
        values = resolve(
            role,
            texts["vars"],
            (f"{prefix}_ARTEFACTS", f"{prefix}_STORED", source, mounts_name),
            spec["fakes"],
            {"model": ENTRY} if stored else {},
        )
        gate = require_gate(texts["core"], spec["start"], values)
        if gate != (stored, [ENTRY] if stored else []):
            found.append(f"{state}: the store's require.yml gate is {gate!r}")
        mounts = [MOUNT] if stored else []
        if values[mounts_name] != mounts:
            found.append(f"{state}: the store mount is {values[mounts_name]!r}")
        if compose_volumes(texts["compose"], values) != [mounts]:
            found.append(f"{state}: the compose file does not mount {mounts!r}")
        env = env_entries(texts["env"], values)
        switches = sorted(key for key in OFFLINE if env.get(key) == "1")
        if switches != sorted(spec["offline"] if stored else ()):
            found.append(f"{state}: the offline switches are {switches}")
        if not stored:
            continue
        model = str(PurePosixPath(STORE, ENTRY[field]))
        if values[source] != model or env.get(spec["env"]) != model:
            found.append(f"stored: {spec['env']} is {env.get(spec['env'])!r}")
        if "program" in spec:
            argv = command_argv(texts["dockerfile"], spec["program"], env)
            handed = (
                argv[argv.index("--model-file") + 1] if "--model-file" in argv else ""
            )
            if handed != model:
                found.append(f"stored: the image hands {handed!r} to the engine")
    return found


class TestEngineGates(unittest.TestCase):
    def test_every_engine_reads_the_store_offline_behind_its_manifest_gate(
        self,
    ) -> None:
        for role, spec in ENGINES.items():
            with self.subTest(role=role):
                self.assertEqual(engine_findings(role, spec, sources(role)), [])

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
                texts = sources(role)
                texts["env"] = "TRANSFORMERS_OFFLINE=1\n" + texts["env"]
                texts["vars"] = texts["vars"].replace(":ro']", "']")
                self.assertEqual(
                    {
                        "unstored: the offline switches are ['TRANSFORMERS_OFFLINE']",
                        f"stored: the store mount is ['{STORE}:{STORE}']",
                    }
                    - set(engine_findings(role, spec, texts)),
                    set(),
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
