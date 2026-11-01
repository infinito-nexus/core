# To-dos

- Enable OIDC
- Add OIDC auto-provisioning so a fresh Keycloak user that lands on the akaunting tile lands on a working akaunting user account instead of a "no permission" surface. Until that is wired, BOTH the playwright biber and administrator personas are blocked via `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true` in `templates/playwright.env.j2` (req 019 Rule 11 explicit opt-out). Once auto-provisioning works, drop both opt-out flags so the personas drive the real journey.
