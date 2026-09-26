const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const YAML_PAGE = "/latest/compose.html";
const FIRST_KEY = "x-ci-defaults";
const LATER_KEY = "dns_opt";

exports.register = function (shared) {
  test("a yaml source page shows the file as one highlighted block", async ({ page, request }) => {
    await expect
      .poll(() => shared.versionState(request, "latest"), {
        message: "Expected the latest site to finish building before its pages are asserted",
        timeout: resolveTimeout(300_000),
      })
      .toBe("ready");

    const response = await gotoOnion(page, `${shared.appBaseUrl}${YAML_PAGE}`);
    expect(response, `Expected a response for ${YAML_PAGE}`).toBeTruthy();
    expect(response.status(), `Expected ${YAML_PAGE} to be served`).toBe(200);

    await expect(
      page.getByRole("heading", { name: "compose.yml", exact: true }),
      "Expected the page to be titled after the file, which the yaml parser supplies",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const block = page.locator("div.highlight-yaml pre");
    await expect(block, "Expected the whole file in a single yaml-highlighted block").toHaveCount(1);

    const source = await block.innerText();
    expect(source, `Expected the top of the file in the block`).toContain(FIRST_KEY);
    expect(
      source,
      "Expected a key from deeper in the file in the same block; reading the file as " +
        "reStructuredText used to scatter it across block quotes instead",
    ).toContain(LATER_KEY);

    await expect(
      page.locator("blockquote"),
      "Expected no block quote: that is the shape reStructuredText made of yaml indentation",
    ).toHaveCount(0);
  });
};
