const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("versions api offers the latest commit first and every release tag after it", async ({ request }) => {
    const names = (await shared.fetchVersions(request)).map((version) => version.name);
    expect(names[0], "Expected the latest commit to be the default version").toBe("latest");
    expect(names.length, "Expected at least one release tag besides the latest commit").toBeGreaterThan(1);
    expect(
      names.slice(1).filter((name) => !shared.RELEASE_TAG.test(name)),
      "Expected only release tags after the latest commit",
    ).toEqual([]);
  });

  test("versions overview renders every version with a link and a progress bar", async ({ page, request }) => {
    const names = (await shared.fetchVersions(request)).map((version) => version.name);
    await gotoOnion(page, `${shared.appBaseUrl}/versions/`);
    const rows = page.locator("tbody[data-versions] tr");
    await expect(rows, "Expected one overview row per version").toHaveCount(names.length, {
      timeout: resolveTimeout(30_000),
    });
    await expect(rows.first().locator("a")).toHaveText("latest");
    await expect(rows.first().locator("a")).toHaveAttribute("href", "/latest/");
    await expect(page.locator("tbody[data-versions] progress")).toHaveCount(names.length);
  });
};
