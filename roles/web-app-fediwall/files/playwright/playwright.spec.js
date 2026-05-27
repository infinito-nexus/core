// Fediwall Playwright spec — orchestration only. Shared env vars, login
// helpers (Mastodon OIDC + Friendica ldapauth + post-on-Friendica /compose
// flow), and the wall-content assertion helpers live in `_shared.js`; each
// scenario is registered from its own `test-*.js` companion module so each
// test stays atomar and individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

// Baseline scenarios — MUST pass even when every shared service is disabled.
require("./test-fediwall-root-tls").register(shared);
require("./test-fediwall-default-slug").register(shared);
require("./test-fediwall-html-content").register(shared);
require("./test-fediwall-wall-config").register(shared);
require("./test-fediwall-spa-mount").register(shared);

// Cross-Fediverse scenario — requires Mastodon AND Friendica.
require("./test-walls-surface-posts").register(shared);

// Persona scenarios. Bodies live in the shared helper
// roles/test-e2e-playwright/files/personas.js so every role's persona
// flow stays consistent.
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
