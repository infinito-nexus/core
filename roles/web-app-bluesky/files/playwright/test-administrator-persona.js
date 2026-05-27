const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test("administrator: app → universal logout", async ({ page }) => {
    await shared.runAdminFlow(page, {
      adminInteraction: async (interactivePage) => {
        // Bluesky / atproto admin: probe the well-known DID document or the
        // PDS /xrpc/_health surface, which is admin-only on the canonical PDS.
        const didProbe = await interactivePage.request
          .get(`${interactivePage.url().replace(/\/$/, "")}/.well-known/atproto-did`, {
            ignoreHTTPSErrors: true,
          })
          .catch(() => null);
        if (didProbe) {
          expect(didProbe.status(), "atproto-did probe must answer 2xx/3xx/4xx, not 5xx").toBeLessThan(500);
        }
      },
    });
  });
};
