from __future__ import annotations

import re
import unittest
import unittest.mock as mock

from cli.administration.inventory.validate import open_subtrees, variables
from cli.meta.ci.iterate import plan
from cli.meta.ci.iterate.catalog import Catalog
from cli.meta.ci.iterate.classify import LINT_SUITE, SEED, TESTS, classify
from cli.meta.ci.iterate.equivalence import DEPLOY_READ_RULES
from cli.meta.ci.iterate.symbols import Index
from utils.cache.files import PROJECT_ROOT, read_text
from utils.licensing import roles as licensing
from utils.roles import header_trust
from utils.roles.mapping import (
    ROLE_FILE_META_INFO,
    ROLE_FILE_META_LICENSE,
    ROLE_FILE_META_SERVICES,
)

INDEX = Index(PROJECT_ROOT)
WORDPRESS = f"roles/web-app-wordpress/{ROLE_FILE_META_SERVICES}"
MARKED = (
    (WORDPRESS, open_subtrees.RULE),
    (f"roles/svc-swarm-manager/{ROLE_FILE_META_LICENSE}", licensing.RULE),
    ("roles/web-app-kix/templates/kix-proxy.default.conf.j2", header_trust._RULE),
)
LINT_ONLY = (f"roles/web-app-keycloak/{ROLE_FILE_META_INFO}", "info-media")
OPEN_SUBTREE_TEST = (
    "tests/unit/python/cli/administration/inventory/validate/test_open_subtrees.py"
)


def _drop(path: str, rule: str) -> tuple[str, str]:
    old = read_text(str(PROJECT_ROOT / path))
    return old, re.sub(rf"[ \t]*#\s*nocheck:\s*{re.escape(rule)}[^\n]*", "", old)


def _classify(path: str, old: str, new: str):
    return classify(path, lambda p: (old, new), INDEX, lambda p: True)


class TestDeployReadMarkers(unittest.TestCase):
    def test_every_reader_outside_a_lint_is_a_read_comment(self) -> None:
        readers = {
            open_subtrees.RULE,
            variables._RULE,
            header_trust._RULE,
            licensing.RULE,
        }
        self.assertEqual(readers, set(DEPLOY_READ_RULES))

    def test_dropping_a_real_marker_seeds_its_role(self) -> None:
        for path, rule in MARKED:
            with self.subTest(path=path):
                old, new = _drop(path, rule)
                self.assertNotEqual(old, new)
                change = _classify(path, old, new)
                self.assertEqual(
                    (change.effect, change.roles, change.format_only),
                    (SEED, (path.split("/")[1],), False),
                )

    def test_negative_control_a_lint_only_marker_runs_the_lint_suite(self) -> None:
        path, rule = LINT_ONLY
        old, new = _drop(path, rule)
        self.assertNotEqual(old, new)
        change = _classify(path, old, new)
        self.assertEqual(
            (change.effect, change.tests, change.format_only),
            (TESTS, (LINT_SUITE,), True),
        )

    def test_open_subtree_edit_runs_the_validator_test_that_reads_it(self) -> None:
        old, new = _drop(WORDPRESS, open_subtrees.RULE)
        catalog = Catalog()
        with mock.patch.object(
            catalog, "free_bytes", side_effect=RuntimeError("no daemon")
        ):
            result = plan.build(
                [WORDPRESS],
                [_classify(WORDPRESS, old, new)],
                catalog,
                loop="",
                disable="",
                timings="",
            )
        self.assertIn(OPEN_SUBTREE_TEST, result["tiers"]["T0"]["tests"])


if __name__ == "__main__":
    unittest.main()
