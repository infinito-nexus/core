const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

// Matrix SSO has several long-tail failure modes (Synapse rc_login rate
// limits, Element rust_crypto "Skip verification" dialog, first-run Synapse
// consent page, transient #/login bounce). The signIn helper walks through
// each with generous per-step waits, so the default 300s budget is far too
// tight — the DM test signs in twice and, when the prior per-user OIDC
// tests in the same spec have drained Synapse's rc_login burst, each
// sign-in can spend 5+ minutes cycling through consent↔M_LIMIT_EXCEEDED
// ping-pong before authenticating. 1200s (20 min) covers the worst case.
test.setTimeout(1_200_000);

test.beforeEach(shared.beforeEach);

require("./test-csp").register(shared);
require("./test-login-admin-oidc").register(shared);
require("./test-login-biber-oidc").register(shared);
require("./test-login-admin-native").register(shared);
require("./test-dm-admin-biber").register(shared);
require("./test-guest-persona").register(shared);
require("./test-element-call").register(shared);
require("./test-bridge-roster").register(shared);
require("./test-seaweedfs");
