import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_RULE = "persona-block-rationale"
_FLAG_RE = re.compile(r"^\s*PERSONA_[A-Z0-9_]+_BLOCKED\s*=\s*(?!false\s*$)\S")


class TestPersonaBlockRationale(unittest.TestCase):
    def test_every_persona_block_states_its_reason(self):
        """
        Every ``PERSONA_*_BLOCKED`` flag MUST carry a
        ``# nocheck: persona-block-rationale — <reason>`` line directly
        above it.

        The contract is docs/contributing/artefact/files/role/playwright.specs.js.md:
        blocking a persona removes the only end-to-end proof that the role's
        auth chain works, so the trade has to name the role property that
        forces it. Five roles audited in one sweep turned out to block for
        five different reasons -- a login id that is an e-mail rather than a
        username, a database superuser, a built-in root account, a CLI that
        never sets a password, an LDAP bind DN. Left unstated they all read
        as the same shrug.

        The reason belongs on the flag, not only in the README, because that
        is where the next person reads it before flipping the flag back.

        A literal ``=false`` blocks nothing and needs no justification; the
        sso-conditional ternary does, because it blocks in every variant
        that pins ``sso.enabled: false``.
        """
        roles_dir = PROJECT_ROOT / "roles"
        self.assertTrue(
            roles_dir.is_dir(), f"'roles' directory not found at: {roles_dir}"
        )

        offenders: list[str] = []
        for env_path in sorted(roles_dir.glob(f"*/{ENV_TEMPLATE_REL}")):
            lines = read_text(str(env_path)).splitlines()
            rel = env_path.relative_to(PROJECT_ROOT).as_posix()
            for idx, line in enumerate(lines, 1):
                if not _FLAG_RE.match(line):
                    continue
                if is_suppressed_at(lines, idx, _RULE, mode="line-above"):
                    continue
                offenders.append(f"{rel}:{idx}: {line.strip()}")

        if offenders:
            self.fail(
                f"PERSONA_*_BLOCKED without a '# nocheck: {_RULE} — <reason>' "
                f"line directly above:\n  - " + "\n  - ".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
