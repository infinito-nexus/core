from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from utils.cache.files import read_text

from ._semaphore_fake import CHANGELOG, PYTHON_DIR, WORKSPACE_ID, load_workspace


def accepts_empty_targets(module, source):
    """Args:
    module: :func:`load_workspace`, possibly patched.
    source: a core tree with a changelog.

    Returns:
        True when ``apply`` takes an empty ``WORKSPACE_TARGETS`` as a workspace
        without servers.
    """
    env = {
        "WORKSPACE": WORKSPACE_ID,
        "WORKSPACE_ACTION": "apply",
        "WORKSPACE_CORE_VERSION": "latest",
        "WORKSPACE_TARGETS": "",
        "INFINITO_SRC_DIR": str(source),
    }
    try:
        variables = module.operation(env, "/nonexistent/result.json")
    except module.RefusalError:
        return False
    return variables["WORKSPACE_TARGETS"] == []


class WorkspaceOperationTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.src = Path(scratch.name)
        (self.src / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    def test_operation_takes_an_empty_target_list_as_no_servers(self):
        self.assertTrue(accepts_empty_targets(load_workspace(), self.src))

    def test_negative_control_a_refused_empty_list_fails_the_check(self):
        module = load_workspace()
        parse = module.parse_targets

        def refusing(value):
            if not value:
                raise module.RefusalError("WORKSPACE_TARGETS is empty")
            return parse(value)

        with mock.patch.object(module, "parse_targets", refusing):
            self.assertFalse(accepts_empty_targets(module, self.src))


def hostname_pattern_beside(interface_pattern):
    """Args:
    interface_pattern: the ``$defs.host_name`` pattern of a planted
        ``interface.json``.

    Returns:
        The ``HOSTNAME`` pattern a copy of ``workspace.py`` compiles when it sits
        in ``python/`` beside that ``opentofu/interface.json``.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        (root / "python").mkdir()
        (root / "opentofu").mkdir()
        (root / "python" / "workspace.py").write_text(
            read_text(str(PYTHON_DIR / "workspace.py")), "utf-8"
        )
        (root / "opentofu" / "interface.json").write_text(
            json.dumps({"$defs": {"host_name": {"pattern": interface_pattern}}}),
            "utf-8",
        )
        spec = spec_from_file_location(
            "semaphore_workspace_copy", str(root / "python" / "workspace.py")
        )
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.HOSTNAME.pattern


class HostNamePatternTests(unittest.TestCase):
    def test_targets_take_the_host_name_pattern_of_the_interface(self):
        interface = json.loads(
            read_text(str(PYTHON_DIR.parent / "opentofu" / "interface.json"))
        )
        self.assertEqual(
            load_workspace().HOSTNAME.pattern,
            interface["$defs"]["host_name"]["pattern"],
        )

    def test_a_planted_interface_pattern_reaches_the_targets(self):
        self.assertEqual(hostname_pattern_beside("^planted$"), "^planted$")


if __name__ == "__main__":
    unittest.main()
