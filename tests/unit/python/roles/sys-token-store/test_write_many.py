from __future__ import annotations

import unittest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.templating.ansible import _trust_as_template

TASKS = PROJECT_ROOT / "roles" / "sys-token-store" / "tasks"
MERGE = "🔨 Build merged structure"
EMPTY = "🛑 Abort if a token is empty (do not persist empties)"
PERSIST = "💾 Persist store (idempotent, single-writer via STACK_HOST)"
MIRROR = "🪞 Mirror the store onto the controller, where every users lookup reads"
HAND_OVER = "🔄 Hand the written store to the lookups of the rest of the play"
RERENDER = "🧊 Re-render the users SPOT the new tokens invalidated"

USERS = {
    "alice": {"tokens": {"web-app-a": "old-a"}, "note": "kept"},
    "carol": {"tokens": {"web-app-c": "token-c"}},
}
SKIPPED = {"changed": False, "skipped": True}


def _tasks(name: str) -> list[dict]:
    return load_yaml_any(str(TASKS / name), default_if_missing=[])


def _conditions(task: dict) -> list[str]:
    if "when" not in task:
        return []
    when = task["when"]
    return when if isinstance(when, list) else [when]


def _walk(tasks: list[dict], gates: list[str]) -> list[tuple[dict, list[str]]]:
    flat = []
    for task in tasks:
        conditions = gates + _conditions(task)
        flat.append((task, conditions))
        if "block" in task:
            flat.extend(_walk(task["block"], conditions))
    return flat


def _flat(name: str) -> list[tuple[dict, list[str]]]:
    return _walk(_tasks(name), [])


def _gated(name: str) -> tuple[dict, list[str]]:
    return next(
        (task, conditions)
        for task, conditions in _flat("write_many.yml")
        if task.get("name") == name
    )


def _task(name: str) -> dict:
    return _gated(name)[0]


def _render(template, **variables):
    templar = Templar(loader=DataLoader(), variables=variables)
    return templar.template(_trust_as_template(template))


def _merged(entries: list[dict], users: dict = USERS) -> dict:
    return _render(
        _task(MERGE)["ansible.builtin.set_fact"]["sys_token_store_users_merged"],
        sys_token_store_entries=entries,
        sys_token_store_users=users,
    )


def _when(name: str, **variables) -> bool:
    conditions = _gated(name)[1]
    if not conditions:
        return True
    return _render(
        "{{ ((" + ") and (".join(conditions) + ")) | bool }}",
        IS_SWARM_MODE=True,
        **variables,
    )


def _entry(user_key: str, app: str, token: str) -> dict:
    return {"user_key": user_key, "app": app, "token": token}


class TestWriteMany(unittest.TestCase):
    def test_every_entry_lands_in_one_merge(self):
        merged = _merged(
            [
                _entry("alice", "web-app-b", " new-b "),
                _entry("alice", "web-app-a", "new-a"),
                _entry("bob", "web-app-b", "token-b"),
            ]
        )
        self.assertEqual(
            merged,
            {
                "alice": {
                    "tokens": {"web-app-a": "new-a", "web-app-b": "new-b"},
                    "note": "kept",
                },
                "bob": {"tokens": {"web-app-b": "token-b"}},
                "carol": {"tokens": {"web-app-c": "token-c"}},
            },
        )

    def test_the_later_entry_of_one_user_and_app_wins(self):
        merged = _merged(
            [_entry("bob", "web-app-b", "first"), _entry("bob", "web-app-b", "second")]
        )
        self.assertEqual(merged["bob"], {"tokens": {"web-app-b": "second"}})

    def test_an_unchanged_store_skips_the_write_and_the_rerender(self):
        merged = _merged(
            [
                _entry("alice", "web-app-a", "old-a"),
                _entry("carol", "web-app-c", "token-c"),
            ]
        )
        self.assertEqual(merged, USERS)
        state = {"sys_token_store_users_merged": merged, "sys_token_store_users": USERS}
        self.assertFalse(_when(PERSIST, **state))
        self.assertFalse(_when(MIRROR, **state))
        self.assertFalse(_when(HAND_OVER, **state))
        self.assertFalse(
            _when(
                RERENDER,
                sys_token_store_persisted=SKIPPED,
                sys_token_store_mirrored=SKIPPED,
            )
        )

    def test_a_changed_store_is_written_and_rerendered_once(self):
        merged = _merged([_entry("bob", "web-app-b", "token-b")])
        state = {"sys_token_store_users_merged": merged, "sys_token_store_users": USERS}
        self.assertTrue(_when(PERSIST, **state))
        self.assertTrue(_when(HAND_OVER, **state))
        self.assertTrue(
            _when(
                RERENDER,
                sys_token_store_persisted={"changed": True},
                sys_token_store_mirrored=SKIPPED,
            )
        )
        rerenders = [
            t for t, _ in _flat("write_many.yml") if "applications_carrier" in t
        ]
        self.assertEqual(len(rerenders), 1)
        self.assertNotIn("loop", rerenders[0])

    def test_the_store_has_one_writer(self):
        persist = _task(PERSIST)
        self.assertEqual(persist["delegate_to"], "{{ STACK_HOST }}")
        self.assertIs(persist["run_once"], True)
        mirror = _task(MIRROR)
        self.assertEqual(mirror["delegate_to"], "localhost")
        self.assertIs(mirror["run_once"], True)

    def test_an_empty_token_is_refused_by_name(self):
        empty = _render(
            _task(EMPTY)["vars"]["sys_token_store_empty"],
            sys_token_store_entries=[
                _entry("alice", "web-app-a", "set"),
                _entry("bob", "web-app-b", "  "),
            ],
        )
        self.assertEqual(empty, ["bob/web-app-b"])


class TestWriteIsAOneEntryBatch(unittest.TestCase):
    def test_the_single_token_contract_feeds_write_many(self):
        tasks = _tasks("write.yml")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["ansible.builtin.import_tasks"], "write_many.yml")
        single = {
            "sys_token_store_user_key": "administrator",
            "sys_token_store_app": "web-app-matomo",
            "sys_token_store_token": "secret-token",
        }
        entries = [
            {field: _render(value, **single) for field, value in entry.items()}
            for entry in tasks[0]["vars"]["sys_token_store_entries"]
        ]
        self.assertEqual(
            entries, [_entry("administrator", "web-app-matomo", "secret-token")]
        )


if __name__ == "__main__":
    unittest.main()
