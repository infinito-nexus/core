"""A caller's block ``when`` must not reach a role that rebinds ``application_id``.

Ansible hands the ``when`` of a block down to every task of a role an
``include_role`` inside that block loads, and evaluates it there. A role whose
``tasks/main.yml`` rebinds ``application_id`` (svc-ai-models pins its own id)
then evaluates the caller's gate under the callee's id: svc-ai-s1's
``S1_STORED`` looked up ``services.s1.flavor`` of svc-ai-models and failed the
deploy, while the gates of the other model-store callers silently read the
manifest of svc-ai-models instead of their own. A ``when`` on the include task
itself stays with the include. These cases run real Ansible: the first ones
reproduce both hazards so the fixed pattern cannot pass vacuously.
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml, load_yaml_all

from . import PROJECT_ROOT

INCLUDES = (
    "include_role",
    "ansible.builtin.include_role",
    "import_role",
    "ansible.builtin.import_role",
)
STATIC = ("import_role", "ansible.builtin.import_role")
TASK_INCLUDES = (
    "include_tasks",
    "ansible.builtin.include_tasks",
    "import_tasks",
    "ansible.builtin.import_tasks",
)
SECTIONS = ("block", "rescue", "always")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
OWN_ID = "application_id"

CALLER_VARS = {
    "CALLER_ARTEFACTS": "{{ manifest[application_id] }}",
    "CALLER_FLAVOR": "{{ flavors[application_id] }}",
    "CALLER_STORED": "{{ (CALLER_ARTEFACTS | length > 0) and CALLER_FLAVOR != 'laya' }}",
}
REQUIRE_VARS = {
    "models_consumer": "{{ application_id }}",
    "models_required": "{{ CALLER_ARTEFACTS }}",
}
SEED = {"ansible.builtin.include_role": {"name": "store"}}
REQUIRE = {
    "ansible.builtin.include_role": {
        "name": "store",
        "tasks_from": "utils/require.yml",
    },
    "vars": REQUIRE_VARS,
}
CALLERS = {
    "blocked": [
        {
            "when": "CALLER_STORED | bool",
            "block": [SEED | {"when": "run_once_store is not defined"}, REQUIRE],
        }
    ],
    "flat": [
        SEED | {"when": ["CALLER_STORED | bool", "run_once_store is not defined"]},
        REQUIRE | {"when": "CALLER_STORED | bool"},
    ],
}
STORE = {
    "vars/main.yml": {OWN_ID: "store"},
    "tasks/main.yml": [
        {
            "include_tasks": "00_core.yml",
            "when": "run_once_store is not defined",
            "vars": {OWN_ID: "store"},
        }
    ],
    "tasks/00_core.yml": [
        {"ansible.builtin.set_fact": {"run_once_store": True}},
        {
            "ansible.builtin.copy": {
                "dest": "{{ out }}/seeded",
                "content": "{{ application_id }}",
                "mode": "0644",
            }
        },
    ],
    "tasks/utils/require.yml": [
        {
            "ansible.builtin.copy": {
                "dest": "{{ out }}/required",
                "content": "{{ models_consumer }}={{ models_required | join(',') }}",
                "mode": "0644",
            }
        }
    ],
}
PLAY = [
    {
        "hosts": "localhost",
        "gather_facts": False,
        "connection": "local",
        "tasks": [
            {
                "name": "Load the caller the way tasks/utils/load/app.yml does",
                "ansible.builtin.include_role": {"name": "{{ caller }}"},
                "vars": {OWN_ID: "{{ caller }}"},
                "when": "not (bare | bool)",
            },
            {
                "name": "Load the caller's core with nothing pinning its id",
                "ansible.builtin.include_role": {
                    "name": "{{ caller }}",
                    "tasks_from": "00_core.yml",
                },
                "when": "bare | bool",
            },
        ],
    }
]
FLAVORS = {"blocked": "torch", "flat": "torch"}
STORE_DECLARES = {"blocked": ["b1"], "flat": ["f1"], "store": ["s1"]}
STORE_DECLARES_NOTHING = STORE_DECLARES | {"store": []}
RUNS = {
    "ci_blocked": ("blocked", STORE_DECLARES, False),
    "ci_flat": ("flat", STORE_DECLARES, False),
    "silent_blocked": ("blocked", STORE_DECLARES_NOTHING, False),
    "silent_flat": ("flat", STORE_DECLARES_NOTHING, False),
    "bare_flat": ("flat", STORE_DECLARES, True),
}


def _fixture(root: Path) -> None:
    """Write the callee ``store`` and both callers under ``root/roles``.

    Args:
        root: an empty directory.
    """
    for relative, body in STORE.items():
        dump_yaml(root / "roles" / "store" / relative, body)
    for caller, core in CALLERS.items():
        base = root / "roles" / caller
        dump_yaml(base / "vars" / "main.yml", {OWN_ID: caller} | CALLER_VARS)
        dump_yaml(
            base / "tasks" / "main.yml",
            [
                {
                    "include_tasks": "00_core.yml",
                    "when": f"run_once_{caller} is not defined",
                    "vars": {OWN_ID: caller},
                }
            ],
        )
        dump_yaml(base / "tasks" / "00_core.yml", core)
    dump_yaml(root / "play.yml", PLAY)


def _play(root: Path, run: str) -> dict[str, Any]:
    """Run the play for one case of ``RUNS`` in its own output directory.

    Args:
        root: the directory ``_fixture`` filled.
        run: a key of ``RUNS``.

    Returns:
        ``rc``, the combined ``output``, and ``seeded`` / ``required``: what the
        callee wrote, None where it wrote nothing.
    """
    caller, manifest, bare = RUNS[run]
    out = root / "out" / run
    out.mkdir(parents=True)
    extra = {
        "out": str(out),
        "caller": caller,
        "bare": bare,
        "manifest": manifest,
        "flavors": FLAVORS,
    }
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            "localhost,",
            str(root / "play.yml"),
            "-e",
            json.dumps(extra),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "rc": result.returncode,
        "output": result.stdout + result.stderr,
        **{
            name: read_text(str(out / name)) if (out / name).is_file() else None
            for name in ("seeded", "required")
        },
    }


def _when(task: dict[str, Any]) -> list[str]:
    value = task.get("when")
    if isinstance(value, list):
        return [str(item) for item in value]
    return [] if value in (None, "") or isinstance(value, bool) else [str(value)]


def _tasks(path: Path) -> list[Any]:
    docs = load_yaml_all(path, default_if_missing=[])
    return [task for doc in docs if isinstance(doc, list) for task in doc]


def _names(path: Path) -> set[str]:
    docs = load_yaml_all(path, default_if_missing=[])
    return {key for doc in docs if isinstance(doc, dict) for key in doc}


def _every_task(tasks: list[Any]) -> Iterator[dict[str, Any]]:
    for task in tasks:
        if isinstance(task, dict):
            yield task
            for section in SECTIONS:
                yield from _every_task(task.get(section) or [])


def _includes(
    tasks: list[Any], guards: tuple[str, ...] = ()
) -> Iterator[tuple[dict[str, Any], dict[str, Any], tuple[str, ...]]]:
    """Yield every role include with the block guards that reach its tasks.

    Args:
        tasks: a parsed tasks file.
        guards: the ``when`` of the enclosing blocks.

    Returns:
        ``(include args, include vars, guards)`` per include; an import adds
        its own ``when`` because a static import hands it down too.
    """
    for task in tasks:
        if not isinstance(task, dict):
            continue
        for key in INCLUDES:
            if isinstance(task.get(key), dict):
                own = tuple(_when(task)) if key in STATIC else ()
                yield task[key], task.get("vars") or {}, guards + own
        inner = guards + tuple(_when(task)) if "block" in task else guards
        for section in SECTIONS:
            yield from _includes(task.get(section) or [], inner)


def _rebinds(root: Path, role: str, tasks_from: str) -> tuple[bool, bool]:
    """Tell where the included tasks file rebinds ``application_id``.

    Args:
        root: a tree holding ``roles/``.
        role: the included role.
        tasks_from: its tasks file.

    Returns:
        ``(anywhere, own)``: a rebinding on any task, and one on a task
        include that keeps running the role itself. A block guard reaches
        every nested include, while include vars reach a nested role only
        until it binds its own values.
    """
    path = root / "roles" / role / "tasks" / tasks_from
    rebinding = [
        task for task in _every_task(_tasks(path)) if OWN_ID in (task.get("vars") or {})
    ]
    own = any(key in task for task in rebinding for key in TASK_INCLUDES)
    return bool(rebinding), own


def _leaks(root: Path) -> list[str]:
    """Find caller-scoped expressions that reach a role rebinding application_id.

    Args:
        root: a tree holding ``roles/``.

    Returns:
        One line per include whose enclosing block guards (or Jinja include
        vars) name a variable of the caller's ``vars/main.yml`` or
        ``application_id`` while the included tasks file rebinds
        ``application_id`` (for include vars: rebinds it for itself).
    """
    found = []
    for path in sorted(root.glob("roles/*/tasks/**/*.yml")):
        caller = path.relative_to(root).parts[1]
        scope = {OWN_ID, *_names(root / "roles" / caller / "vars" / "main.yml")}
        for include, variables, guards in _includes(_tasks(path)):
            role = str(include.get("name", ""))
            tasks_from = str(include.get("tasks_from") or "main.yml")
            if "{{" in role:
                continue
            anywhere, own = _rebinds(root, role, tasks_from)
            texts = [*guards] if anywhere else []
            if own:
                texts += [str(v) for v in variables.values() if "{{" in str(v)]
            leaked = sorted(scope.intersection(NAME.findall(" ".join(texts))))
            if leaked:
                found.append(
                    f"{path.relative_to(root)}: {role}/{tasks_from} evaluates {leaked} under its own id"
                )
    return found


class TestBlockWhenStaysInCaller(unittest.TestCase):
    observed: ClassVar[dict[str, dict[str, Any]]] = {}
    fixture_leaks: ClassVar[list[str]] = []

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _fixture(root)
            cls.fixture_leaks = _leaks(root)
            if shutil.which("ansible-playbook"):
                cls.observed = {run: _play(root, run) for run in RUNS}

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_block_gate_fails_inside_the_callee_like_svc_ai_s1(self) -> None:
        run = self.observed["ci_blocked"]
        self.assertNotEqual(run["rc"], 0, run["output"])
        for needle in (
            "store : include_tasks",
            "roles/blocked/tasks/00_core.yml",
            "when: CALLER_STORED | bool",
        ):
            self.assertIn(needle, run["output"])
        self.assertIsNone(run["seeded"])

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_block_gate_silently_skips_the_seed_on_the_callees_manifest(self) -> None:
        run = self.observed["silent_blocked"]
        self.assertEqual(run["rc"], 0, run["output"])
        self.assertIsNone(run["seeded"])
        self.assertEqual(run["required"], "blocked=b1")

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_a_gate_on_the_include_seeds_and_requires_the_callers_artefacts(
        self,
    ) -> None:
        for run in ("ci_flat", "silent_flat"):
            with self.subTest(run=run):
                observed = self.observed[run]
                self.assertEqual(observed["rc"], 0, observed["output"])
                self.assertEqual(observed["seeded"], "store")
                self.assertEqual(observed["required"], "flat=f1")

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
    def test_include_vars_resolve_under_the_callers_pin_only(self) -> None:
        run = self.observed["bare_flat"]
        self.assertEqual(run["rc"], 0, run["output"])
        self.assertEqual(
            run["required"],
            "store=s1",
            "without a pin the callee's own application_id wins; the callers' "
            "main.yml pin is what keeps require.yml on the caller's values",
        )

    def test_the_guard_flags_exactly_the_failing_fixture(self) -> None:
        self.assertEqual(
            self.fixture_leaks,
            [
                (
                    "roles/blocked/tasks/00_core.yml: store/main.yml evaluates "
                    "['CALLER_STORED'] under its own id"
                )
            ],
        )

    def test_no_caller_scoped_gate_reaches_a_role_that_rebinds_its_id(self) -> None:
        self.assertEqual(_leaks(PROJECT_ROOT), [])


if __name__ == "__main__":
    unittest.main()
