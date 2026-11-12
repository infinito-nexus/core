"""Negative controls for the managed-field lint of ``meta/forms.yml``."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from tests.lint.ansible.roles.meta import test_forms as lint
from utils.roles.mapping import (
    ROLE_FILE_META_FORMS,
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "web-app-fixture"
DEFAULTS = {ROLE: {"design": {"label": "Fixture"}}}
USERS = {"administrator": {"email": "admin@example.com"}}
SECRETS = """
credentials:
  smtp_password:
    algorithm: alphanumeric
    length: 32
"""
VALID = """
general:
  path: /admin/settings
  fields:
    title:
      source: design.label
      mode: enforced
      selector: "#title"
    email:
      source: users.administrator.email
      mode: seeded
      selector: "#email"
    smtp_password:
      source: secrets.credentials.smtp_password
      mode: enforced
      selector: "#smtp_password"
"""


class TestFormsLint(unittest.TestCase):
    def _findings(self, forms_yml: str) -> list[str]:
        return self._findings_with(forms_yml, DEFAULTS, USERS)

    @staticmethod
    def _findings_with(forms_yml: str, defaults: dict, users: dict) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / ROLE
            for name, content in (
                (ROLE_FILE_META_FORMS, forms_yml),
                (ROLE_FILE_META_SECRETS, SECRETS),
            ):
                path = role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
            return lint.findings([role], defaults, users)

    def test_a_valid_file_passes(self) -> None:
        self.assertEqual([], self._findings(VALID))

    def test_a_field_without_mode_fails(self) -> None:
        broken = VALID.replace("      mode: seeded\n", "")
        self.assertEqual(
            [f"{ROLE}: general.fields.email lacks `mode`"], self._findings(broken)
        )

    def test_a_field_without_source_or_selector_fails(self) -> None:
        broken = VALID.replace("      source: design.label\n", "").replace(
            '      selector: "#email"\n', ""
        )
        self.assertEqual(
            [
                f"{ROLE}: general.fields.title lacks `source`",
                f"{ROLE}: general.fields.email lacks `selector`",
            ],
            self._findings(broken),
        )

    def test_an_unknown_mode_fails(self) -> None:
        findings = self._findings(VALID.replace("mode: seeded", "mode: once"))
        self.assertEqual(1, len(findings))
        self.assertIn("mode 'once' is not one of", findings[0])

    def test_a_source_that_does_not_resolve_fails(self) -> None:
        broken = VALID.replace("source: design.label", "source: design.title")
        self.assertEqual(
            [f"{ROLE}: general.title.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_a_dotted_secret_in_when_is_never_echoed(self) -> None:
        secret = "SG.SYNTH-SECRET-1.abcdef0123"
        broken = VALID.replace(
            '      selector: "#title"\n',
            f'      selector: "#title"\n      when: {secret}\n',
        )
        findings = self._findings(broken)
        self.assertEqual(
            [f"{ROLE}: general.title.when names nothing in the inventory"], findings
        )
        self.assertNotIn("SYNTH-SECRET-1", findings[0])

    def test_a_template_in_a_forms_string_fails(self) -> None:
        broken = VALID.replace('selector: "#title"', 'selector: "#{{ title_id }}"')
        self.assertEqual(
            [
                (
                    f"{ROLE}: general.fields.title.selector must hold no template;"
                    f" {ROLE_FILE_META_FORMS} is never rendered"
                )
            ],
            self._findings(broken),
        )

    def test_an_undeclared_credential_fails(self) -> None:
        broken = VALID.replace(
            "secrets.credentials.smtp_password", "secrets.credentials.imap_password"
        )
        self.assertEqual(
            [f"{ROLE}: general.smtp_password.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_an_unknown_user_fails(self) -> None:
        broken = VALID.replace("users.administrator.email", "users.biber.email")
        self.assertEqual(
            [f"{ROLE}: general.email.source names nothing in the inventory"],
            self._findings(broken),
        )

    def test_a_user_source_other_than_a_plain_attribute_fails(self) -> None:
        role_users = {"administrator": {"email": "a@x", "password": "pw", "tokens": {}}}
        defaults = {ROLE: {**DEFAULTS[ROLE], "users": role_users}}
        for source in ("users.administrator", "users.administrator.tokens"):
            with self.subTest(source=source):
                broken = VALID.replace("users.administrator.email", source)
                self.assertEqual(
                    [
                        (
                            f"{ROLE}: general.email.source must be "
                            "users.<key>.<attr> with an attr other than ['tokens']"
                        )
                    ],
                    self._findings_with(broken, defaults, {**USERS, **role_users}),
                )

    def test_a_user_password_source_passes(self) -> None:
        users = {"administrator": {"email": "a@x", "password": "SYNTH-PW"}}
        allowed = VALID.replace(
            "users.administrator.email", "users.administrator.password"
        )
        self.assertEqual([], self._findings_with(allowed, DEFAULTS, users))

    def test_an_sso_claim_source_passes(self) -> None:
        self.assertEqual([], self._findings(VALID + PROFILE))

    def test_an_sso_source_outside_the_oidc_claims_fails(self) -> None:
        for source in ("sso.shoe_size", "sso.email.domain"):
            with self.subTest(source=source):
                findings = self._findings(VALID + PROFILE.replace("sso.email", source))
                self.assertEqual(1, len(findings))
                self.assertIn(
                    f"{ROLE}: profile.email.source must be sso.<claim> with a claim "
                    "of OIDC.ATTRIBUTES",
                    findings[0],
                )
                self.assertNotIn(source, findings[0])

    def test_a_seeded_sso_field_fails(self) -> None:
        seeded = PROFILE.replace("mode: enforced", "mode: seeded")
        self.assertEqual(
            [
                f"{ROLE}: profile.email.mode must be enforced, since the sign-in writes it"
            ],
            self._findings(VALID + seeded),
        )

    def test_an_sso_field_with_when_fails(self) -> None:
        guarded = PROFILE.replace(
            "      mode: enforced", "      when: design.label\n      mode: enforced"
        )
        self.assertEqual(
            [f"{ROLE}: profile.email takes no `when`; the selector's marker decides"],
            self._findings(VALID + guarded),
        )


PROFILE = """
profile:
  path: /profile
  fields:
    email:
      source: sso.email
      mode: enforced
      selector: "#email[data-sso]"
"""
CONVERGES_GENERAL = """
- name: Write the general settings
  ansible.builtin.debug:
    msg: "{{ lookup('form_values', application_id, 'general') }}"
"""
NOT_CONVERGED = (
    f"{ROLE}: meta/forms.yml declares the form 'general', but no "
    "lookup('form_values', application_id, 'general') converges it"
)


class TestConvergenceLint(unittest.TestCase):
    @staticmethod
    def _findings(files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / ROLE
            for name, content in {ROLE_FILE_META_FORMS: VALID, **files}.items():
                path = role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
            return lint.convergence_findings([role])

    def test_a_role_that_converges_each_declared_form_passes(self) -> None:
        self.assertEqual([], self._findings({"tasks/main.yml": CONVERGES_GENERAL}))

    def test_a_form_read_from_vars_or_a_template_counts(self) -> None:
        for name in ("vars/main.yml", "templates/settings.json.j2"):
            with self.subTest(file=name):
                lookup = '{{ lookup("form_values", application_id, "general") }}'
                self.assertEqual([], self._findings({name: f"X: '{lookup}'\n"}))

    def test_a_declared_form_the_role_never_converges_fails(self) -> None:
        self.assertEqual(
            [NOT_CONVERGED],
            self._findings({"tasks/main.yml": "- ansible.builtin.meta: noop\n"}),
        )

    def test_a_converged_form_the_file_does_not_declare_fails(self) -> None:
        undeclared = CONVERGES_GENERAL.replace("'general'", "'mail'")
        self.assertEqual(
            [
                NOT_CONVERGED,
                (
                    f"{ROLE}: lookup('form_values', application_id, 'mail') converges "
                    "a form meta/forms.yml does not declare"
                ),
            ],
            self._findings({"tasks/main.yml": undeclared}),
        )

    def test_a_form_named_through_a_variable_does_not_count(self) -> None:
        dynamic = CONVERGES_GENERAL.replace("'general'", "form_name")
        self.assertEqual(1, len(self._findings({"tasks/main.yml": dynamic})))

    def test_a_form_of_sso_fields_only_needs_no_converge(self) -> None:
        files = {
            ROLE_FILE_META_FORMS: VALID + PROFILE,
            "tasks/main.yml": CONVERGES_GENERAL,
        }
        self.assertEqual([], self._findings(files))


SINK_FORMS = """
general:
  path: /admin/settings
  sinks: [FIXTURE_SETTINGS]
  fields:
    title:
      source: design.label
      mode: enforced
      selector: "#title"
mail:
  path: /admin/mail
  sinks: [FIXTURE_SETTINGS]
  fields:
    sender:
      source: design.label
      mode: seeded
      selector: "#sender"
"""
GENERAL = "lookup('form_values', application_id, 'general')"
MAIL = "lookup('form_values', application_id, 'mail')"
BOTH = f"{GENERAL} | combine({MAIL})"
SINK = f"{ROLE}: sink FIXTURE_SETTINGS"
SYNTH_LITERAL = "SYNTH-LITERAL-1"


def _sink(expression: str, **others: str) -> str:
    lines = [f'FIXTURE_SETTINGS: "{{{{ {expression} }}}}"']
    lines.extend(f'{name}: "{{{{ {value} }}}}"' for name, value in others.items())
    return "\n".join(lines) + "\n"


class TestSinkLint(unittest.TestCase):
    @staticmethod
    def _findings(vars_yml: str, forms_yml: str = SINK_FORMS) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            role = Path(tmp) / ROLE
            for name, content in (
                (ROLE_FILE_META_FORMS, forms_yml),
                (ROLE_FILE_VARS_MAIN, vars_yml),
            ):
                path = role / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(textwrap.dedent(content), encoding="utf-8")
            return lint.sink_findings([role])

    def test_a_sink_joining_the_form_values_of_its_forms_passes(self) -> None:
        self.assertEqual([], self._findings(_sink(BOTH)))
        seeded = f"{GENERAL} | combine({MAIL[:-1]}, mode='seeded'), recursive=True)"
        self.assertEqual([], self._findings(_sink(seeded)))

    def test_a_sink_read_through_a_clean_role_variable_passes(self) -> None:
        self.assertEqual(
            [],
            self._findings(
                _sink(f"FIXTURE_GENERAL | combine({MAIL})", FIXTURE_GENERAL=GENERAL)
            ),
        )

    def test_an_item_or_an_attribute_of_the_form_values_passes(self) -> None:
        self.assertEqual(
            [], self._findings(_sink(f"{GENERAL}['title'] | combine({MAIL}.sender)"))
        )

    def test_a_literal_fails_naming_its_field_without_repeating_it(self) -> None:
        for vars_yml, finding in (
            (
                _sink(f"{BOTH} | combine({{'title': '{SYNTH_LITERAL}'}})"),
                f"{SINK} writes a literal to title",
            ),
            (f"FIXTURE_SETTINGS: {SYNTH_LITERAL}\n", f"{SINK} writes a literal"),
            (
                f"FIXTURE_SETTINGS: {{title: {SYNTH_LITERAL}}}\n",
                f"{SINK} writes a literal",
            ),
        ):
            with self.subTest(finding=finding):
                findings = self._findings(vars_yml)
                self.assertEqual([finding], findings)
                self.assertNotIn(SYNTH_LITERAL, "\n".join(findings))

    def test_a_config_lookup_fails(self) -> None:
        self.assertEqual(
            [f"{SINK} reads lookup('config')"],
            self._findings(
                _sink(f"{BOTH} | combine(lookup('config', application_id, 'design'))")
            ),
        )

    def test_an_indirect_variable_fails(self) -> None:
        self.assertEqual(
            [f"{SINK} through FIXTURE_EXTRA reads lookup('config')"],
            self._findings(
                _sink(
                    f"{BOTH} | combine(FIXTURE_EXTRA)",
                    FIXTURE_EXTRA="lookup('config', application_id, 'design')",
                )
            ),
        )
        self.assertEqual(
            [
                f"{SINK} reads design_overrides, which {ROLE_FILE_VARS_MAIN} does not define"
            ],
            self._findings(_sink(f"{BOTH} | combine(design_overrides)")),
        )

    def test_any_other_filter_or_option_fails(self) -> None:
        self.assertEqual(
            [f"{SINK} applies the filter 'default'"],
            self._findings(_sink(f"{BOTH} | default({{}})")),
        )
        self.assertEqual(
            [f"{SINK} passes combine an option it does not take"],
            self._findings(_sink(f"{GENERAL} | combine({MAIL}, title='x')")),
        )

    def test_an_expression_other_than_a_lookup_fails(self) -> None:
        for expression, kind in (
            ("query('form_values', application_id, 'general')", "Call"),
            (f"{BOTH} ~ 'x'", "Concat"),
            (f"{BOTH} if true else {GENERAL}", "CondExpr"),
        ):
            with self.subTest(kind=kind):
                self.assertIn(
                    f"{SINK} computes a {kind} expression",
                    self._findings(_sink(expression)),
                )

    def test_a_form_named_through_a_variable_or_a_foreign_mode_fails(self) -> None:
        for expression in (
            f"{GENERAL} | combine(lookup('form_values', application_id, form_name))",
            f"{GENERAL} | combine({MAIL[:-1]}, mode='locked'))",
            f"{GENERAL} | combine(lookup('form_values', 'web-app-other', 'mail'))",
        ):
            with self.subTest(expression=expression):
                self.assertIn(
                    f"{SINK} must read lookup('form_values', application_id, '<form>')",
                    self._findings(_sink(expression)),
                )

    def test_a_statement_text_or_a_second_expression_fails(self) -> None:
        for vars_yml, finding in (
            (
                f'FIXTURE_SETTINGS: "{{% if true %}}{{{{ {BOTH} }}}}{{% endif %}}"\n',
                f"{SINK} holds a statement",
            ),
            (
                f'FIXTURE_SETTINGS: "x{{{{ {BOTH} }}}}"\n',
                f"{SINK} must be exactly one expression",
            ),
            (
                f'FIXTURE_SETTINGS: "{{{{ {BOTH} }}}}{{{{ {GENERAL} }}}}"\n',
                f"{SINK} must be exactly one expression",
            ),
            ('FIXTURE_SETTINGS: "{{ broken("\n', f"{SINK} is no valid Jinja"),
        ):
            with self.subTest(finding=finding):
                self.assertIn(finding, self._findings(vars_yml))

    def test_a_cycle_fails_instead_of_recursing(self) -> None:
        findings = self._findings(
            _sink("FIXTURE_LOOP", FIXTURE_LOOP="FIXTURE_SETTINGS")
        )
        self.assertIn(
            f"{SINK} through FIXTURE_LOOP reads FIXTURE_SETTINGS in a cycle", findings
        )

    def test_a_form_without_sinks_fails_unless_it_holds_only_sso_fields(self) -> None:
        unnamed = SINK_FORMS.replace("  sinks: [FIXTURE_SETTINGS]\n", "", 1)
        self.assertEqual(
            [
                f"{ROLE}: the form 'general' names no sinks",
                f"{SINK} reads the form 'general', whose sinks do not name FIXTURE_SETTINGS",
            ],
            self._findings(_sink(BOTH), unnamed),
        )
        self.assertEqual([], self._findings(_sink(BOTH), SINK_FORMS + PROFILE))

    def test_a_form_its_sink_never_reads_fails(self) -> None:
        self.assertEqual(
            [f"{SINK} never reads the form 'mail', which names it"],
            self._findings(_sink(GENERAL)),
        )

    def test_a_sink_the_role_does_not_define_fails(self) -> None:
        self.assertEqual(
            [f"{SINK} is not defined in {ROLE_FILE_VARS_MAIN}"],
            self._findings("FIXTURE_OTHER: x\n"),
        )


if __name__ == "__main__":
    unittest.main()
