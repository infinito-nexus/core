const { test, expect } = require("./onion-test");

const { gotoOnion } = require("./personas");
const { resolveTimeout } = require("./timeouts");
const {
  RESULT,
  accountApplications,
  awaitDashboardReturn,
  chooseFromAccountMenu,
  expectDashboardSignedIn,
  expectDashboardSignedOut,
  expectLoginAsksForCredentials,
  expectSynapseSession,
  logOutThisDeviceFromAccountMenu,
  logoutEnv,
  openContext,
  signInToDashboard,
  signInToSynapse,
} = require("./logout-flow");

/**
 * Sign biber in on device A on every network and on device B on the canonical one.
 *
 * Args:
 *   browser: the Playwright browser.
 */
async function twoDevices(browser) {
  const a = await openContext(browser);
  const b = await openContext(browser);
  const pageA = await a.newPage();
  const pageB = await b.newPage();
  for (const url of logoutEnv.dashboardUrls) {
    await signInToDashboard(pageA, url);
  }
  await signInToDashboard(pageB, logoutEnv.dashboardUrls[0]);
  const synapseB = logoutEnv.synapseUrl ? await signInToSynapse(pageB) : "";
  await gotoOnion(pageA, logoutEnv.dashboardUrls[0]);
  return { a, b, pageA, pageB, synapseB };
}

exports.register = function () {
  test.describe("logout-device", () => {
    test.describe.configure({ mode: "serial" });

    test.beforeEach(() => {
      test.skip(
        logoutEnv.dashboardUrls.length === 0,
        "DASHBOARD_URLS_JSON is empty: both choices are offered through the dashboard with OIDC",
      );
    });

    test("logout-device: on this device ends every network of device A and keeps device B", async ({ browser }) => {
      test.setTimeout(resolveTimeout(900_000)); // four OIDC round trips over two networks plus a conductor sweep per network
      const devices = await twoDevices(browser);
      try {
        await logOutThisDeviceFromAccountMenu(devices.pageA);
        for (const url of logoutEnv.dashboardUrls) {
          await expectDashboardSignedOut(devices.pageA, url);
        }
        await expectDashboardSignedIn(devices.pageB, logoutEnv.dashboardUrls[0]);
        if (devices.synapseB) {
          await expectSynapseSession(devices.b.request, devices.synapseB, 200);
        }
        await logOutThisDeviceFromAccountMenu(devices.pageB);
        await expectDashboardSignedOut(devices.pageB, logoutEnv.dashboardUrls[0]);
      } finally {
        await devices.a.close();
        await devices.b.close();
      }
    });

    test("logout-device: everywhere ends every session of biber on every device", async ({ browser }) => {
      test.setTimeout(resolveTimeout(900_000)); // four OIDC round trips over two networks, the Account calls and a conductor sweep per network
      const devices = await twoDevices(browser);
      try {
        const dashboardOrigin = new URL(logoutEnv.dashboardUrls[0]).origin;
        const accountCall = (method, suffix) =>
          devices.pageA.waitForResponse(
            (response) => response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix),
            { timeout: resolveTimeout(120_000) },
          );
        const listed = accountCall("GET", "/account/applications");
        const ended = accountCall("DELETE", "/account/sessions");
        await chooseFromAccountMenu(devices.pageA, "everywhere");
        for (const [label, pending, status] of [
          ["the application list", listed, 200],
          ["ending every other session", ended, 204],
        ]) {
          const response = await pending;
          expect(response.status(), `${label} must succeed with the dashboard's own token`).toBe(status);
          expect(
            response.headers()["access-control-allow-origin"],
            `${label}: the dashboard client's allowed-origins claim must open CORS for the dashboard`,
          ).toBe(dashboardOrigin);
        }
        await awaitDashboardReturn(devices.pageA);
        await expect(devices.pageA.locator(RESULT), "device A names the everywhere outcome").toHaveAttribute("role", "status", {
          timeout: resolveTimeout(30_000),
        });
        for (const url of logoutEnv.dashboardUrls) {
          await expectDashboardSignedOut(devices.pageA, url);
        }
        await expectDashboardSignedOut(devices.pageB, logoutEnv.dashboardUrls[0]);
        await expectLoginAsksForCredentials(devices.pageB);
        if (devices.synapseB) {
          await expectSynapseSession(devices.b.request, devices.synapseB, 401);
        }
        const offline = (await accountApplications(devices.b.request)).filter((entry) => entry.offlineAccess === true);
        expect(offline, "no offline token of biber may still refresh").toEqual([]);
      } finally {
        await devices.a.close();
        await devices.b.close();
      }
    });

    test("logout-device: a failing Account call still logs this device out and says others may remain", async ({ browser }) => {
      test.setTimeout(resolveTimeout(600_000)); // two OIDC round trips over two networks plus a conductor sweep per network
      const a = await openContext(browser);
      try {
        await a.route("**/account/sessions", (route) =>
          route.request().method() === "DELETE" ? route.fulfill({ status: 500, body: "" }) : route.continue(),
        );
        const page = await a.newPage();
        for (const url of logoutEnv.dashboardUrls) {
          await signInToDashboard(page, url);
        }
        await gotoOnion(page, logoutEnv.dashboardUrls[0]);
        await chooseFromAccountMenu(page, "everywhere");
        await awaitDashboardReturn(page);
        await expect(page.locator(RESULT), "device A says other devices may still be signed in").toHaveAttribute("role", "alert", {
          timeout: resolveTimeout(30_000),
        });
        await expect(page.locator(RESULT)).not.toBeEmpty();
        for (const url of logoutEnv.dashboardUrls) {
          await expectDashboardSignedOut(page, url);
        }
      } finally {
        await a.close();
      }
    });
  });
};
