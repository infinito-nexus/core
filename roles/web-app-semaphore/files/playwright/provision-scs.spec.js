const { test } = require("@playwright/test");

const shared = require("./_shared");

test.use({
  ignoreHTTPSErrors: true,
  trace: "off",
  video: "off",
  screenshot: "off",
});

test.beforeEach(shared.beforeEach);

require("./test-provision").registerScs(shared);
