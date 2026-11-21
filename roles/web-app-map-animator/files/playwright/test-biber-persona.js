const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { skipUnlessServiceEnabled } = require("./service-gating");

const PROBE_LINK = "#kf=playwrightprobe";

async function removeProbeJob(card) {
  for (let step = 0; step < 3 && (await card.count()) > 0; step += 1) {
    const button = card.getByRole("button", { name: /^(Cancel|Delete)$/ });
    const label = ((await button.textContent({ timeout: resolveTimeout(15_000) })) || "").trim();
    await button.click({ timeout: resolveTimeout(15_000) });
    await expect(card.getByRole("button", { name: label })).toHaveCount(0, { timeout: resolveTimeout(15_000) });
  }
}

async function withDeadline(work, ms, label) {
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${label} exceeded ${ms} ms`)), ms);
  });
  try {
    return await Promise.race([work, deadline]);
  } finally {
    clearTimeout(timer);
  }
}

exports.register = function (shared) {
  test("biber: login → editor → queue a render → cancel it → logout", async ({ page }) => {
    skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(240_000)); // Keycloak round-trip of the oauth2 gate, native login, and the renderer's cancel
    expect(shared.env.biberUsername, "BIBER_USERNAME must be set").toBeTruthy();
    expect(shared.env.biberPassword, "BIBER_PASSWORD must be set").toBeTruthy();

    page.on("dialog", (dialog) => dialog.accept().catch(() => {}));

    await shared.loginToApp(page, shared.env.biberUsername, shared.env.biberPassword);
    await shared.gotoRenders(page);
    await expect(page, "biber's session must open the renders page").toHaveURL(/\/renders\/$/, {
      timeout: resolveTimeout(30_000),
    });
    await expect(page.locator("#user"), "the renders page must name the signed-in user").toHaveText(
      shared.env.biberUsername,
      { timeout: resolveTimeout(30_000) },
    );

    const title = `playwright-${Date.now()}`;
    const form = page.locator("form#new");
    const card = page.locator("li.job", { hasText: title });
    try {
      await form.getByLabel("Share link").fill(PROBE_LINK);
      await form.getByLabel("Title").fill(title);
      await form.getByRole("button", { name: "Add to queue" }).click({ timeout: resolveTimeout(30_000) });
      await expect(page.locator("#formMessage")).toHaveText("Added.", { timeout: resolveTimeout(30_000) });
      await expect(card, "the queued render must show up in biber's list").toBeVisible({
        timeout: resolveTimeout(30_000),
      });
    } finally {
      await withDeadline(removeProbeJob(card), resolveTimeout(60_000), "probe job cleanup").catch((err) =>
        console.warn(`probe job cleanup: ${err.message}`),
      );
    }
    await expect(card, "the probe render must be gone after cancel/delete").toHaveCount(0);

    await shared.logout(page);
  });
};
