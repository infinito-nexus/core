const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeUrl, readEnv, runGuestFlow } = require("./personas");
const { crossNetworkLeaks } = require("./personas/utils/network");
const { resolveTimeout } = require("./timeouts");

const SETTLE_MS = 15_000;

test.describe("network isolation", () => {
  test.skip(
    readEnv("PLAYWRIGHT_NETWORK_LEAK").toLowerCase() !== "true",
    "the node serves this role on one network only",
  );

  test("guest stays signed out on this network", async ({ page }) => {
    await runGuestFlow(page);
  });

  test("the page stays inside its network", async ({ page }) => {
    const baseUrl = normalizeUrl(process.env.APP_BASE_URL);
    test.skip(!baseUrl, "role has no public surface");
    test.setTimeout(resolveTimeout(120_000));

    const requests = [];
    const consoleErrors = [];
    page.on("request", (request) => {
      let documentUrl = baseUrl;
      if (!request.isNavigationRequest()) {
        try {
          documentUrl = request.frame().url();
        } catch {
          documentUrl = baseUrl;
        }
      }
      requests.push({ url: request.url(), documentUrl });
    });
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    await page.context().clearCookies();
    await gotoOnion(page, baseUrl, { waitUntil: "domcontentloaded" });
    await page
      .waitForLoadState("networkidle", { timeout: resolveTimeout(SETTLE_MS) })
      .catch((err) => {
        if (err.name !== "TimeoutError") throw err;
      });

    const leaks = crossNetworkLeaks({
      requests,
      consoleErrors,
      suffixes: JSON.parse(readEnv("PLAYWRIGHT_NETWORK_SUFFIXES")),
      allowedHosts: readEnv("PLAYWRIGHT_NETWORK_ALLOWED_HOSTS").split(",").filter(Boolean),
    });
    expect(leaks, leaks.join("\n")).toEqual([]);
  });
});
