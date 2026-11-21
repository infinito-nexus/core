const { test, expect } = require("@playwright/test");
const { gotoOnion, normalizeBaseUrl, requireDotenvValue } = require("./personas");
const { resolveTimeout } = require("./timeouts");

const appBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.APP_BASE_URL, "APP_BASE_URL"));
const apiToken = requireDotenvValue(process.env.WEBLATE_API_TOKEN, "WEBLATE_API_TOKEN");
const adminUsername = requireDotenvValue(process.env.ADMIN_USERNAME, "ADMIN_USERNAME");
const adminPassword = requireDotenvValue(process.env.ADMIN_PASSWORD, "ADMIN_PASSWORD");
const nativeEnabled = process.env.LOGIN_METHOD_NATIVE_ENABLED === "true";
const NATIVE_ONLY = "only the native variant signs a local account in, and it runs no translation gateway on this Weblate";
const REFUSAL = "This project requires two-factor authentication";
const BANNER = "You are a member of the team that requires two-factor authentication";
const STATE_TRANSLATED = 20;
const SELECTION_MANUAL = 0;

/**
 * Args:
 *   request: Playwright API request context.
 *   method: HTTP method.
 *   path: API path below /api/.
 *   options: the data or multipart body of the request.
 */
function api(request, method, path, options = {}) {
  return request.fetch(`${appBaseUrl}/api/${path}`, {
    method,
    headers: { Authorization: `Token ${apiToken}` },
    failOnStatusCode: false,
    timeout: resolveTimeout(120_000),
    ...options,
  });
}

/**
 * Args:
 *   response: the API response.
 *   status: the status it must carry.
 *   label: the step, named in the failure message.
 */
async function expectStatus(response, status, label) {
  expect(response.status(), `${label}: ${(await response.text()).slice(0, 300)}`).toBe(status);
  return response;
}

/**
 * Args:
 *   request: Playwright API request context.
 *   path: API path below /api/ that answers a paginated list.
 *   label: what the list must come to hold, named in the failure message.
 */
async function firstResult(request, path, label) {
  let first;
  await expect
    .poll(
      async () => {
        const response = await api(request, "GET", path);
        first = response.ok() ? ((await response.json()).results || [])[0] : undefined;
        return first !== undefined;
      },
      { timeout: resolveTimeout(120_000), message: label },
    )
    .toBe(true);
  return first;
}

exports.register = function () {
  test("two-factor: a flagged project refuses the edit it allowed before, superuser included", async ({ request }) => {
    test.skip(!nativeEnabled, NATIVE_ONLY);
    test.setTimeout(resolveTimeout(300_000));
    const slug = `infinito-2fa-probe-${Date.now()}`;
    await expectStatus(
      await api(request, "POST", "projects/", { data: { name: slug, slug, web: "https://example.org/" } }),
      201,
      "create the probe project",
    );
    try {
      await expectStatus(
        await api(request, "POST", `projects/${slug}/components/`, {
          multipart: {
            name: "probe",
            slug: "probe",
            file_format: "html",
            source_language: "en",
            docfile: {
              name: "probe.html",
              mimeType: "text/html",
              buffer: Buffer.from("<html><body><p>Second factor probe</p></body></html>"),
            },
          },
        }),
        201,
        "create the probe component from a document",
      );
      await firstResult(request, `components/${slug}/probe/translations/`, "the probe component must load its source");
      await expectStatus(
        await api(request, "POST", `components/${slug}/probe/translations/`, { data: { language_code: "de" } }),
        201,
        "add German to the probe component",
      );
      const unit = await firstResult(
        request,
        `translations/${slug}/probe/de/units/`,
        "the German translation must hold the probe string",
      );
      const edit = (target) =>
        api(request, "PATCH", `units/${unit.id}/`, { data: { target: [target], state: STATE_TRANSLATED } });

      await expectStatus(await edit("Probe des zweiten Faktors"), 200, "edit while the project is not flagged");
      await expectStatus(
        await api(request, "PATCH", `projects/${slug}/`, { data: { enforced_2fa: true } }),
        200,
        "flag the probe project",
      );
      const refused = await edit("Zweiter Faktor verlangt");
      expect(refused.status(), "a flagged project refuses an edit to an account without a second factor").toBe(403);
      expect(await refused.text(), "Weblate names the missing second factor as the reason").toContain(REFUSAL);
    } finally {
      await api(request, "DELETE", `projects/${slug}/`);
    }
  });

  test("two-factor: a member of a flagged team sees Weblate's enrollment banner", async ({ page, request }) => {
    test.skip(!nativeEnabled, NATIVE_ONLY);
    test.setTimeout(resolveTimeout(300_000));
    const created = await expectStatus(
      await api(request, "POST", "groups/", {
        data: {
          name: `Infinito 2FA probe ${Date.now()}`,
          project_selection: SELECTION_MANUAL,
          language_selection: SELECTION_MANUAL,
          enforced_2fa: true,
        },
      }),
      201,
      "create the flagged probe team",
    );
    const team = (await created.json()).id;
    try {
      await expectStatus(
        await api(request, "POST", `users/${encodeURIComponent(adminUsername)}/groups/`, { data: { group_id: team } }),
        200,
        "add the administrator to the probe team",
      );
      await page.context().clearCookies();
      await gotoOnion(page, `${appBaseUrl}/accounts/login/`, { waitUntil: "domcontentloaded" });
      await page.locator("input[name='username']").fill(adminUsername);
      const password = page.locator("input[name='password']");
      await password.fill(adminPassword);
      await password.press("Enter");
      await expect(page.getByText(BANNER), "a member of a flagged team without a second factor is told to enroll").toBeVisible({
        timeout: resolveTimeout(60_000),
      });
      await expect(page.getByRole("link", { name: "Configure two-factor authentication" })).toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    } finally {
      await api(request, "DELETE", `groups/${team}/`);
      await page.context().clearCookies();
    }
  });
};
