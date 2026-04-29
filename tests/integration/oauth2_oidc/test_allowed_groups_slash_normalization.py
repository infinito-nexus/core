"""Guard: oauth2-proxy `allowed_groups` MUST be normalized to a leading-slash
path so it lines up with what Keycloak actually emits in the JWT groups claim.

Background
----------
oauth2-proxy compares each item in `allowed_groups` to each entry in the JWT
`groups` claim by literal string equality. Keycloak's group-membership-mapper
emits paths with a leading slash whenever `full.path=true` (the realm-import
default for the shared `groups` client-scope, see
roles/web-app-keycloak/templates/import/components/...).

The `rbac_group_path` lookup, by historical contract pinned in
tests/unit/plugins/lookup/test_rbac_group_path.py, returns paths WITHOUT a
leading slash (e.g. `roles/web-app-yourls/administrator`). Plugging that
value straight into oauth2-proxy's `allowed_groups` produces a silent literal
mismatch — the `/oauth2/callback` request gets HTTP 403 with
`[AuthFailure] Invalid authentication via OAuth2: unauthorized` and the user
never reaches the upstream app. This is exactly what tripped the
`web-app-yourls` Playwright spec on iter 2.

This guard pins the cheapest fix at the SPOT that bridges the contract
mismatch: the oauth2-proxy template normalises every entry to exactly one
leading slash via `regex_replace('^/*', '/')`. If a future refactor drops
the normalisation (or changes the rbac_group_path contract to emit a leading
slash, in which case this normalisation becomes a no-op anchor), this test
trips so the operator gets a fast signal.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TEMPLATE_PATH = os.path.join(
    REPO_ROOT,
    "roles",
    "web-app-oauth2-proxy",
    "templates",
    "oauth2-proxy-keycloak.cfg.j2",
)

# Match an `allowed_groups = ...` line whose value pipeline includes the
# slash-normalising regex_replace. Whitespace is permissive so cosmetic
# reformats don't break the guard.
ALLOWED_GROUPS_NORMALISED = re.compile(
    r"allowed_groups\s*=\s*\{\{[^}]*"
    r"map\(\s*['\"]regex_replace['\"]\s*,\s*"
    r"['\"]\^/\*['\"]\s*,\s*['\"]/['\"]\s*\)"
    r"[^}]*\}\}",
    re.DOTALL,
)


class TestAllowedGroupsSlashNormalization(unittest.TestCase):
    def test_template_normalises_allowed_groups_with_leading_slash(self):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertRegex(
            content,
            ALLOWED_GROUPS_NORMALISED,
            msg=(
                "oauth2-proxy-keycloak.cfg.j2 must normalise `allowed_groups` "
                "to a leading-slash path via `map('regex_replace', '^/*', "
                "'/')`. Without that filter, oauth2-proxy literal-matches "
                "`roles/<app>/...` against Keycloak's emit "
                "`/roles/<app>/...` and rejects the user with a 403 at "
                "/oauth2/callback (see "
                "docs/contributing/design/iam/rbac.md and the iter-2 "
                "regression that prompted this guard)."
            ),
        )


if __name__ == "__main__":
    unittest.main()
