const { test, expect } = require("./fixtures/onion-test");

const {
  gotoOnion,
  normalizeBaseUrl,
  requireDotenvValue,
} = require("./personas");

const cdnBaseUrl = normalizeBaseUrl(requireDotenvValue(process.env.CDN_BASE_URL, "CDN_BASE_URL"));
const sharedCssPrefix = `${cdnBaseUrl.replace(/\/$/, "")}/_shared/css`;

async function getComputedStyleProperty(locator, propertyName) {
  return locator.evaluate(
    (element, requestedProperty) => window.getComputedStyle(element).getPropertyValue(requestedProperty),
    propertyName
  );
}

async function expectDashboardCssEffects(page) {
  const card = page.locator(".card").first();

  if ((await card.count().catch(() => 0)) > 0) {
    const [actual, expected] = await card.evaluate((element) => {
      const probe = document.createElement("span");
      probe.style.backgroundColor = "var(--design-surface-2)";
      document.body.appendChild(probe);
      const token = window.getComputedStyle(probe).backgroundColor;
      probe.remove();
      return [window.getComputedStyle(element).backgroundColor, token];
    });
    expect(actual, "Expected dashboard cards to take the corporate surface token instead of the port-ui default").toBe(
      expected
    );
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
    shared.skipUnlessServiceEnabled("design");

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
    expect(
      await page.evaluate(
        () => document.head.querySelector('link[rel="stylesheet"], style')?.getAttribute("href") ?? "",
      ),
      "the shared cascade layer must be declared before every stylesheet of the app",
    ).toContain("/_shared/css/layer.css");
    await expectDashboardCssEffects(page);
  });
};
