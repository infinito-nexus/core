const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("../timeouts");
const { performKeycloakLoginForm, decodeDotenvQuotedValue } = require("../personas");
const shared = require("../_shared");

const SESSION_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

function skipUnlessAddonArchitecture(addonId, architectures) {
  const architecture = decodeDotenvQuotedValue(process.env.MATTERMOST_ARCHITECTURE || "");
  test.skip(
    !architecture || !architectures.includes(architecture),
    `meta/addons/${addonId}.yml declares architectures: [${architectures.join(", ")}] and this node runs ` +
      `${architecture || "an unmapped architecture"}, so tasks/utils/addon.yml installed nothing to assert against`,
  );
}

async function activePluginIds(page) {
  const baseUrl = shared.expectedMattermostBaseUrl();

  await shared.startMattermostSsoFlow(page, baseUrl);
  await expect
    .poll(() => page.url(), {
      timeout: resolveTimeout(30_000),
      message: `Expected redirect to Keycloak OIDC: ${shared.expectedOidcAuthUrl()}`,
    })
    .toContain(shared.expectedOidcAuthUrl());

  await performKeycloakLoginForm(page, shared.env.adminUsername, shared.env.adminPassword);
  await shared.waitForMattermostChannelView(page, resolveTimeout(120_000));

  const response = await page.request.get(`${baseUrl}/api/v4/plugins`, {
    headers: SESSION_HEADERS,
    failOnStatusCode: false,
  });
  expect(
    response.status(),
    "the administrator session must be allowed to read /api/v4/plugins; a non-200 means the OIDC login did not land a system-admin session",
  ).toBe(200);

  const body = await response.json();
  return (body.active || []).map((manifest) => manifest.id);
}

module.exports = { activePluginIds, skipUnlessAddonArchitecture };
