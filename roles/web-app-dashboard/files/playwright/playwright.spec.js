// Dashboard Playwright spec — orchestration only. Shared env vars,
// helpers, and the `beforeEach` env-presence guard live in `_shared.js`;
// each scenario is registered from its own `test-*.js` companion module
// so each test stays atomar and individually inspectable.

const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

test.beforeEach(shared.beforeEach);

// CSP + canonical-domain baseline.
require("./test-csp-canonical-domain").register(shared);
require("./test-no-console-noise").register(shared);

// Per-service shared / role-local asset coverage.
require("./test-shared-css").register(shared);
require("./test-cdn-role-stylesheet").register(shared);
require("./test-logout-js-injection").register(shared);
require("./test-simpleicons-cards").register(shared);
require("./test-icons").register(shared);
require("./test-header-navbar-logos").register(shared);
require("./test-iframe-sync").register(shared);
require("./test-matomo-integration").register(shared);

// OIDC login → account → logout round-trip.
require("./test-oidc-login").register(shared);

// Tile reachability per consumer role declared via roles_with_service('dashboard').
require("./test-tile-reachability").register(shared);

// Persona scenarios. Bodies live in the shared helper
// roles/test-e2e-playwright/files/personas.js so every role's persona
// flow stays consistent.
require("./test-guest-persona").register(shared);
require("./test-biber-persona").register(shared);
require("./test-administrator-persona").register(shared);
