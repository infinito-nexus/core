const { test } = require("@playwright/test");
const { resolveTimeout, isOnionTarget } = require("./timeouts");
const { runSeaweedfsStorageCheck } = require("./personas");

exports.register = function (shared) {
  test("seaweedfs: an image uploaded to the OpenPost media library is stored in the SeaweedFS bucket", async ({ page, browser }) => {
    test.skip(isOnionTarget(), "SeaweedFS filer UI is not a Tor surface on an onion node (headless backend)");
    shared.skipUnlessServiceEnabled("seaweedfs");
    shared.skipUnlessServiceEnabled("sso");
    test.setTimeout(resolveTimeout(300_000)); // Filer UI admin login, OIDC login and the upload round-trip

    await runSeaweedfsStorageCheck(page, browser, {
      label: "an OpenPost media library upload",
      action: async (appPage) => {
        await shared.signInViaOidc(appPage, shared.env.adminUsername, shared.env.adminPassword, "administrator");
        await shared.uploadMedia(appPage, `infinito-storage-check-${Date.now()}.png`, "administrator");
        await shared.logout(appPage, "administrator");
      },
    });
  });
};
