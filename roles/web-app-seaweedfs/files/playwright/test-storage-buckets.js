const { test } = require("@playwright/test");

exports.register = function (shared) {
  const { env, keycloakLogin, isAuthChain, expect } = shared;

  test("storage: a bucket exists for every consumer with the service enabled", async ({ page }) => {
    test.skip(!env.ssoEnabled, "SSO disabled");
    test.skip(env.consumerBuckets.length === 0, "no object-store consumers on this host");

    await page.goto(env.filerUrl, { waitUntil: "domcontentloaded" });
    if (isAuthChain(page.url())) {
      await keycloakLogin(page, env.adminUsername, env.adminPassword);
    }
    await page.waitForLoadState("networkidle").catch(() => {});

    await page.goto(`${env.filerUrl.replace(/\/$/, "")}/buckets/`, { waitUntil: "domcontentloaded" });
    const listing = (await page.locator("body").innerText().catch(() => "")) || "";

    const missing = env.consumerBuckets.filter((b) => !listing.includes(b.bucket));
    expect(
      missing,
      `buckets missing on SeaweedFS: ${missing.map((b) => `${b.role}->${b.bucket}`).join(", ")}`
    ).toHaveLength(0);
  });
};
