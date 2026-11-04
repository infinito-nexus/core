import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.i18n.extract import core_messages, rbac_context, rbac_messages, role_messages
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_META_RBAC


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
                    glyph: 𓏴
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
                    children:
                      Forums:
                        description: " Boards to discuss "
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
            _write(
                root,
                "roles/sys-svc-app-control/files/paused_i18n.yml",
                """\
                title: " Service paused "
                """,
            )
            _write(
                root,
                "roles/sys-front-inj-javascript/files/profile_lock_i18n.yml",
                """\
                locked: " Managed by your central account. "
                """,
            )
            _write(
                root,
                "roles/web-svc-access-request/files/access_request_i18n.yml",
                """\
                form_title: " Request access "
                """,
            )
            _write(
                root,
                f"roles/web-app-wiki/{ROLE_FILE_META_RBAC}",
                """\
                roles:
                  editor:
                    description: " Edits pages "
                  reader: {}
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
                ("menu:Forums:title", "Forums"),
                ("menu:Forums:description", "Boards to discuss"),
                ("logout:counter", "{done} of {total} services signed out"),
                ("paused:title", "Service paused"),
                ("profile_lock:locked", "Managed by your central account."),
                ("access_request:form_title", "Request access"),
                ("rbac:web-app-wiki:editor:description", "Edits pages"),
            ],
        )

    def test_role_descriptions_use_the_context_the_service_looks_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                f"roles/web-app-wiki/{ROLE_FILE_META_RBAC}",
                "roles:\n  editor:\n    description: Edits pages\n",
            )
            _write(
                root,
                f"roles/web-app-cst-demo/{ROLE_FILE_META_RBAC}",
                "roles:\n  editor:\n    description: Custom\n",
            )

            messages = rbac_messages(root)

        self.assertEqual(
            messages, [(rbac_context("web-app-wiki", "editor"), "Edits pages")]
        )
        self.assertEqual(
            "rbac:web-app-wiki:editor:description",
            rbac_context("web-app-wiki", "editor"),
        )

    def test_a_pulled_custom_role_stays_out_of_the_core_catalogs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root,
                f"roles/web-app-wiki/{ROLE_FILE_META_MAIN}",
                "galaxy_info:\n  description: A wiki\n",
            )
            _write(
                root,
                f"roles/web-app-cst-demo/{ROLE_FILE_META_MAIN}",
                "galaxy_info:\n  description: A custom app\n",
            )

            messages = role_messages(root)

        self.assertEqual(messages, [("role:web-app-wiki:description", "A wiki")])


if __name__ == "__main__":
    unittest.main()
