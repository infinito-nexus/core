const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
});

test.beforeEach(shared.beforeEach);

require("./test-landing").register(shared);
require("./test-csp-headers").register(shared);
require("./test-alias-domain").register(shared);
require("./test-login-administrator").register(shared);
require("./test-login-biber").register(shared);
require("./test-guest-persona").register(shared);
require("./test-rest-api-ticket-create").register(shared);
require("./test-ticket-create-as-customer").register(shared);
require("./test-ticket-reply-as-agent").register(shared);
require("./test-websocket-realtime").register(shared);
require("./test-mail-to-ticket").register(shared);
