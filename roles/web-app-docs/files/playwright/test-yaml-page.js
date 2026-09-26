const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const YAML_PAGE = "/deployed/compose.html";
const FIRST_KEY = "x-ci-defaults";
const LATER_KEY = "dns_opt";

exports.register = function (shared) {
  test("a yaml source page shows the file as one highlighted block", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(3_000_000)); // the English Sphinx build of the deployed working tree
    await expect
      .poll(async () => {
        try {
          const response = await request.get(`${shared.appBaseUrl}${YAML_PAGE}`, {
            failOnStatusCode: false,
            timeout: resolveTimeout(30_000),
          });
          return response.status();
        } catch {
          return 0; // the server refuses connections while it builds; a throw would end the poll
        }
      }, {
        message: "Expected the deployed YAML page to finish building before it is asserted",
        timeout: resolveTimeout(2_700_000),
        intervals: [30_000],
      })
      .toBe(200);

    const response = await gotoOnion(page, `${shared.appBaseUrl}${YAML_PAGE}`);
    expect(response, `Expected a response for ${YAML_PAGE}`).toBeTruthy();
    expect(response.status(), `Expected ${YAML_PAGE} to be served`).toBe(200);

    await expect(
      page.getByRole("heading", { name: /^compose\.yml/ }),
      "Expected the page to be titled after the file, which the yaml parser supplies. " +
        "The name is matched by prefix because docutils appends its permalink pilcrow as a " +
        "bare text node, which the theme hides through `.headerlink > *` and therefore never " +
        "hides at all, so the accessible name is `compose.yml¶`",
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
