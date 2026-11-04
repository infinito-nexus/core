const { test, expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");
const { gotoOnion } = require("./personas");

function decodeJwtPayload(token) {
  const segment = String(token || "").split(".")[1] || "";
  const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  return JSON.parse(Buffer.from(base64, "base64").toString("utf8"));
}

async function requestRoomToken(shared, page, roomName) {
  await gotoOnion(page, `${shared.env.appBaseUrl}/oidc/redirect?path=/${roomName}`, {
    waitUntil: "domcontentloaded",
  });
  await expect
    .poll(() => new URL(page.url()).searchParams.get("oidc"), {
      timeout: resolveTimeout(60_000),
      message: "the keycloak_adapter round trip must land back on the room with an oidc state",
    })
    .not.toBeNull();
  return new URL(page.url()).searchParams;
}

exports.register = function (shared) {
  test("rbac: the keycloak_adapter issues a moderator JWT to the administrator", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    shared.skipUnlessServiceEnabled("keycloak_adapter");
    test.setTimeout(resolveTimeout(180_000));
    const roomName = "e2e-admin-jwt-room";
    await shared.runAdminFlow(page, {
      adminInteraction: async (p) => {
        const params = await requestRoomToken(shared, p, roomName);
        expect(params.get("oidc"), "the administrator MUST be authorized by the keycloak_adapter").toBe("authorized");
        const payload = decodeJwtPayload(params.get("jwt"));
        expect(payload.room, "the JWT must be scoped to the requested room").toBe(roomName);
        expect(payload.context?.user?.moderator, "the administrator's JWT MUST mark a moderator").toBe(true);
      },
    });
  });

  test("rbac: the keycloak_adapter issues biber, without the administrator role, a named member JWT", async ({ page }) => {
    shared.skipUnlessServiceEnabled("sso");
    shared.skipUnlessServiceEnabled("keycloak_adapter");
    test.setTimeout(resolveTimeout(180_000));
    const roomName = "e2e-biber-jwt-room";
    await shared.runBiberFlow(page, {
      biberInteraction: async (p) => {
        const params = await requestRoomToken(shared, p, roomName);
        expect(params.get("oidc"), "biber MUST be authorized by the keycloak_adapter").toBe("authorized");
        const payload = decodeJwtPayload(params.get("jwt"));
        expect(payload.room, "the JWT must be scoped to the requested room").toBe(roomName);
        expect(payload.context?.user?.moderator, "biber's JWT MUST NOT mark a moderator").toBe(false);
        expect(payload.context?.user?.lobby_bypass, "biber MUST wait in the lobby").toBe(false);
        expect(payload.context?.user?.name, "biber's JWT MUST carry the Keycloak display name").toBeTruthy();
      },
    });
  });
};
