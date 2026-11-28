const { test } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { runProxmoxAdminFlow } = require("./proxmox-flow");

test.use({ ignoreHTTPSErrors: true });

test("administrator: oauth2 gate → OpenID realm → Administrator on / → universal logout", async ({ page }) => {
  test.setTimeout(resolveTimeout(420_000)); // two Keycloak round trips plus the Ext JS workspace boot
  await runProxmoxAdminFlow(page);
});
