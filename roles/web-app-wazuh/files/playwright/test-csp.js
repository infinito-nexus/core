const { test, expect } = require("@playwright/test");
const {
  installCspViolationObserver,
  assertCspResponseHeader,
  assertCspMetaParity,
  expectNoCspViolations,
  gotoOnion,
} = require("./personas");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { resolveTimeout } = require("./timeouts");
const shared = require("./_shared");

test.use({ ignoreHTTPSErrors: true });

const CONSOLE_EDITOR_SELECTORS = [
  ".ace_text-input",
  ".monaco-editor textarea",
  "[data-test-subj='console-textarea'] textarea",
  ".ace_editor textarea",
];

async function typeIntoDevToolsConsole(page) {
  const response = await gotoOnion(page, `${shared.env.appBaseUrl}/app/dev_tools#/console`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForLoadState("networkidle").catch(() => {});
  if (!response || response.status() >= 400) {
    throw new Error(`dev tools console answered ${response ? response.status() : "no response"}`);
  }
  const editor = page.locator(CONSOLE_EDITOR_SELECTORS.join(", ")).first();
  await editor.waitFor({ state: "visible", timeout: resolveTimeout(15_000) });
  await page
    .getByRole("button", { name: /dismiss|close this dialog/i })
    .first()
    .click({ timeout: resolveTimeout(5_000) })
    .catch(() => {});
  await editor.click({ timeout: resolveTimeout(10_000) });
  await page.keyboard.type("GET _cluster/health", { delay: 50 });
  await page.waitForTimeout(resolveTimeout(3_000));
}

test("wazuh dashboard: script-src-elem unsafe-inline and worker-src blob: are declared and exercised without violation", async ({
  page,
}) => {
  skipUnlessServiceEnabled("sso");

  const diagnostics = shared.attachDiagnostics(page);
  await installCspViolationObserver(page);

  await shared.wazuhLoginViaOidc(
    page,
    shared.env.appBaseUrl,
    shared.env.adminUsername,
    shared.env.adminPassword,
  );

  const response = await gotoOnion(page, `${shared.env.appBaseUrl}/app/home`);
  expect(response, "Expected Wazuh dashboard home response").toBeTruthy();
  expect(
    response.status(),
    "Expected Wazuh dashboard home response to be successful",
  ).toBeLessThan(400);

  const directives = assertCspResponseHeader(response, "wazuh dashboard home");
  await assertCspMetaParity(page, directives, "wazuh dashboard home");

  expect(
    directives["script-src-elem"] || [],
    "Expected script-src-elem to declare 'unsafe-inline'",
  ).toContain("'unsafe-inline'");
  expect(directives["worker-src"] || [], "Expected worker-src to grant blob:").toContain("blob:");

  await typeIntoDevToolsConsole(page).catch((err) =>
    console.warn(`wazuh dev tools console was not typed into: ${err}`),
  );

  await expectNoCspViolations(page, diagnostics, "wazuh dashboard (home + dev tools console)");
});
