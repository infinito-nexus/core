# 099 - Role Skeleton

## User Story

As a developer who wants to run an existing web application on Infinito.Nexus, I want core to render a complete `web-app-cst-<name>` role from a short manifest, so that my role passes every core check from its first commit and I deploy it through the custom role path of [046](046-custom-roles.md) instead of learning the role format by hand.

## Decisions

| # | Decision |
| --- | --- |
| 1 | Core owns the role contract, so core owns the skeleton: the templates live in `templates/roles/skeleton/`, the renderer and the manifest schema in `cli/contributing/role/skeleton/`. A change to the role format that breaks a rendered skeleton fails core's own tests and is fixed in the same change. |
| 2 | The renderer is the only implementation. The builder (`infinito-nexus/builder`, CLI and builder.infinito.nexus) calls it from a checkout of the chosen core version and keeps no templates or schema of its own. |
| 3 | The renderer is invoked as `python -m cli.contributing.role.skeleton`, with the subcommands `schema` (prints the manifest fields as JSON, which the builder turns into its wizard and form) and `render` (reads the manifest as JSON or YAML from stdin and writes the role). It runs with the Python standard library, Jinja2 and PyYAML only. |
| 4 | `cli/contributing/role/skeleton/sparse.txt` lists, as Git sparse-checkout patterns, every path of core the renderer reads, so the builder fetches only those paths of a core tag. |
| 5 | Manifest v1 fields: `name`, `description`, `homepage`, `license` (SPDX id), `image` (with tag), `port` (internal HTTP port), `database` (`postgres`, `mariadb`, `none`), `login` (`oidc`, `ldap`, `none`), `features` (subset of `email`, `redis`), and optionally `environment` (mapping) and `volumes` (container paths). |
| 6 | The renderer allocates what must be unique in the target core: the local HTTP port through `cli contributing network ports suggest`, the subnet through `cli contributing network address suggest`, and the canonical domain `<name>.{{ DOMAIN_PRIMARY }}`. |
| 7 | The skeleton follows `web-app-mini-qr` for the base and `web-app-pgadmin` for database and OIDC wiring; every optional service is a dynamic flag, and `meta/variants.yml` pins each flag true in variant 0 and false in variant 1. |
| 8 | The image version is the literal tag of the manifest; the skeleton uses no `lookup('role_version', ...)`. |
| 9 | Rendered roles are never committed to core: `roles/web-app-cst-*` stays reserved and ignored by Git. The contract check renders sample manifests into `roles/web-app-cst-*` with the pull marker of 046 and removes them with `make roles-clean`. |
| 10 | A second kind, `static`, renders a static site role modelled on `web-app-cst-team` for the sites of the Infinito.Nexus family. It links the brand role `web-app-cst-brand` and the `--design-*` tokens of the design round of 2026-11-11 23:55 instead of copying header or footer markup, and it follows once `web-app-cst-brand` exists. It uses the shared translation stack: its strings live in `locale/<code>/LC_MESSAGES/<domain>.po`, translated through `make i18n-translate` and the `web-svc-translate` gateway, and it serves every language under `/<code>/` with `html` `lang` and `dir` and `hreflang` links. The default kind renders no HTML of its own, so the application's interface keeps its own translations. |

## Acceptance Criteria

### Renderer

- [ ] `python -m cli.contributing.role.skeleton schema` prints every manifest field with its help text, its type, its choices and its default as JSON.
- [ ] `python -m cli.contributing.role.skeleton render --target <dir>` writes `<dir>/web-app-cst-<name>/` from a manifest on stdin and prints the path of the role directory.
- [ ] `render` refuses an existing role directory unless `--force` is given.
- [ ] A manifest with a missing required field, a `name` outside `[a-z0-9-]`, an `image` without a tag, a `port` outside 1 to 65535, an unknown `database`, `login` or feature, or a `description` longer than 120 characters stops with exit code 2 and one line per error naming the field, and writes nothing.
- [ ] A `name` whose entity name equals the entity name of an in-tree role stops with a message naming that role.
- [ ] The rendered role has a local HTTP port and a subnet that no role of the core checkout uses.
- [ ] `make role-skeleton manifest=<file> target=<dir>` runs `render` with that manifest.
- [ ] `sparse.txt` lists every path the renderer reads; a render inside a sparse checkout made from it succeeds.

### Rendered role

- [ ] The role has `vars/main.yml` with `application_id: web-app-cst-<name>`, `tasks/main.yml` guarded by `run_once`, `README.md` with the Description, Overview and Features sections, `meta/main.yml`, `meta/services.yml`, `meta/variants.yml`, `meta/info.yml`, `meta/license.yml`, `meta/domains.yml`, `meta/networks.yml`, `meta/csp.yml`, `templates/compose.yml.j2`, `templates/playwright.env.j2` and `files/playwright/playwright.spec.js`.
- [ ] `database: postgres` or `mariadb` declares the database service and passes its connection values to the container from `lookup('database', application_id, ...)`.
- [ ] `login: oidc` declares `sso` with flavor `oidc` and passes the client values; `login: ldap` declares `ldap`; `login: none` opts out of SSO with its nocheck reason.
- [ ] `features: [email]` and `features: [redis]` declare the email and redis services.
- [ ] `environment` entries reach the container environment through `templates/env.j2`, and every `volumes` path becomes a named volume with `backup.stop_required`.
- [ ] The README names the parts the developer must review: CSP, RBAC, application settings and Playwright coverage beyond the baseline.

### Static kind

- [x] A manifest with `kind: static` renders a static site role that links `web-app-cst-brand` and the `--design-*` tokens, renders header and footer on the server with nav entries from the brand config, and includes `cosmos.js` and `cosmos-sky` only while its cosmos service flag is on.
- [ ] A `kind: static` role ships its strings as `locale/<code>/LC_MESSAGES/<domain>.po`, `make i18n-translate` fills them through `web-svc-translate`, and every language of core `meta/languages.yml` is served under `/<code>/` with `html` `lang` and `dir` and `hreflang` links.

### Contract

- [ ] `make role-skeleton-check` renders one sample manifest per database and login choice into `roles/web-app-cst-*`, runs `make test` and `make lint` against them, and removes them afterwards, also when a check fails.
- [ ] Unit tests cover the manifest validation, the schema output and the file set of a rendered role.
- [ ] Whenever `templates/roles/skeleton/`, `cli/contributing/role/` or a role lint changes, the regular CI test and lint jobs render the sample roles with `make role-skeleton-samples` first, so no second full suite runs.
- [ ] `make test` passes.
