"""Require ``homepage`` and ``video`` in every invokable role's
``meta/info.yml``.

The root-README roles overview renders a Homepage and a Video column;
a missing entry degrades every consumer-facing role to an empty cell.
Fully self-written roles (backups, host plumbing, ...) have no upstream
product page or demo video: opt them out with the file-level marker

    # nocheck: info-media <reason>

within the first 30 lines of ``meta/main.yml``. The marker lives in
``meta/main.yml`` (always present) rather than ``meta/info.yml`` because
a comment-only ``info.yml`` parses to an empty document, which the
``meta/info.yml`` schema lint rejects.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_INFO, ROLE_FILE_META_MAIN
from utils.roles.validation.invokable import _get_invokable_paths, _is_role_invokable

from . import PROJECT_ROOT

_RULE = "info-media"
_REQUIRED_KEYS = ("homepage", "video")


class TestInfoHomepageVideo(unittest.TestCase):
    def test_invokable_roles_declare_homepage_and_video(self) -> None:
        invokable = _get_invokable_paths()
        findings: list[str] = []
        for role_dir in sorted((PROJECT_ROOT / "roles").iterdir()):
            if not role_dir.is_dir():
                continue
            if not _is_role_invokable(role_dir.name, invokable):
                continue
            main_path = role_dir / ROLE_FILE_META_MAIN
            if main_path.is_file() and is_suppressed_in_head(
                read_text(str(main_path)).splitlines(), _RULE
            ):
                continue
            info_path = role_dir / ROLE_FILE_META_INFO
            info: dict = {}
            if info_path.is_file():
                data = load_yaml_any(str(info_path)) or {}
                if isinstance(data, dict):
                    info = data
            missing = [
                key
                for key in _REQUIRED_KEYS
                if not (isinstance(info.get(key), str) and info[key].strip())
            ]
            if missing:
                findings.append(f"{role_dir.name}: missing {', '.join(missing)}")

        self.assertFalse(
            findings,
            f"{len(findings)} invokable role(s) miss 'homepage' and/or 'video' "
            f"in {ROLE_FILE_META_INFO}. Add the URLs, or opt a fully "
            f"self-written role out with '# nocheck: {_RULE} <reason>' in the "
            f"first 30 lines of {ROLE_FILE_META_MAIN}:\n" + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
