const { test, expect } = require("@playwright/test");

const { escapeRegex } = require("./personas");

async function waitForBoundingBoxStable(locator, { samples = 3, interval = 100, timeout = 10_000 } = {}) {
  const deadline = Date.now() + timeout;
  let previous = null;
  let stableCount = 0;

  while (Date.now() < deadline) {
    const current = await locator.boundingBox();

    if (
      current &&
      previous &&
      current.x === previous.x &&
      current.y === previous.y &&
      current.width === previous.width &&
      current.height === previous.height
    ) {
      stableCount += 1;
      if (stableCount >= samples) {
        return current;
      }
    } else {
      stableCount = 0;
    }

    previous = current;
    await new Promise((resolve) => setTimeout(resolve, interval));
  }

  return previous;
}

async function getComputedStyleProperty(locator, propertyName) {
  return locator.evaluate(
    (element, requestedProperty) => window.getComputedStyle(element).getPropertyValue(requestedProperty),
    propertyName
  );
}

async function expectStableCardHover(page, cardTitle) {
  const card = page
    .locator(".card")
    .filter({
      has: page.locator(".card-title", {
        hasText: new RegExp(`^${escapeRegex(cardTitle)}$`),
      }),
    })
    .first();

  await expect(card, `Expected the ${cardTitle} card to be visible`).toBeVisible({ timeout: 60_000 });

  const stretchedLink = card.locator("a.btn.stretched-link").first();
  await expect(stretchedLink, `Expected the ${cardTitle} card to expose a stretched-link button`).toBeVisible({
    timeout: 60_000,
  });

  await card.scrollIntoViewIfNeeded();
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => undefined);
  const settledBox = await waitForBoundingBoxStable(card);
  expect(settledBox, `Expected the ${cardTitle} card to expose a measurable bounding box`).toBeTruthy();

  const hoverPoints = [
    { x: 0.5, y: 0.2 },
    { x: 0.5, y: 0.5 },
    { x: 0.5, y: 0.8 },
  ];

  for (const point of hoverPoints) {
    await expect
      .poll(
        async () => {
          const freshBox = await card.boundingBox();
          if (!freshBox) {
            return false;
          }
          const x = Math.round(freshBox.x + freshBox.width * point.x);
          const y = Math.round(freshBox.y + freshBox.height * point.y);
          await page.mouse.move(x, y);
          return stretchedLink.evaluate((element) => element.matches(":hover"));
        },
        {
          timeout: 5_000,
          intervals: [100, 150, 250, 500],
          message: `Expected the ${cardTitle} stretched-link overlay to stay hovered at y=${point.y * 100}% of the card`,
        }
      )
      .toBe(true);
  }

  await stretchedLink.hover();
  const hoverFilter = await getComputedStyleProperty(stretchedLink, "filter");
  expect(hoverFilter.trim() || "none", `Expected the ${cardTitle} stretched-link hover filter to stay disabled`).toBe(
    "none"
  );
}

exports.register = function (shared) {
  test("dashboard renders simpleicon-backed cards when simpleicons service is enabled", async ({ page }) => {
    shared.skipUnlessServiceEnabled("simpleicons");

    await page.goto("/");
    await shared.waitForDashboardReady(page);

    const simpleiconCard = page
      .locator(".card")
      .filter({
        has: page.locator(".card-img-top svg, .card-img-top img[src^='http://'], .card-img-top img[src^='https://'], .card-img-top img[src^='/static/']"),
      })
      .first();

    await expect(
      simpleiconCard,
      "Expected at least one dashboard card to render a Simple Icons-backed SVG or cached image asset"
    ).toBeVisible({ timeout: 60_000 });
    await expect(
      simpleiconCard.locator(".card-img-top svg, .card-img-top img[src^='http://'], .card-img-top img[src^='https://'], .card-img-top img[src^='/static/']").first()
    ).toBeVisible({ timeout: 60_000 });
    await expectStableCardHover(page, "Keycloak");
  });
};
