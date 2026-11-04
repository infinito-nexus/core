from __future__ import annotations

import json
import unittest

from jinja2 import Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = PROJECT_ROOT / "roles/web-app-semaphore/templates/oidc/email_claim.j2"
GROUP_CLAIM = "groups"
EMAIL_CLAIM = "email"
LOGIN_ROLES = ("administrator", "operator", "user")
VERIFIED_GATE = '(eq (printf "%v" (index . "email_verified")) "true")'


def render() -> str:
    """Render the Jinja layer of the template into the Go template Semaphore runs."""
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.filters["to_json"] = json.dumps
    environment.globals["lookup"] = lambda name, application_id, role: (
        f"roles/{application_id}/{role}"
    )
    return (
        environment.from_string(read_text(str(TEMPLATE)))
        .render(
            RBAC={"GROUP": {"CLAIM": GROUP_CLAIM}},
            OIDC={"ATTRIBUTES": {"EMAIL": EMAIL_CLAIM}},
            SEMAPHORE_RBAC_LOGIN_ROLES=list(LOGIN_ROLES),
            application_id="web-app-semaphore",
        )
        .strip()
    )


class TestSemaphoreEmailClaim(unittest.TestCase):
    def test_the_email_is_emitted_only_for_a_verified_member(self) -> None:
        self.assertIn(
            "{{ if and $member " + VERIFIED_GATE + " }}"
            "{{ with index . "
            + json.dumps(EMAIL_CLAIM)
            + " }}{{ . }}{{ end }}{{ end }}",
            render(),
            "Semaphore links an SSO login to the account whose email matches "
            "(GetUserByLoginOrEmail, semaphore v2.19.17 api/login.go:790), so the "
            "template must yield no email unless Keycloak marks it verified",
        )

    def test_the_email_is_read_once(self) -> None:
        self.assertEqual(render().count("index . " + json.dumps(EMAIL_CLAIM)), 1)

    def test_the_group_gate_stays(self) -> None:
        rendered = render()
        self.assertTrue(
            rendered.startswith(
                "{{ $member := false }}{{ range index . "
                + json.dumps(GROUP_CLAIM)
                + " }}{{ if eq ."
            )
        )
        for role in LOGIN_ROLES:
            self.assertIn(json.dumps(f"/roles/web-app-semaphore/{role}"), rendered)

    def test_the_template_has_no_alternative_separator(self) -> None:
        self.assertNotIn(
            "|",
            render(),
            "parseClaim splits the claim setting on '|' into alternatives "
            "(semaphore v2.19.17 api/login.go:578), which would cut the template apart",
        )


if __name__ == "__main__":
    unittest.main()
