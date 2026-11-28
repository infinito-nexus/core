const { test, expect } = require("@playwright/test");
const { gotoOnion, requireDotenvValue } = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

const catalogue = JSON.parse(requireDotenvValue(process.env.PROFILE_LOCK_I18N_JSON, "PROFILE_LOCK_I18N_JSON"));
const lockedSelectors = JSON.parse(
  requireDotenvValue(process.env.PROFILE_LOCK_SELECTORS_JSON, "PROFILE_LOCK_SELECTORS_JSON"),
);

const ACTION = { timeout: resolveTimeout(30_000) };
const GERMAN = "de-DE";

test.use({ ignoreHTTPSErrors: true });

/**
 * Args:
 *   page: Playwright page on a rendered Grafana page.
 * Returns:
 *   string: the warning the shared lock renderer shows in the page's language.
 */
async function expectedWarning(page) {
  const tags = await page.evaluate(() => [document.documentElement.lang, navigator.language]);
  for (const raw of tags) {
    const tag = String(raw || "").toLowerCase();
    const entry = catalogue[tag] || catalogue[tag.split("-")[0]];
    if (entry) return entry.locked;
  }
  return catalogue.en.locked;
}

/**
 * Args:
 *   page: Playwright page on the Grafana profile of an OAuth account.
 *   warning: the text every locked field must carry as its title.
 */
async function expectEverySelectorLocked(page, warning) {
  for (const [field, selector] of Object.entries(lockedSelectors)) {
    const matches = page.locator(selector);
    await expect
      .poll(() => matches.count(), { message: `the sso field ${field} of meta/forms.yml must match a field of the profile`, ...ACTION })
      .toBeGreaterThan(0);
    const count = await matches.count();
    for (let index = 0; index < count; index += 1) {
      await expect(matches.nth(index), `${field} must be locked because every Keycloak login overwrites it`).toBeDisabled(ACTION);
      await expect(matches.nth(index), `${field} must carry the profile lock warning`).toHaveAttribute("title", warning, ACTION);
    }
  }
}

function identity(user) {
  return { name: user.name, email: user.email, login: user.login };
}

test("biber: the Grafana profile locks name, email and username with the translated warning, and PUT /api/user keeps them", async ({
  page,
  browser,
}) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("javascript");
  test.setTimeout(resolveTimeout(180_000)); // one Keycloak group grant, one OIDC round-trip and the profile render
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.context().clearCookies();
  try {
    await shared.withBiberInGroup(browser, shared.env.auditorGroupPath, async () => {
      await shared.loginViaOidc(page, shared.env.biberUsername, shared.env.biberPassword);
      await gotoOnion(page, `${shared.env.appBaseUrl}/profile`, { waitUntil: "domcontentloaded" });
      await expectEverySelectorLocked(page, await expectedWarning(page));

      const before = await shared.grafanaApi(page, "GET", "/api/user");
      expect(before.ok(), `GET /api/user must answer biber: ${before.status()}`).toBe(true);
      const stored = identity(await before.json());
      const suffix = String(Date.now()).slice(-6);
      const update = await shared.grafanaApi(page, "PUT", "/api/user", {
        name: `${stored.name} tampered`,
        email: `tampered-${suffix}@example.invalid`,
        login: `${stored.login}-tampered-${suffix}`,
      });
      const refusal = await update.text();
      expect(update.status(), `Grafana must refuse the profile update of an OAuth account: ${refusal}`).toBe(403);
      expect(refusal, "the refusal must come from the external-user guard, not from the CSRF check").toContain(
        "Cannot update external User",
      );

      const after = await shared.grafanaApi(page, "GET", "/api/user");
      expect(after.ok(), `GET /api/user must answer biber: ${after.status()}`).toBe(true);
      expect(identity(await after.json()), "a direct PUT /api/user must not change name, email or login").toEqual(stored);
      expect(errors, "the injected lock renderer must not throw").toEqual([]);
    });
  } finally {
    await page.context().clearCookies().catch(() => {});
  }
});

test("biber: a German Grafana profile shows the lock warning in German, not in English", async ({ browser }) => {
  skipUnlessServiceEnabled("sso");
  skipUnlessServiceEnabled("javascript");
  test.setTimeout(resolveTimeout(180_000)); // one Keycloak group grant, one OIDC round-trip and two profile renders
  const context = await browser.newContext({ ignoreHTTPSErrors: true, locale: GERMAN });
  const page = await context.newPage();
  try {
    await shared.withBiberInGroup(browser, shared.env.auditorGroupPath, async () => {
      await shared.loginViaOidc(page, shared.env.biberUsername, shared.env.biberPassword);
      const preferences = await shared.grafanaApi(page, "GET", "/api/user/preferences");
      expect(preferences.ok(), `GET /api/user/preferences must answer biber: ${preferences.status()}`).toBe(true);
      // Grafana omits `language` while the account has none set; "" restores that default.
      const reported = (await preferences.json()).language;
      expect(["undefined", "string"], "Grafana's language preference must be absent or a string").toContain(
        typeof reported,
      );
      const previous = reported ?? "";
      try {
        const german = await shared.grafanaApi(page, "PATCH", "/api/user/preferences", { language: GERMAN });
        expect(german.ok(), `Grafana must store German as biber's language: ${await german.text()}`).toBe(true);

        await gotoOnion(page, `${shared.env.appBaseUrl}/profile`, { waitUntil: "domcontentloaded" });
        await expect(page.locator("html"), "a German account must get a German Grafana page").toHaveAttribute(
          "lang",
          /^de\b/i,
          ACTION,
        );
        const field = page.locator(Object.values(lockedSelectors)[0]).first();
        await expect(field, "the lock renderer must decorate the field").toHaveAttribute("title", /\S/, ACTION);
        const title = await field.getAttribute("title");
        expect(title, "the German warning must differ from the English text; translate profile_lock:locked").not.toBe(
          catalogue.en.locked,
        );
        expect(catalogue.de, "the embedded catalogue must carry German").toBeTruthy();
        expect(title, "the warning must be the German catalogue text").toBe(catalogue.de.locked);
      } finally {
        await shared
          .grafanaApi(page, "PATCH", "/api/user/preferences", { language: previous })
          .catch((error) => console.warn(`Restoring biber's Grafana language failed: ${error}`));
      }
    });
  } finally {
    await context.close().catch(() => {});
  }
});
