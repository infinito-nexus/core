const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

const { normalizeBaseUrl } = require("./personas");
const { isServiceEnabled, skipUnlessServiceEnabled } = require("./service-gating");

const dashboardJsBaseUrl = normalizeBaseUrl(process.env.DASHBOARD_JS_BASE_URL || "");
const matomoBaseUrl = normalizeBaseUrl(process.env.MATOMO_BASE_URL || "");

async function beforeEach({ page }) {
  await page.setViewportSize({ width: 1440, height: 1100 });

  expect(dashboardJsBaseUrl, "DASHBOARD_JS_BASE_URL must be set in the Playwright env file").toBeTruthy();
  expect(matomoBaseUrl, "MATOMO_BASE_URL must be set in the Playwright env file").toBeTruthy();

  await page.context().clearCookies();
}

function attachDiagnostics(page) {
  const consoleErrors = [];
  const pageErrors = [];
  const responses = [];

  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location();
      consoleErrors.push({
        text: message.text(),
        url: location.url || "",
        lineNumber: location.lineNumber,
        columnNumber: location.columnNumber,
      });
    }
  });

  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });

  page.on("response", (response) => {
    responses.push({
      url: response.url(),
      status: response.status(),
      resourceType: response.request().resourceType(),
    });
  });

  return { consoleErrors, pageErrors, responses };
}

function formatConsoleError(record) {
  if (!record || typeof record === "string") {
    return String(record || "");
  }
  if (!record.url) {
    return record.text;
  }
  return `${record.text} (${record.url}:${record.lineNumber}:${record.columnNumber})`;
}

function formatConsoleErrors(records) {
  return records.map((record) => formatConsoleError(record)).join("\n");
}

function isMatomoConsoleNoise(record) {
  if (!record) {
    return false;
  }
  const text = typeof record === "string" ? record : record.text || "";
  const url = typeof record === "string" ? "" : record.url || "";
  return (
    url.startsWith(matomoBaseUrl) ||
    /matomo/i.test(text) ||
    /_pk_(id|ses)\./i.test(text) ||
    /There was an error setting cookie/i.test(text) ||
    /Can't write cookie on domain/i.test(text)
  );
}

function isKeycloak3pCookieNoise(record) {
  if (!record) {
    return false;
  }
  const text = typeof record === "string" ? record : record.text || "";
  const url = typeof record === "string" ? "" : record.url || "";
  return (
    /\/3p-cookies\//.test(url) ||
    /requestStorageAccess/i.test(text)
  );
}

function expectNoUnexpectedDiagnostics(
  diagnostics,
  { ignoreMatomoConsoleNoise = false } = {}
) {
  expect(diagnostics.pageErrors, `Unexpected page errors: ${diagnostics.pageErrors.join("\n")}`).toEqual([]);
  let unexpectedConsoleErrors = diagnostics.consoleErrors.filter(
    (record) => !isKeycloak3pCookieNoise(record)
  );
  if (ignoreMatomoConsoleNoise) {
    unexpectedConsoleErrors = unexpectedConsoleErrors.filter((record) => !isMatomoConsoleNoise(record));
  }
  expect(
    unexpectedConsoleErrors,
    `Unexpected console errors: ${formatConsoleErrors(unexpectedConsoleErrors)}`
  ).toEqual([]);
}

async function waitForDashboardReady(page) {
  await expect(page.locator("main#main")).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(page.locator("header.header")).toBeVisible({ timeout: resolveTimeout(60_000) });
  await expect(page.locator("#navbar_logo img")).toBeVisible({ timeout: resolveTimeout(60_000) });
}

async function waitForResourceResponse(records, partialUrl, label) {
  await expect
    .poll(
      () =>
        records.some((record) => record.url.includes(partialUrl) && record.status >= 200 && record.status < 400),
      {
        timeout: resolveTimeout(60_000),
        message: `Expected ${label} to load successfully (${partialUrl})`,
      }
    )
    .toBe(true);
}

module.exports = {
  env: {
    dashboardJsBaseUrl,
    matomoBaseUrl,
  },
  isServiceEnabled,
  skipUnlessServiceEnabled,
  beforeEach,
  attachDiagnostics,
  expectNoUnexpectedDiagnostics,
  waitForDashboardReady,
  waitForResourceResponse,
};
