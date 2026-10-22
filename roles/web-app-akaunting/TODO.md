# To-dos

- Enable OIDC
- Move off PHP 8.1. The role builds the image from `akaunting/docker` (`master`), whose Dockerfile starts `FROM php:8.1-apache` and runs PHP 8.1.34, which is end of life and gets no upstream fix for CVE-2026-109618 and CVE-2026-109619. Build on a PHP 8.2 or later base instead.
- Add OIDC auto-provisioning so a fresh Keycloak user that lands on the akaunting tile lands on a working akaunting user account instead of a "no permission" surface. Until that is wired, BOTH the playwright biber and administrator personas are blocked via `PERSONA_BIBER_BLOCKED=true` and `PERSONA_ADMINISTRATOR_BLOCKED=true` in `templates/playwright.env.j2` (req 019 Rule 11 explicit opt-out). Once auto-provisioning works, drop both opt-out flags so the personas drive the real journey.
