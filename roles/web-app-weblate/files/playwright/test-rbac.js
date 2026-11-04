const { test, expect } = require("@playwright/test");
const { decodeDotenvQuotedValue, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const apiToken = requireDotenvValue(process.env.WEBLATE_API_TOKEN, "WEBLATE_API_TOKEN");
const adminUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME"));
const biberUsername = decodeDotenvQuotedValue(requireDotenvValue(process.env.BIBER_USERNAME, "BIBER_USERNAME"));
const managedTeams = decodeDotenvQuotedValue(
  requireDotenvValue(process.env.WEBLATE_RBAC_TEAM_NAMES, "WEBLATE_RBAC_TEAM_NAMES"),
).split(",");

async function api(request, url) {
  const response = await request.get(url, {
    headers: { Authorization: `Token ${apiToken}` },
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
  });
  expect(response.status(), `Expected ${url} to answer`).toBe(200);
  return response.json();
}

function userUrl(username) {
  return `${appBaseUrl}/api/users/${encodeURIComponent(username)}/`;
}

exports.register = function () {
  test("rbac: the administrator role group makes the platform administrator a superuser", async ({ request }) => {
    const admin = await api(request, userUrl(adminUsername));
    expect(admin.is_superuser, "the administrator role group must map to Weblate's superuser flag").toBe(true);
  });

  test("rbac: biber, in no Weblate role group, is neither superuser nor in a managed team", async ({ request }) => {
    skipUnlessServiceEnabled("sso");
    const biber = await api(request, userUrl(biberUsername));
    expect(biber.is_superuser, "biber holds no administrator role").toBe(false);
    const teams = [];
    for (const url of biber.groups) {
      teams.push((await api(request, url)).name);
    }
    for (const team of managedTeams) {
      expect(teams, `biber holds no role that maps to the ${team} team`).not.toContain(team);
    }
  });
};
