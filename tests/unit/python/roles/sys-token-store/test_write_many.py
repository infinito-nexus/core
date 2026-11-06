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
KEEP_OWN = "📌 Keep the writer's own merge over a peer writer's hand-over"
CHANGED = "🧮 Note whether the merge changed the store"
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


def _state(merged: dict, users: dict = USERS) -> dict:
    variables = {"sys_token_store_users_merged": merged, "sys_token_store_users": users}
    changed = _render(
        _task(CHANGED)["ansible.builtin.set_fact"]["sys_token_store_changed"],
        **variables,
    )
    return {**variables, "sys_token_store_changed": changed}


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


def _reader(reader: str, reader_stack_host: str) -> dict:
    return {
        "sys_token_store_reader": reader,
        "hostvars": {reader: {"STACK_HOST": reader_stack_host}},
        "STACK_HOST": "mgr",
    }


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
        state = _state(merged)
        self.assertFalse(_when(PERSIST, **state))
        self.assertFalse(_when(MIRROR, **state))
        self.assertFalse(_when(HAND_OVER, **state))
        self.assertFalse(_when(KEEP_OWN, **state))
        self.assertFalse(
            _when(
                RERENDER,
                sys_token_store_persisted=SKIPPED,
                sys_token_store_mirrored=SKIPPED,
            )
        )

    def test_a_changed_store_is_written_and_rerendered_once(self):
        merged = _merged([_entry("bob", "web-app-b", "token-b")])
        state = _state(merged)
        self.assertTrue(_when(PERSIST, **state))
        self.assertTrue(_when(HAND_OVER, **state, **_reader("wrk", "mgr")))
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

    def test_the_written_store_reaches_only_the_readers_of_its_stack_host(self):
        merged = _merged([_entry("bob", "web-app-b", "token-b")])
        state = _state(merged)
        self.assertTrue(_when(HAND_OVER, **state, **_reader("wrk", "mgr")))
        self.assertFalse(_when(HAND_OVER, **state, **_reader("solo", "solo")))
        hand_over = _task(HAND_OVER)
        self.assertEqual(hand_over["delegate_to"], "{{ sys_token_store_reader }}")
        self.assertIs(hand_over["delegate_facts"], True)

    def test_every_changed_writer_hands_over_its_own_store(self):
        self.assertNotIn("run_once", _task(HAND_OVER))

    def test_every_writer_ends_on_its_own_merge(self):
        names = [task.get("name") for task, _ in _flat("write_many.yml")]
        self.assertGreater(names.index(KEEP_OWN), names.index(HAND_OVER))
        keep_own = _task(KEEP_OWN)
        self.assertEqual(
            keep_own["ansible.builtin.set_fact"],
            {"sys_token_store_users": "{{ sys_token_store_users_merged }}"},
        )
        for keyword in ("delegate_to", "delegate_facts", "run_once", "loop"):
            with self.subTest(keyword=keyword):
                self.assertNotIn(keyword, keep_own)
        merged = _merged([_entry("bob", "web-app-b", "token-b")])
        self.assertTrue(_when(KEEP_OWN, **_state(merged)))

    def test_the_hand_over_outlives_the_writers_own_fact_update(self):
        merged = _merged([_entry("bob", "web-app-b", "token-b")])
        after_writer_item = {**_state(merged), "sys_token_store_users": merged}
        self.assertTrue(_when(HAND_OVER, **after_writer_item, **_reader("wrk", "mgr")))

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
