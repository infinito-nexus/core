const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");

test.beforeEach(() => {
  skipUnlessServiceEnabled("knot");
  expect(process.env.KNOT_ZONE, "KNOT_ZONE must be set").toBeTruthy();
  expect(process.env.KNOT_SERVERS, "KNOT_SERVERS must be set").toBeTruthy();
});

require("./test-subzone");
