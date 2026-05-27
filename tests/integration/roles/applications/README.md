# Application Role Tests 📦

Integration tests that enforce rules about roles which represent deployable applications: `web-app-*` roles MUST ship a `README.md` (required for the Web App Dashboard), every literal name compared against `group_names` in playbooks/roles MUST resolve to a real `application_id`, every `applications['…']` / `applications.get('…')` / `applications.name` / `get_domain('…')` reference MUST name an existing application, and roles MUST NOT reach into `applications[...]` by subscript; they MUST use `lookup('applications', …)` or `utils.roles.applications.config.get` instead.

Tests in this directory MUST only cover application-level role rules. Identity checks tied to the `application_id` variable itself (presence, uniqueness, deprecation, folder-name prefix, ports/domain/run_after/dependency consistency) MUST live under [`id/`](id/). Generic structural role checks MUST live one level up under [`../`](../).

For framework, directory layout, and `make test-integration` usage see [integration.md](../../../../docs/contributing/actions/testing/integration.md).
