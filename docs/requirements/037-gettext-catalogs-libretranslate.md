# 037 - Gettext Catalogs with LibreTranslate Autotranslation

## User Story

As a maintainer of Infinito.Nexus, I want every user-facing string that core ships extracted into gettext catalogs and machine-translated by LibreTranslate through `make`, so that the API, the documentation and every consumer app serve all ISO 639-1 languages from one source of truth in this repository.

## Scope

This requirement covers the catalogs, their extraction, their machine translation and their validation.
Serving the catalogs is [038 - web-svc-api](README.md#archive); consuming them inside core roles is [039 - Core i18n Consumers](039-core-i18n-consumers.md).
The consumer repositories (infinito-nexus-gui, meta-infinite-graph, portfolio) keep their own interface strings in their own gettext catalogs and switch only after 037 to 039 are green.

## Findings That Constrain the Design

- Core has no gettext today. The only catalogue is [logout_i18n.yml](../../roles/web-app-keycloak/files/logout_i18n.yml): 30 languages keyed by language code, named keys, `{placeholder}` slots and a `dir` value, inlined as JSON by [logout-panel.js.j2](../../roles/web-app-keycloak/templates/logout-panel.js.j2).
- The translatable core strings are `galaxy_info.description` in every `roles/*/meta/main.yml` (266 roles), `title` and `description` of every node in [categories.yml](../../meta/categories.yml), the key and `description` of every entry in [menu_categories.yml](../../roles/web-app-dashboard/vars/menu_categories.yml), and the logout panel strings. Role titles are product names and MUST NOT be translated.
- Babel 2.18 is already installed in the development interpreter as a Sphinx dependency; Sphinx compiles `.po` catalogs through it.
- The Argos package index behind LibreTranslate offers 49 languages paired with English. 47 of them are ISO 639-1 codes; `pb` (Brazilian Portuguese) and `zt` (Traditional Chinese) are not and are out of scope. The remaining ISO languages have no model.
- [web-svc-libretranslate](../../roles/web-svc-libretranslate/meta/services.yml) pins `libretranslate/libretranslate` `v1.9.6` with `load_only: [en, de]`, `cpus: 0.2` and `mem_limit: 256m`. Bulk translation MUST NOT depend on that deployment; `make` runs its own short-lived container of the same image and version.
- The documentation sources hold about 300,000 words (role READMEs and `docs/`). Translating them into 47 languages takes days of CPU, so the documentation domain runs per language and in the background.

## Design

- `meta/languages.yml` lists the 184 ISO 639-1 languages with English name, native name and text direction. It is the single source for every language list in core.
- Catalogs use the standard layout `locale/<code>/LC_MESSAGES/<domain>.po`, without committed `.pot` templates.
- Domain `core` exists for every language except the source language `en`. Every message carries a `msgctxt` naming its source: `role:<role>:description`, `category:<dotted path>:title|description`, `menu:<key>:title|description`, `logout:<key>`.
- Domain `docs` exists for the 47 languages LibreTranslate supports. Its messages come from the Sphinx `gettext` builder run over the same generated sources the documentation build uses, compacted into the single domain `docs`.
- Machine translations carry the translator comment `libretranslate`. A human translation never carries it and is never overwritten.

## Acceptance Criteria

- [x] `meta/languages.yml` lists exactly the 184 ISO 639-1 languages, each with English name, native name and direction `ltr` or `rtl`.
- [x] `make i18n-extract` writes `locale/<code>/LC_MESSAGES/core.po` for all 183 non-English languages, holding every role description, category title and description, dashboard menu label and logout panel string under the `msgctxt` of its source.
- [x] `make i18n-extract` writes `locale/<code>/LC_MESSAGES/docs.po` for every language LibreTranslate supports, holding the messages of the Sphinx `gettext` build of the documentation.
- [x] Running `make i18n-extract` twice in a row leaves the working tree unchanged.
- [x] After a source string changes, `make i18n-extract` keeps the previous translation as a fuzzy entry, and after a source string is removed its entry is gone.
- [x] `make i18n-translate domain=core` starts a LibreTranslate container with the image and version of `roles/web-svc-libretranslate/meta/services.yml`, and no container of it remains after the target ends, on success and on failure.
- [ ] After `make i18n-translate domain=core`, no `msgstr` is empty or fuzzy in `core.po` of any language LibreTranslate supports, and every `core.po` of the other languages is left untouched.
- [x] Every machine translation written by `make i18n-translate` carries the translator comment `libretranslate`, and an entry with a human translation is byte-identical before and after the run.
- [x] A machine translation that drops or alters a `{name}`, `%(name)s` or `%s` placeholder, an inline literal or a URL of its source is discarded, left empty and reported, never written.
- [x] `make i18n-translate domain=<domain> languages=<codes>` translates only the listed languages.
- [ ] `make i18n-translate domain=docs languages=de` fills every `msgstr` of the German `docs.po`.
- [x] A lint test fails when a catalog is out of date with the extracted sources, when a language of `meta/languages.yml` has no `core.po`, or when a translated entry breaks a placeholder of its source.
- [x] Unit tests exercise extraction, the merge rules and the translator against a fake LibreTranslate server.
