const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

const LICENSING_PAGE = "/deployed/generated/licensing.html";
const RIGHT_COLUMNS = [
  "Commercial use",
  "Modifications",
  "Distribution",
  "Private use",
  "Patent use",
  "Self host",
  "Include copyright",
  "Document changes",
  "Disclose source",
  "Network use disclose",
  "Same license",
  "Liability",
  "Warranty",
  "Trademark use",
];

exports.register = function (shared) {
  test("the licence page carries a rights matrix for every role", async ({ page, request }) => {
    test.setTimeout(resolveTimeout(5_400_000)); // the English Sphinx build of the deployed working tree
    await shared.pollStatus(
      request,
      `${shared.appBaseUrl}${LICENSING_PAGE}`,
      200,
      "Expected the deployed licence page to finish building before it is asserted",
      5_300_000,
    );

    const response = await gotoOnion(page, `${shared.appBaseUrl}${LICENSING_PAGE}`);
    expect(response, `Expected a response for ${LICENSING_PAGE}`).toBeTruthy();
    expect(response.status(), `Expected ${LICENSING_PAGE} to be served`).toBe(200);

    await expect(
      page.getByRole("heading", { name: /^Licence contexts/ }),
      "Expected the generated page title; matched by prefix because docutils appends " +
        "its permalink pilcrow as a bare text node",
    ).toBeVisible({ timeout: resolveTimeout(30_000) });

    const tables = page.locator("table");
    const tableCount = await tables.count();
    expect(tableCount, "Expected one matrix per licence context").toBeGreaterThan(1);

    const headers = tables.first().locator("thead th");
    await expect(
      headers,
      `Expected Role, Licence and one column per right (${RIGHT_COLUMNS.length})`,
    ).toHaveCount(RIGHT_COLUMNS.length + 2);
    for (const [index, label] of RIGHT_COLUMNS.entries()) {
      await expect(headers.nth(index + 2)).toHaveText(label);
    }

    await expect(
      page.getByRole("heading", { name: /^Network copyleft/ }),
      "Expected the network-copyleft section: the catalogue holds AGPL roles, and the " +
        "heading is derived from their rights rather than declared, so its absence means " +
        "the derivation stopped working",
    ).toBeVisible();

    await expect(
      page.getByRole("heading", { name: /^Not yet determined/ }),
      "Expected no undetermined section: every invokable role resolves to a licence, and " +
        "tests/lint/ansible/roles/meta/test_license_declared.py refuses a commit that " +
        "breaks that",
    ).toHaveCount(0);

    // The role cell is an inline literal, which docutils and Sphinx wrap in
    // different elements, so the row is found by its text, not by a tag.
    const nextcloud = page.locator("tr", { hasText: "web-app-nextcloud" });
    await expect(
      nextcloud,
      "Expected one row for web-app-nextcloud, which anchors the page to the declared data",
    ).toHaveCount(1);
    await expect(
      nextcloud.locator("a", { hasText: "AGPL-3.0-or-later" }),
      "Expected Nextcloud's licence to be the one its own SPDX headers state, linked to " +
        "the url meta/license.yml records",
    ).toHaveCount(1);
    await expect(
      nextcloud.locator("td").nth(RIGHT_COLUMNS.indexOf("Network use disclose") + 1),
      "Expected the AGPL network clause to reach the matrix cell",
    ).toHaveText("yes");
  });
};
