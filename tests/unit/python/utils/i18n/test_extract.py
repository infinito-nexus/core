import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from utils.cache.files import read_text
from utils.i18n.catalog import build_template
from utils.i18n.extract import (
    access_request_context,
    category_context,
    core_messages,
    core_source,
    docs_sources,
    keyed_messages,
    keyed_translatable,
    logout_context,
    menu_context,
    paused_context,
    profile_lock_context,
    rbac_context,
    rbac_messages,
    role_context,
    role_messages,
)
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_META_RBAC


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


class TestCoreSource(unittest.TestCase):
    def test_every_context_names_the_file_its_extractor_reads(self):
        expected = {
            role_context("web-app-wiki"): Path(
                f"roles/web-app-wiki/{ROLE_FILE_META_MAIN}"
            ),
            category_context("web.app", "title"): Path("meta/categories.yml"),
            menu_context("Community", "description"): Path(
                "roles/web-app-dashboard/vars/menu_categories.yml"
            ),
            logout_context("counter"): Path(
                "roles/web-app-keycloak/files/logout_i18n.yml"
            ),
            paused_context("title"): Path(
                "roles/sys-svc-app-control/files/paused_i18n.yml"
            ),
            profile_lock_context("locked"): Path(
                "roles/sys-front-inj-javascript/files/profile_lock_i18n.yml"
            ),
            access_request_context("form_title"): Path(
                "roles/web-svc-access-request/files/access_request_i18n.yml"
            ),
            rbac_context("web-app-wiki", "editor"): Path(
                f"roles/web-app-wiki/{ROLE_FILE_META_RBAC}"
            ),
        }

        for context, path in expected.items():
            with self.subTest(context=context):
                self.assertEqual(core_source(context), path)

    def test_a_context_no_extractor_writes_is_refused(self):
        with self.assertRaises(ValueError):
            core_source("glossary:term")


class TestDocsSources(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_paragraph_is_found_across_its_line_breaks_and_markup(self):
        _write(self.root, "docs/backup.md", "The backup keeps `seven`\n  copies.\n")
        _write(self.root, "docs/other.md", "Something else entirely.\n")

        found = docs_sources(self.root, "The backup keeps ``seven`` copies.")

        self.assertEqual(found, ["docs/backup.md"])

    def test_a_generated_role_page_names_the_meta_file_it_was_built_from(self):
        _write(
            self.root,
            f"roles/web-app-wiki/{ROLE_FILE_META_MAIN}",
            "galaxy_info:\n  description: >-\n    A wiki for\n    teams\n",
        )

        found = docs_sources(self.root, "**Description:** A wiki for teams")

        self.assertEqual(found, [f"roles/web-app-wiki/{ROLE_FILE_META_MAIN}"])

    def test_a_rendered_template_is_found_by_the_prose_around_its_spans(self):
        _write(
            self.root,
            "templates/roles/README.md.j2.tmpl",
            "Deploy {{ application_name }} onto the local stack in one step.\n",
        )

        found = docs_sources(
            self.root, "Deploy `web-app-wiki` onto the local stack in one step."
        )

        self.assertEqual(found, ["templates/roles/README.md.j2.tmpl"])

    def test_a_catalog_is_never_a_source(self):
        _write(
            self.root,
            "locale/de/LC_MESSAGES/docs.po",
            'msgid "The backup keeps seven copies."\n',
        )

        self.assertEqual(docs_sources(self.root, "The backup keeps seven copies."), [])

    def test_a_word_is_not_found_inside_a_longer_one(self):
        _write(self.root, "docs/backup.md", "The backups keep seven copies.\n")

        self.assertEqual(docs_sources(self.root, "backup keep seven copies"), [])


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
            carried = {
                context: msgid in read_text(str(root / core_source(context)))
                for context, msgid in messages
            }

        self.assertEqual([c for c, found in carried.items() if not found], [])
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


class TestKeyedMessages(unittest.TestCase):
    def test_only_the_named_domain_is_read_under_its_own_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "locale/team.yml", "title: ' The team '\nbuilt: 'Built:'\n")
            _write(root, "locale/other.yml", "title: Elsewhere\n")

            messages = keyed_messages(root, "team")

        self.assertEqual(
            messages, [("team:title", "The team"), ("team:built", "Built:")]
        )


class TestKeyedTranslatable(unittest.TestCase):
    def _template(self, source: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "locale/meta.yml", source)
            template = build_template(
                keyed_messages(root, "meta"),
                "meta",
                keyed_translatable(root, "meta"),
            )
        return [message.context for message in template if message.id]

    def test_a_marked_key_stays_in_the_template_although_it_reads_as_a_token(self):
        self.assertEqual(
            self._template(
                "# nocheck: untranslatable\nresources.cpu: CPU\n"
                "resources.ram: RAM\nresources.disk: Disk space\n"
            ),
            ["meta:resources.cpu", "meta:resources.disk"],
            "the marker keeps only the key below it; RAM stays a token",
        )

    def test_without_the_marker_the_same_key_vanishes_from_the_template(self):
        self.assertEqual(
            self._template("resources.cpu: CPU\nresources.disk: Disk space\n"),
            ["meta:resources.disk"],
        )


if __name__ == "__main__":
    unittest.main()
