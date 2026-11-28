from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

HOOKS = PROJECT_ROOT / "roles/web-app-n8n/files/javascript/hooks.js"
REFUSAL = re.compile(
    r"if \(claims\.email_verified !== true \|\| !subject\) \{.*?"
    r"res\.statusCode = 403;.*?return;\s*\}",
    re.DOTALL,
)
SUBJECT_LOOKUP = (
    "AuthIdentityRepo.findOne({ where: { providerId: subject, "
    "providerType: identityProvider } })"
)
EMAIL_FIND = re.compile(r"return UserRepo\.findOne\(\{ where: \{ email")


def refuses_unverified_email(source: str) -> bool:
    """Whether the hook refuses a sign-in before it looks an account up.

    Args:
        source: the text of ``hooks.js``.
    """
    refusal = REFUSAL.search(source)
    lookup = source.find("await findSsoUser(")
    return refusal is not None and 0 <= refusal.end() < lookup


def finds_accounts_by_subject(source: str) -> bool:
    """Whether the hook resolves an SSO account by subject and never by email.

    Args:
        source: the text of ``hooks.js``.
    """
    return SUBJECT_LOOKUP in source and EMAIL_FIND.search(source) is None


class TestN8nSsoAccountLinking(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read_text(str(HOOKS))

    def test_an_unverified_email_is_refused_before_any_account_lookup(self) -> None:  # nocheck: test.text-presence -- order analyzer of the hook, mutation-tested below  # fmt: skip
        self.assertTrue(refuses_unverified_email(self.source))

    def test_an_account_is_found_by_its_subject_never_by_email(self) -> None:  # nocheck: test.text-presence -- lookup analyzer of the hook, mutation-tested below  # fmt: skip
        self.assertTrue(finds_accounts_by_subject(self.source))


class TestN8nSsoAccountLinkingNegativeControls(unittest.TestCase):
    def setUp(self) -> None:
        self.source = read_text(str(HOOKS))

    def test_a_hook_without_the_verified_check_fails(self) -> None:
        mutated = self.source.replace("claims.email_verified !== true || ", "")
        self.assertFalse(refuses_unverified_email(mutated))

    def test_a_check_after_the_lookup_fails(self) -> None:
        refusal = REFUSAL.search(self.source).group(0)
        lookup = "let user = await findSsoUser(username, subject);"
        mutated = self.source.replace(refusal, "").replace(
            lookup, f"{lookup}\n{refusal}"
        )
        self.assertFalse(refuses_unverified_email(mutated))

    def test_a_lookup_by_email_fails(self) -> None:
        mutated = self.source.replace(
            "          return null;\n        };",
            "          return UserRepo.findOne({ where: { email: username } });\n        };",
        )
        self.assertNotEqual(self.source, mutated)
        self.assertFalse(finds_accounts_by_subject(mutated))


if __name__ == "__main__":
    unittest.main()
