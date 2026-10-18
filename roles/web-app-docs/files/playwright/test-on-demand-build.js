const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

exports.register = function (shared) {
  test("selecting an unbuilt version in the overview starts its build", async ({ page, request }) => {
    const target = (await shared.fetchVersions(request)).find(
      (version) => shared.RELEASE_TAG.test(version.name) && version.state === "missing",
    );
    expect(target, "Expected a release tag that is neither built nor requested yet").toBeTruthy();

    await gotoOnion(page, `${shared.appBaseUrl}/versions/`);
    const link = page.getByRole("link", { name: target.name, exact: true });
    await expect(link, `Expected ${target.name} in the overview`).toBeVisible({ timeout: resolveTimeout(30_000) });

    const [response] = await Promise.all([
      page.waitForResponse((candidate) => new URL(candidate.url()).pathname === `/${target.name}/`, {
        timeout: resolveTimeout(30_000),
      }),
      link.click(),
    ]);
    expect(response.status(), "Expected the build page for an unbuilt version").toBe(202);

    const build = page.locator(`section[data-build="${target.name}"]`);
    await expect(build, "Expected the build page of the selected version").toBeVisible({ timeout: resolveTimeout(30_000) });
    await expect(build.locator("progress"), "Expected a progress bar on the build page").toHaveCount(1);

    await expect
      .poll(() => shared.versionState(request, target.name), {
        message: `Expected selecting ${target.name} to queue or start its build`,
        timeout: resolveTimeout(60_000),
      })
      .toMatch(/^(queued|building|ready)$/);
  });
};
