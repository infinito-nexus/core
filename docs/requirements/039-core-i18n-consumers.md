# 039 - Core i18n Consumers

## User Story

As a visitor of an Infinito.Nexus deployment, I want the documentation, the universal logout panel and the dashboard to speak my language from the core gettext catalogs, and I want browser apps such as MIG to be allowed to read the API, so that every surface core renders follows the same translations.

## Scope

This requirement moves the core roles that render translated text onto the catalogs of [037 - Gettext Catalogs with LibreTranslate Autotranslation](037-gettext-catalogs-libretranslate.md) and opens the API of [038 - web-svc-api](README.md#archive) to browser consumers.
The consumer repositories change afterwards and are not part of this requirement.

## Findings That Constrain the Design

- [web-app-docs](../../roles/web-app-docs/files/python/infinito_docs/library.py) builds each version on demand from a git mirror: `git archive` of the ref, the generators, then one `sphinx-build -M html`. Its [server](../../roles/web-app-docs/files/python/infinito_docs/server.py) routes `/<version>/<rest>`. Sphinx reads `locale/<code>/LC_MESSAGES/docs.po` when `language` and `locale_dirs` are set, and compiles it with Babel.
- One built version needs about 2.3 GB. Building every translated language up front multiplies that per language; `min_storage` MUST say so. `min_storage` also gates which roles a host deploys at all, so it counts the sites every deployment builds and names the growth per further language.
- The documentation is built from the git mirror of `DOCS_SOURCE_REPO`. Catalogs that exist only in a local working tree never reach it.
- [logout-panel.js.j2](../../roles/web-app-keycloak/templates/logout-panel.js.j2) inlines [logout_i18n.yml](../../roles/web-app-keycloak/files/logout_i18n.yml) as a `{language: {key: text, dir}}` object, and [logout-panel.js](../../roles/web-app-keycloak/files/javascript/logout-panel.js) picks the language from `<html lang>` and `navigator.language`. Its 29 non-English blocks are the only human translations core owns.
- port-ui translates the rendered `config.yaml` through `app/i18n/content/<code>.yaml`, a flat mapping from the English source string to its translation for the keys `description`, `info`, `name`, `subtitel`, `text`, `title` and `warning`. [web-app-dashboard](../../roles/web-app-dashboard/meta/volumes.yml) mounts only `config.yaml` today, so every card and menu text stays English.
- [csp_filters.py](../../plugins/filter/csp_filters.py) adds a provider origin to `connect-src` only for known feature flags such as `simpleicons`. [web-app-mig](../../roles/web-app-mig/templates/compose.yml.j2) renders no environment and no API origin.

## Acceptance Criteria

- [ ] For every version whose tree holds a `locale/<code>/LC_MESSAGES/docs.po` with at least one translation, web-app-docs publishes the English site first and then one site per such language at `/<version>/<code>/`.
- [ ] web-app-docs builds the deployed working tree as the unlisted version `deployed`, because the git mirror only holds what is pushed to `main`.
- [ ] `/deployed/de/` serves a page whose `<html lang>` is `de` and whose body contains the German translation of a message from the German `docs.po`; `/latest/de/` follows once the catalogs are on `main`.
- [ ] Every documentation page offers a language switcher that lists English and every language built for that version, and switching keeps the page path.
- [ ] A request for a language of `meta/languages.yml` that has no site for the version returns a 404, not the English page.
- [x] `min_storage` of web-app-docs states the storage of the English site plus the translated sites.
- [x] `logout_i18n.yml` holds only the English source strings, and the logout panel reads every other language from `core.po`.
- [ ] For each of the 29 languages of the former `logout_i18n.yml`, the rendered panel catalogue holds the same strings as before the migration.
- [x] The logout panel takes the text direction of every language from `meta/languages.yml`.
- [x] web-app-dashboard mounts one port-ui content catalog per language that has a translated dashboard string, generated from `core.po` at deploy time.
- [x] The dashboard at `/de/` shows the German translation of at least one card description and one menu category.
- [x] A role that enables the `api` service gets the web-svc-api origin in its `connect-src`, and a role without it does not.
- [x] web-app-mig enables the `api` service when web-svc-api is deployed and renders the API base URL into its environment.
- [ ] The Playwright specs of web-app-docs, web-app-keycloak and web-app-dashboard cover the German page, the German logout panel and the German dashboard.
- [ ] `make compose-deploy` is green for web-app-docs, web-app-keycloak, web-app-dashboard and web-app-mig.
