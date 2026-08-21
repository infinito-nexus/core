import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

_REL = "plugins/lookup/role_templates_expanded.py"
_APP = "web-app-demo"


def _load_module():
    path = PROJECT_ROOT / _REL
    spec = importlib.util.spec_from_file_location("role_templates_expanded", str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


MODULE = _load_module()


class _Tree:
    """A throwaway repo root holding `roles/<app>/templates/<names>`."""

    def __init__(self, *names: str):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        templates = self.root / "roles" / _APP / "templates"
        templates.mkdir(parents=True)
        for name in names:
            if name.endswith("/"):
                (templates / name.rstrip("/")).mkdir()
            else:
                (templates / name).write_text("x")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()


def _run(entries, tree):
    with patch.object(MODULE, "PROJECT_ROOT", tree.root):
        return MODULE.LookupModule().run([_APP, entries])[0]


class TestRoleTemplatesExpanded(unittest.TestCase):
    def test_a_glob_entry_without_notify_gets_the_compose_up_handler(self) -> None:
        with _Tree("a.conf.j2") as tree:
            out = _run([{"src_glob": "*.conf.j2", "dest_dir": "/opt/x"}], tree)
        self.assertEqual([item["notify"] for item in out], [["compose-up"]])

    def test_a_pass_through_entry_without_notify_gets_it_too(self) -> None:
        with _Tree() as tree:
            out = _run([{"src": "a.j2", "dest": "/opt/x/a"}], tree)
        self.assertEqual(out[0]["notify"], ["compose-up"])

    def test_dest_drops_the_j2_suffix_and_one_trailing_slash(self) -> None:
        with _Tree("a.conf.j2") as tree:
            out = _run([{"src_glob": "*.conf.j2", "dest_dir": "/opt/x/"}], tree)
        self.assertEqual(out[0]["dest"], "/opt/x/a.conf")

    def test_matches_are_sorted_and_directories_are_not_matched(self) -> None:
        with _Tree("b.j2", "a.j2", "c.j2/") as tree:
            out = _run([{"src_glob": "*.j2", "dest_dir": "/opt/x"}], tree)
        self.assertEqual([Path(item["src"]).name for item in out], ["a.j2", "b.j2"])

    def test_explicit_values_beat_the_defaults_on_both_paths(self) -> None:
        with _Tree("a.j2") as tree:
            globbed = _run(
                [
                    {
                        "src_glob": "*.j2",
                        "dest_dir": "/opt/x",
                        "mode": "0600",
                        "notify": ["container-recreate"],
                    }
                ],
                tree,
            )
            passed = _run([{"src": "s", "dest": "d", "owner": "www-data"}], tree)
        self.assertEqual(globbed[0]["mode"], "0600")
        self.assertEqual(globbed[0]["notify"], ["container-recreate"])
        self.assertEqual(passed[0]["owner"], "www-data")

    def test_an_explicit_empty_notify_is_kept_and_not_refilled(self) -> None:
        with _Tree("a.j2") as tree:
            globbed = _run(
                [{"src_glob": "*.j2", "dest_dir": "/opt/x", "notify": []}], tree
            )
            passed = _run([{"src": "s", "dest": "d", "notify": []}], tree)
        self.assertEqual(globbed[0]["notify"], [])
        self.assertEqual(passed[0]["notify"], [])

    def test_a_false_condition_survives_the_defaulting(self) -> None:
        with _Tree("a.j2") as tree:
            out = _run(
                [{"src_glob": "*.j2", "dest_dir": "/opt/x", "condition": False}], tree
            )
        self.assertIs(out[0]["condition"], False)

    def test_the_glob_keys_do_not_leak_into_the_rendered_spec(self) -> None:
        with _Tree("a.j2") as tree:
            out = _run([{"src_glob": "*.j2", "dest_dir": "/opt/x"}], tree)
        self.assertNotIn("src_glob", out[0])
        self.assertNotIn("dest_dir", out[0])

    def test_a_glob_matching_nothing_contributes_no_entry(self) -> None:
        with _Tree("a.j2") as tree:
            out = _run([{"src_glob": "*.absent", "dest_dir": "/opt/x"}], tree)
        self.assertEqual(out, [])

    def test_a_glob_entry_without_dest_dir_is_rejected(self) -> None:
        with _Tree("a.j2") as tree, self.assertRaises(AnsibleError):
            _run([{"src_glob": "*.j2"}], tree)

    def test_wrong_term_count_and_bad_shapes_are_rejected(self) -> None:
        with _Tree() as tree, patch.object(MODULE, "PROJECT_ROOT", tree.root):
            with self.assertRaises(AnsibleError):
                MODULE.LookupModule().run([_APP])
            with self.assertRaises(AnsibleError):
                MODULE.LookupModule().run(["", []])
            with self.assertRaises(AnsibleError):
                MODULE.LookupModule().run([_APP, "not-a-list"])
            with self.assertRaises(AnsibleError):
                MODULE.LookupModule().run([_APP, ["not-a-dict"]])

    def test_no_templates_at_all_yields_an_empty_list(self) -> None:
        with _Tree() as tree, patch.object(MODULE, "PROJECT_ROOT", tree.root):
            self.assertEqual(MODULE.LookupModule().run([_APP, None])[0], [])


if __name__ == "__main__":
    unittest.main()
