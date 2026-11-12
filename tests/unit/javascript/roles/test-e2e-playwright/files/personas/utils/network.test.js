const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../../..");
const { networkOf, isTorHost, isTorUrl, torOrigins, crossNetworkLeaks } = require(
  path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/network.js"),
);
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));

const SUFFIXES = { tor: ".onion" };
process.env.PLAYWRIGHT_NETWORK_SUFFIXES = JSON.stringify(SUFFIXES);
const NODE = "b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion";
const CLEARNET_PAGE = `https://wazuh.${DOMAIN}/app/wz-home`;
const ONION_PAGE = `http://wazuh.${NODE}/app/wz-home`;
const ISSUER = `auth.${DOMAIN}`;
const CSS = `https://css.${DOMAIN}/global.css`;
const CDN_JS = `https://cdn.${DOMAIN}/app.js`;

test("a host is classified by the registry suffixes", () => {
  assert.equal(networkOf(`cdn.${NODE}`, SUFFIXES), "tor");
  assert.equal(networkOf(`cdn.${DOMAIN}`, SUFFIXES), "clearnet");
  assert.equal(networkOf(`CDN.${NODE.toUpperCase()}.`, SUFFIXES), "tor");
});

test("tor hosts and URLs are classified by the rendered registry table", () => {
  assert.equal(isTorHost(`cdn.${NODE}`), true);
  assert.equal(isTorHost(`cdn.${DOMAIN}`), false);
  assert.equal(isTorHost(""), false);
  assert.equal(isTorUrl(`http://cdn.${NODE}:8080/x?y=1`), true);
  assert.equal(isTorUrl(`https://cdn.${DOMAIN}/?next=http://cdn.${NODE}/`), false);
  assert.equal(isTorUrl("/relative/path"), false);
});

test("tor origins are collected from free text and JSON lists", () => {
  assert.deepEqual(
    torOrigins([
      `["http://a.${NODE}/x","https://b.${DOMAIN}/"]`,
      `see http://c.${NODE}:8080/ now`,
      42,
      `http://a.${NODE}/y`,
    ]),
    [`http://a.${NODE}`, `http://c.${NODE}:8080`],
  );
});

test("a run without the rendered table fails loudly", () => {
  const rendered = process.env.PLAYWRIGHT_NETWORK_SUFFIXES;
  delete process.env.PLAYWRIGHT_NETWORK_SUFFIXES;
  try {
    assert.throws(() => isTorHost(`cdn.${NODE}`), /PLAYWRIGHT_NETWORK_SUFFIXES is missing/);
  } finally {
    process.env.PLAYWRIGHT_NETWORK_SUFFIXES = rendered;
  }
});

test("the wazuh regression of fork run 35925283225 is reported", () => {
  const leaks = crossNetworkLeaks({
    requests: [
      { url: `http://cdn.${NODE}/_shared/fonts/inter.css`, documentUrl: CLEARNET_PAGE },
      { url: `http://matomo.${NODE}/matomo.js`, documentUrl: CLEARNET_PAGE },
    ],
    consoleErrors: [
      `Mixed Content: The page at '${CLEARNET_PAGE}' was loaded over HTTPS, but ` +
        `requested an insecure script 'http://matomo.${NODE}/matomo.js'. This ` +
        "request has been blocked; the content must be served over HTTPS.",
    ],
    suffixes: SUFFIXES,
    allowedHosts: [ISSUER],
  });
  assert.equal(leaks.length, 3);
  assert.match(leaks[0], /clearnet document .* requested tor http:\/\/cdn\./);
  assert.match(leaks[2], /^blocked mixed content: /);
});

test("an onion document reaching a clearnet provider is reported", () => {
  const leaks = crossNetworkLeaks({
    requests: [{ url: CSS, documentUrl: ONION_PAGE }],
    consoleErrors: [],
    suffixes: SUFFIXES,
    allowedHosts: [ISSUER],
  });
  assert.deepEqual(leaks, [
    `tor document ${ONION_PAGE} requested clearnet ${CSS}`,
  ]);
});

test("the SSO issuer is reachable from every network", () => {
  const leaks = crossNetworkLeaks({
    requests: [
      { url: `https://${ISSUER}/realms/${DOMAIN}/protocol/openid-connect/auth`, documentUrl: ONION_PAGE },
    ],
    consoleErrors: [],
    suffixes: SUFFIXES,
    allowedHosts: [ISSUER],
  });
  assert.deepEqual(leaks, []);
});

test("requests inside the document network pass", () => {
  const leaks = crossNetworkLeaks({
    requests: [
      { url: `http://cdn.${NODE}/app.js`, documentUrl: ONION_PAGE },
      { url: CDN_JS, documentUrl: CLEARNET_PAGE },
      { url: "data:image/png;base64,AAAA", documentUrl: CLEARNET_PAGE },
      { url: CDN_JS, documentUrl: "about:blank" },
    ],
    consoleErrors: ["TypeError: x is undefined"],
    suffixes: SUFFIXES,
    allowedHosts: [ISSUER],
  });
  assert.deepEqual(leaks, []);
});
