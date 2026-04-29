## Summary

Briefly describe the `web-*` change and the expected user-facing outcome.

Examples:

* Add a new `web-app-*` role
* Fix a broken login, bootstrap, or integration flow in an existing `web-*` role
* Introduce SSO or mail integration for an existing `web-*` role
* Extend bootstrap or deployment behavior for a server-facing application

---

## Template Type

Select the primary intent of this PR:

* [ ] **Feature** - Adds or extends server functionality
* [ ] **Fix** - Repairs broken or incorrect server behavior

---

## Affected Roles and Services

List the impacted roles and related services.

* Primary `web-*` role(s):
* Related `web-svc-*`, `sys-front-*`, `svc-db-*`, auth, mail, proxy, or storage role(s):

## Preferred Integrations

Integrate the change into the following services when possible:

* [ ] Dashboard
* [ ] Matomo
* [ ] OIDC
* [ ] LDAP
* [ ] Logout

---

## Change Type

Select the semantic version impact of this change:

* [ ] **Major** - Breaking change
* [ ] **Minor** - New backwards-compatible feature
* [ ] **Patch** - Small improvement or compatible adjustment

---

## Change Details

Explain what changed and why.

Key points:

* What problem does this solve?
* Which upstream image or service version was used or changed?
* How do login, logout, proxying, storage, or mail integration behave after this change?
* Which alternatives were considered?

---

## File Checklist

Check the relevant rows and explain intentional omissions in `Additional Notes`.

| Check | Item | When to include | Purpose |
|---|---|---|---|
| [ ] | `README.md` | Usually | Documents role-specific usage, setup notes, and contributor context. |
| [ ] | `meta/main.yml` | Usually | Declares Ansible Galaxy info and `dependencies:`. No project-internal `run_after:` / `lifecycle:` (those live on the primary entity in `meta/services.yml`, per [req-010](../../docs/requirements/010-role-meta-runafter-lifecycle-migration.md)). |
| [ ] | `vars/main.yml` | Usually | Defines the shared fixed role variables as the main source of truth. |
| [ ] | `meta/services.yml` | Usually | Per-entity service config (file root IS the services map keyed by `<entity_name>`). Holds image/version, `ports.{inter,local,public}` (per [req-009](../../docs/requirements/009-per-role-networks-and-ports.md)), `run_after`/`lifecycle` on the primary entity (per [req-010](../../docs/requirements/010-role-meta-runafter-lifecycle-migration.md)), plus inlined per-service settings. |
| [ ] | `meta/server.yml` | Usually | Server-level config (file root IS `applications.<app>.server`). CSP, `domains`, `status_codes`, plus the per-role `networks.local.{subnet,dns_resolver}`. |
| [ ] | `meta/rbac.yml` | When the role declares RBAC | RBAC declarations (file root IS `applications.<app>.rbac`). |
| [ ] | `meta/volumes.yml` | When the role declares Compose volumes | Volumes map (file root IS the volumes map; no `compose:`/`volumes:` wrapper). |
| [ ] | `meta/schema.yml` | When the role declares credentials | Credential schema with optional `default:` field (per [req-008](../../docs/requirements/008-role-meta-layout.md)). |
| [ ] | `tasks/main.yml` | Usually | Acts as the role entry point and includes the main task flow. |
| [ ] | `templates/compose.yml.j2` | For containerized app roles | Defines the service, volume, environment, port, and network wiring. |
| [ ] | `templates/env.j2` | When the app uses environment files | Renders the app environment configuration. |
| [ ] | `templates/style.css.j2` or `files/style.css` | When the role injects custom branding or theming | Defines the role-local CSS overrides that adapt the UI to the repository design system. See [Contributing `style.css`](../../docs/contributing/artefact/files/role/style.css.md). |
| [ ] | `templates/javascript.js.j2` or `files/javascript.js` | When the role injects custom frontend behavior | Defines the role-local JavaScript that adapts UI behavior or integration glue in the browser. See [Contributing `javascript.js`](../../docs/contributing/artefact/files/role/javascript.js.md). |
| [ ] | `meta/users.yml` | When the role bootstraps users or identities | Role-local user definitions (file root IS the users map; no `users:` wrapper). |
| [ ] | `files/Dockerfile` | When a custom image is required | Provides a custom image build path. Prefer this over `Dockerfile.j2`. |
| [ ] | `templates/playwright.env.j2` | When Playwright coverage is included | Configures the Playwright test environment. See [Contributing `playwright.env.j2`](../../docs/agents/files/role/playwright.env.j2.md). |
| [ ] | `files/playwright.spec.js` | When Playwright coverage is included | Defines the Playwright login and logout test flow. See [Contributing `playwright.spec.js`](../../docs/contributing/artefact/files/role/playwright.specs.js.md). |

### Registered

| Check | Item | When to include | Purpose |
|---|---|---|---|
| [ ] | Per-entity ports in `meta/services.yml.<entity>.ports.{inter,local,public}` | When the app exposes a service | Confirms that the app's host-bound ports are declared on the entity that exposes them (per [req-009](../../docs/requirements/009-per-role-networks-and-ports.md)). Use `cli meta ports suggest` to pick free slots inside the appropriate `PORT_BANDS.<scope>.<category>` from `group_vars/all/08_networks.yml`. |
| [ ] | Per-role subnet in `meta/server.yml.networks.local.subnet` | When the app communicates over container networks | Confirms that the role's docker network CIDR is declared (per [req-009](../../docs/requirements/009-per-role-networks-and-ports.md)). Use `cli meta networks suggest --clients N` to pick a free subnet. |

---

## Local Validation

Describe how the change was validated locally.

* [ ] Deployment target and distro documented
* [ ] Playwright test run documented
* [ ] Login flow tested
* [ ] Logout flow tested
* [ ] Screenshot attached when the change is user-visible

---

## Security Impact

Indicate whether this change has security implications.

* [ ] No relevant security impact
* [ ] Security impact present

If security impact is present, explain:

* Affected auth, TLS, permissions, secrets, headers, or exposed surfaces:
* Risk reduction, new exposure, or compatibility considerations:
* Security-specific validation performed:

---

## Review Focus

Help reviewers focus on the riskiest parts of this PR.
For repository-wide contribution and review expectations, see [CONTRIBUTING.md](../../CONTRIBUTING.md).

* Highest-risk files, roles, or flows:
* Migration, rollback, or security-sensitive concerns:
* Specific feedback requested from reviewers:

---

## Definition of Done (DoD)

* [ ] The implementation follows the Definition of Done, and the contribution guidelines in [CONTRIBUTING.md](../../CONTRIBUTING.md) were considered and applied during implementation.

---

## Additional Notes

Add any reviewer context that is useful for deployment, rollback, or follow-up work.
