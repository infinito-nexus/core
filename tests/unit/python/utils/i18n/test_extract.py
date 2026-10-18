import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.i18n.extract import core_messages
from utils.roles.mapping import ROLE_FILE_META_MAIN


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class TestCoreMessages(unittest.TestCase):
    def test_every_source_yields_messages_under_its_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                f"roles/web-app-wiki/{ROLE_FILE_META_MAIN}",
                """\
                galaxy_info:
                  description: " A wiki "
                """,
            )
            _write(
                root, f"roles/web-app-plain/{ROLE_FILE_META_MAIN}", "galaxy_info: {}\n"
            )
            _write(
                root,
                "meta/categories.yml",
                """\
                roles:
                  web:
                    title: Web
                    hanzi: 网络
                    app:
                      title: Applications
                      description: Apps for users
                      invokable: true
                """,
            )
            _write(
                root,
                "roles/web-app-dashboard/vars/menu_categories.yml",
                """\
                portfolio_menu_categories:
                  Community:
                    description: Tools to manage the community
                    tags: [forum]
                """,
            )
            _write(
                root,
                "roles/web-app-keycloak/files/logout_i18n.yml",
                """\
                counter: "{done} of {total} services signed out"
                """,
            )

            messages = core_messages(root)

        self.assertEqual(
            messages,
            [
                ("role:web-app-wiki:description", "A wiki"),
                ("category:web:title", "Web"),
                ("category:web.app:title", "Applications"),
                ("category:web.app:description", "Apps for users"),
                ("menu:Community:title", "Community"),
                ("menu:Community:description", "Tools to manage the community"),
                ("logout:counter", "{done} of {total} services signed out"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
