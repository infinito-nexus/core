from __future__ import annotations

import copy
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from ansible.errors import AnsibleError

import plugins.lookup.form_drift as module

APP = "web-app-demo"
OTHER = "web-app-other"
FORMS = {
    "general": {
        "path": "/admin/settings",
        "fields": {
            "relay": {
                "source": "services.mail.relay",
                "mode": "enforced",
                "selector": "#relay",
                "type": "text",
            },
            "sender": {
                "source": "users.administrator.email",
                "mode": "seeded",
                "selector": "#sender",
                "type": "email",
            },
        },
    }
}
SOURCE = "relay.example.test"
EDITED = "edited.example.test"
SYNTHETIC_SECRET = "SYNTH-CREDENTIAL-0042"


def _application(relay: str) -> dict:
    return {"forms": FORMS, "services": {"mail": {"relay": relay}}}


class TestFormDrift(unittest.TestCase):
    def _run(
        self,
        current,
        *,
        default: str = SOURCE,
        rendered: str = SOURCE,
        inventory: dict | None = None,
        other: dict | None = None,
    ) -> list[str]:
        applications = {APP: _application(rendered), OTHER: other or {}}
        spots = {"applications": applications, "users": {"administrator": {}}}

        def get(name, **_kwargs):
            spot = mock.MagicMock()
            spot.run.return_value = [spots[name]]
            return spot

        defaults = {APP: _application(default)}
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / APP / "meta").mkdir(parents=True)
            with (
                mock.patch.object(module, "ROLES_DIR", Path(tmp)),
                mock.patch.object(
                    module,
                    "get_application_defaults",
                    side_effect=lambda: copy.deepcopy(defaults),
                ),
                mock.patch.object(module.lookup_loader, "get", side_effect=get),
            ):
                return module.LookupModule().run(
                    [APP, current],
                    variables={"applications": inventory or {}},
                )[0]

    def test_a_plain_field_an_admin_changed_shows_both_values(self):
        self.assertEqual(
            [f"{APP}: general.relay (services.mail.relay): {EDITED!r} -> {SOURCE!r}"],
            self._run({"general": {"relay": EDITED}}),
        )

    def test_a_templated_default_hides_both_values(self):
        templated = "{{ lookup('tls', 'web-app-mail', 'url.host') }}"

        self.assertEqual(
            [f"{APP}: general.relay (services.mail.relay): changed"],
            self._run({"general": {"relay": EDITED}}, default=templated),
        )

    def test_a_plain_inventory_value_over_a_templated_default_shows_both(self):
        templated = "{{ lookup('tls', 'web-app-mail', 'url.host') }}"
        inventory = {APP: {"services": {"mail": {"relay": SOURCE}}}}

        self.assertEqual(
            [f"{APP}: general.relay (services.mail.relay): {EDITED!r} -> {SOURCE!r}"],
            self._run(
                {"general": {"relay": EDITED}}, default=templated, inventory=inventory
            ),
        )

    def test_another_roles_credential_in_the_field_hides_both_values(self):
        other = {"credentials": {"api_token": SYNTHETIC_SECRET}}

        lines = self._run({"general": {"relay": SYNTHETIC_SECRET}}, other=other)

        self.assertEqual(
            [f"{APP}: general.relay (services.mail.relay): changed"], lines
        )
        self.assertNotIn(SYNTHETIC_SECRET, "".join(lines))

    def test_a_field_that_matches_its_source_is_not_reported(self):
        self.assertEqual([], self._run({"general": {"relay": SOURCE}}))

    def test_a_field_the_run_did_not_read_is_not_reported(self):
        self.assertEqual([], self._run({"general": {}}))

    def test_a_seeded_field_is_never_reported(self):
        self.assertEqual([], self._run({"general": {"sender": "edited@example.test"}}))

    def test_an_undeclared_form_fails(self):
        with self.assertRaises(AnsibleError) as caught:
            self._run({"mail": {"relay": EDITED}})
        self.assertIn("declares no form 'mail'", str(caught.exception))

    def test_current_must_map_forms_to_fields(self):
        for current in (["relay"], {"general": "relay"}):
            with self.subTest(current=current), self.assertRaises(AnsibleError):
                self._run(current)

    def test_a_role_without_forms_fails(self):
        with (
            mock.patch.object(
                module.LookupModule,
                "_spot",
                side_effect=lambda name, *_a, **_k: (
                    {APP: {}} if name == "applications" else {}
                ),
            ),
            self.assertRaises(AnsibleError),
        ):
            module.LookupModule().run([APP, {}], variables={})


if __name__ == "__main__":
    unittest.main()
