const { test, expect } = require("./fixtures/onion-test");

const { normalizeBaseUrl, gotoOnion } = require("./personas");

const cdnBaseUrl = normalizeBaseUrl(process.env.CDN_BASE_URL || "");
const sharedCssPrefix = `${cdnBaseUrl.replace(/\/$/, "")}/_shared/css`;

async function getComputedStyleProperty(locator, propertyName) {
  return locator.evaluate(
    (element, requestedProperty) => window.getComputedStyle(element).getPropertyValue(requestedProperty),
    propertyName
  );
}

async function expectDashboardCssEffects(page) {
  const styledCardIcon = page.locator(".card-img-top i").first();

  if ((await styledCardIcon.count().catch(() => 0)) > 0) {
    const iconFilter = await getComputedStyleProperty(styledCardIcon, "filter");
    expect(iconFilter, "Expected dashboard card icons to receive the role-local drop shadow style").not.toBe("none");
    return;
  }

  const navbarToggler = page.locator(".navbar-toggler").first();

  if ((await navbarToggler.count().catch(() => 0)) > 0) {
    const backgroundColor = await getComputedStyleProperty(navbarToggler, "background-color");
    expect(
      backgroundColor,
      "Expected the dashboard navbar toggler to receive the role-local background color override"
    ).not.toBe("rgba(0, 0, 0, 0)");
    return;
  }

  throw new Error("Expected a dashboard element that demonstrates the role-local CSS to be present");
}

exports.register = function (shared) {
  test("dashboard injects shared CSS assets when css service is enabled", async ({ page }) => {
    shared.skipUnlessServiceEnabled("css");

    const diagnostics = shared.attachDiagnostics(page);
    const documentResponse = await gotoOnion(page, "/");
    expect(documentResponse.status()).toBeLessThan(400);

    const documentHtml = await documentResponse.text();
    await shared.waitForDashboardReady(page);
    await shared.waitForResourceResponse(diagnostics.responses, "/_shared/css/default.css", "shared default CSS");
    await shared.waitForResourceResponse(diagnostics.responses, "/_shared/css/bootstrap.css", "shared bootstrap CSS");

    expect(documentHtml).toContain(sharedCssPrefix);
    expect(documentHtml).toContain(`${sharedCssPrefix}/default.css`);
    expect(documentHtml).toContain(`${sharedCssPrefix}/bootstrap.css`);
    await expectDashboardCssEffects(page);
  });
};
