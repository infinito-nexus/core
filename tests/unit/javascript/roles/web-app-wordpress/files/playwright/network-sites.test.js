const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const Module = require("node:module");

const loadModule = Module._load;
Module._load = function (request, ...rest) {
  return request === "@playwright/test" ? {} : loadModule.call(this, request, ...rest);
};

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const { networkSites, networkTenants, canonicalMainOrigin } = require(
  path.join(PROJECT_ROOT, "roles/web-app-wordpress/files/playwright/network-sites.js"),
);
const { DOMAIN } = require(path.join(PROJECT_ROOT, "tests/unit/javascript/utils/domain.js"));
const { escapeRegex } = require(path.join(PROJECT_ROOT, "roles/test-e2e-playwright/files/personas/utils/dom.js"));

const NODE = "b5abfs7uwr23x6vbjxqjatyscpmkm6qkmkla7eyapdi4zpwtrz6o4nqd.onion";
const LABELS = ["blog", "biberblog", "biber.blog"];
const SITES = LABELS.map((label) => `${label}.${DOMAIN}`);
const SIBLINGS = LABELS.map((label) => `${label}.${NODE}`);
const BASE_URLS = LABELS.map((label) => `https://${label}.${DOMAIN}/,http://${label}.${NODE}/`).join(";");

function groupMap(tenants) {
  const map = { "/roles/web-app-wordpress/network-administrator": { network: true } };
  for (const tenant of tenants) {
    map[`/roles/web-app-wordpress/${tenant}/editor`] = { role: "editor", tenant };
  }
  return JSON.stringify(map);
}

test("every network site lists its domain first and its network siblings after it", () => {
  assert.deepEqual(
    networkSites(BASE_URLS),
    SITES.map((site, index) => [site, SIBLINGS[index]]),
  );
});

test("an unset network base URL list fails loudly", () => {
  assert.throws(() => networkSites(undefined), /WORDPRESS_NETWORK_BASE_URLS must be set/);
});

test("a network sibling in the group map never becomes a site of its own", () => {
  const env = { networkBaseUrls: BASE_URLS, rbacGroupMapJson: groupMap([...SITES, ...SIBLINGS]), canonicalDomain: SITES[0] };
  assert.deepEqual(networkTenants(env), { primary: SITES[0], children: SITES.slice(1) });
});

test("the onion pass resolves its canonical domain to the main site's domain", () => {
  const env = { networkBaseUrls: BASE_URLS, rbacGroupMapJson: groupMap(SITES), canonicalDomain: SIBLINGS[0].toUpperCase() };
  assert.deepEqual(networkTenants(env), { primary: SITES[0], children: SITES.slice(1) });
});

test("both passes reach the main site on the canonical network, where the own sites are served", () => {
  for (const canonicalDomain of [SITES[0], SIBLINGS[0]]) {
    const env = { networkBaseUrls: BASE_URLS, rbacGroupMapJson: groupMap(SITES), canonicalDomain };
    assert.equal(canonicalMainOrigin(env), `https://${SITES[0]}`);
  }
});

test("a network site without a per-site group fails loudly", () => {
  const env = { networkBaseUrls: BASE_URLS, rbacGroupMapJson: groupMap(SITES.slice(0, 2)), canonicalDomain: SITES[0] };
  assert.throws(() => networkTenants(env), new RegExp(`no per-site group for ${escapeRegex(SITES[2])}`));
});

test("a canonical domain outside the network fails loudly", () => {
  const env = { networkBaseUrls: BASE_URLS, rbacGroupMapJson: groupMap(SITES), canonicalDomain: `other.${DOMAIN}` };
  assert.throws(() => networkTenants(env), /is no host of a network site/);
});
