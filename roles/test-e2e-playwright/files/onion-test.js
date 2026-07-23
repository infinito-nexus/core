/**
 * Custom Playwright `test` whose worker-scoped `browser` is launched directly so
 * Firefox user-prefs actually apply (the test runner ignores
 * `use.launchOptions.firefoxUserPrefs`). On Firefox — the browser the real Tor
 * Browser is based on — set the prefs that make `.onion` a secure context
 * (RFC 7686) so the Web Crypto API used by keycloak-js is available, and route
 * `.onion` through the SOCKS proxy. Chromium/clearnet launches unchanged.
 */
const base = require("@playwright/test");

const isOnion = Object.values(process.env).some(
  (value) => typeof value === "string" && /\bhttps?:\/\/[^/,\s"']+\.onion\b/i.test(value)
);

const test = base.test.extend({
  browser: async ({ playwright }, use) => {
    const proxy = process.env.PLAYWRIGHT_PROXY
      ? { server: process.env.PLAYWRIGHT_PROXY }
      : undefined;
    let browser;
    if (isOnion) {
      browser = await playwright.firefox.launch({
        proxy,
        firefoxUserPrefs: {
          "dom.securecontext.allowlist_onions": true,
          "network.proxy.socks_remote_dns": true,
          "network.dns.blockDotOnion": false,
          "network.http.sendOriginHeader": 2,
          "network.http.referer.hideOnionSource": false,
          "security.mixed_content.upgrade_display_content": false,
          "security.mixed_content.block_display_content": false,
          "security.mixed_content.block_active_content": false,
        },
      });
    } else {
      browser = await playwright.chromium.launch({ proxy });
    }
    await use(browser);
    await browser.close();
  },
});

module.exports = { ...base, test };
