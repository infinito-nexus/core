# 016 - Fediwall multi-wall via OIDC-protected runtime upload

## User Story

As an Infinito.Nexus admin, I want to host multiple Fediwalls under distinct path slugs on a single `fediwall.{{ DOMAIN_PRIMARY }}` deployment and manage their `wall-config.json` files at runtime through an OIDC-protected upload UI, so that I can publish purpose-built media walls (per event, hashtag, account set, etc.) without redeploying the [`web-app-fediwall`](../../roles/web-app-fediwall/) role for every new wall.

## Acceptance Criteria

- [ ] The static Fediwall SPA is served from `https://fediwall.{{ DOMAIN_PRIMARY }}/<slug>/` for every published slug, and each request resolves the slug-specific `wall-config.json` from the same path.
- [ ] An authenticated `POST /admin/walls` endpoint behind [`web-app-oauth2-proxy`](../../roles/web-app-oauth2-proxy/) accepts a `multipart/form-data` upload with fields `slug` and `file`, persists `wall-config.json` to `<persistent_volume>/walls/<slug>/wall-config.json`, and returns `201`.
- [ ] Unauthenticated requests to any `/admin/*` endpoint are rejected with `401` (not `200` or `403`).
- [ ] The `slug` is validated against `^[a-z0-9][a-z0-9-]{0,63}$`; path-traversal payloads (`..`, slashes, control chars) and reserved slugs (e.g. `admin`, `assets`, empty) are rejected with `400`.
- [ ] The uploaded file is validated as JSON and against the Fediwall `Config` shape (every field from upstream [`src/types.ts`](https://github.com/defnull/fediwall/blob/main/src/types.ts) `Config`); malformed payloads are rejected with `422` and a field-level error list.
- [ ] An authenticated `DELETE /admin/walls/<slug>` endpoint removes `<persistent_volume>/walls/<slug>/`; the next anonymous request to `/<slug>/` returns `404`.
- [ ] An authenticated `GET /admin/walls` returns the list of currently published slugs as JSON.
- [ ] The public root `/` renders an HTML link list of all currently published walls; the list updates on the next page load after a successful upload or delete (no admin login required to view).
- [ ] Wall configs and slug directories survive container restart and `make deploy-reuse-kept-apps INFINITO_APPS=web-app-fediwall`; an existing wall is reachable byte-identical after a redeploy.
- [ ] CSP `connect-src` for every `/<slug>/` continues to be governed by [`lookup('fediwall_active', 'url_bases')`](../../plugins/lookup/fediwall_active.py); the multi-wall feature MUST NOT bypass the existing whitelist.
- [ ] End-to-end Playwright in [`roles/web-app-fediwall/files/playwright/playwright.spec.js`](../../roles/web-app-fediwall/files/playwright/playwright.spec.js) covers: anonymous read of an existing `/<slug>/`, anonymous `401` on `/admin/walls`, authenticated round-trip (upload → read → delete → `404`), slug-collision rejection (`409`), and slug-validation rejection (`400`).
- [ ] This requirement file is cross-linked from the implementing PR; the PR description references this file.
