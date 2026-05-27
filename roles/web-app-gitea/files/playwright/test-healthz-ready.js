// /healthz/ready on the Gitea domain returns a non-5xx response.
//
// This is the endpoint the Blackbox Exporter probes to determine whether
// Gitea is up. A 200 or 401 means the backend is reachable; 502/503 means
// the container is down. This test verifies the healthz endpoint is wired
// correctly.

const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("healthz/ready endpoint returns non-5xx when gitea is running", async ({ request }) => {
    const response = await request.get(shared.healthzReadyUrl());

    expect(
      response.status(),
      `/healthz/ready returned ${response.status()} — ` +
      "502/503 means the Gitea container is down or nginx cannot reach it.",
    ).toBeLessThan(500);
  });
};
