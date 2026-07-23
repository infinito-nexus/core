const { test, expect } = require("@playwright/test");

exports.register = function (shared) {
  test.describe("matrix DM", () => {
    // rc_login exhaustion used to be the dominant failure mode here (retries
    // burned through Synapse's default burst of 3), which is why this block
    // previously set retries=0. The 120s drain wait before admin's signin
    // below made that obsolete. The dominant failure mode is now transient
    // CI infra pressure — browser processes getting OOM-killed under the
    // combined load of Synapse + Element + bridges + Keycloak + Mailu +
    // Matomo on a standard runner surfaces as "Target page, context or
    // browser has been closed" mid-navigation. Allow a single retry so those
    // transient crashes don't fail the suite. Cap at 1 (not the config-wide
    // 2) so a genuinely broken test can't burn 3× the DM budget (~9m).
    test.describe.configure({ retries: 1 });

    test("administrator and biber can exchange a direct message in element", async ({ browser }) => {
      shared.skipUnlessServiceEnabled("sso");
      const {
        adminUsername,
        adminPassword,
        biberUsername,
        biberPassword,
        elementBaseUrl,
        matrixServerName,
      } = shared.env;
      const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const biberContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const adminPage = await adminContext.newPage();
      const biberPage = await biberContext.newPage();

      await shared.installCspViolationObserver(adminPage);
      await shared.installCspViolationObserver(biberPage);

      // When the spec runs in full (CSP + two per-user OIDC tests + DM), the
      // prior admin/biber logins have already consumed Synapse's rc_login
      // burst (default: 3 slots, drain 0.17/s ≈ 6s per slot). The per-user
      // OIDC tests themselves can take minutes and trigger retries that
      // consume additional slots. Waiting ~120s before DM's admin sign-in
      // lets the burst and any pending retries fully drain, so the DM
      // test's state machine isn't forced to spend most of its deadline
      // cycling through consent↔M_LIMIT_EXCEEDED retries. Running the DM
      // test in isolation doesn't need this, but the extra wait is cheap.
      await adminPage.waitForTimeout(120_000);
      await shared.signInViaElement(adminPage, adminUsername, adminPassword, "administrator");
      // Same reasoning between admin and biber: two back-to-back SSO
      // logins easily exhaust rc_login. 30s lets the burst refill.
      await adminPage.waitForTimeout(30_000);
      await shared.signInViaElement(biberPage, biberUsername, biberPassword, "biber");

      const marker = `hello-from-admin-${Date.now()}`;
      // MXIDs use the Synapse server_name (a.k.a. MATRIX_SERVER_NAME, typically
      // the bare DOMAIN_PRIMARY), not the client-facing URL host. Using the URL
      // host (e.g. "matrix.infinito.test") yields a non-existent user and
      // Synapse returns HTTP 502 on profile lookup.
      const biberMatrixId = `@${biberUsername}:${matrixServerName}`;

      // Admin opens a DM to biber via URL API (#/user/@biber:...). This renders
      // biber's profile in a right-hand `aside` panel alongside the home
      // welcome screen — not a full-screen user view — so the "Send message"
      // button we need lives inside the profile panel specifically (there is a
      // separate "Send a Direct Message" button on the welcome screen that
      // opens a search dialog rather than directly messaging biber).
      await adminPage.goto(`${elementBaseUrl}/#/user/${encodeURIComponent(biberMatrixId)}`);

      const profilePanel = adminPage.getByRole("complementary").filter({ hasText: biberMatrixId });
      await expect(profilePanel, "admin: biber profile panel must render").toBeVisible({ timeout: 60_000 });

      const profileSendMessageButton = profilePanel
        .getByRole("button", { name: /^send message$/i })
        .first();
      await expect(profileSendMessageButton, "admin: profile 'Send message' button must be visible").toBeVisible({ timeout: 30_000 });
      await profileSendMessageButton.click();

      // After clicking "Send message", Element navigates into the DM room and
      // renders a message composer. Wait for the room header to show biber's
      // name before looking for the composer, so we don't match a stale
      // textbox from the previous view (e.g. a search field).
      const roomHeader = adminPage.getByRole("heading", { name: /harry beaver|biber/i }).first();
      await expect(roomHeader, "admin: DM room header with biber must render").toBeVisible({ timeout: 30_000 });

      const composer = adminPage
        .locator("div[role='textbox'][contenteditable='true'], textarea[aria-label*='message' i], div[aria-label*='message' i][contenteditable='true']")
        .last();
      await expect(composer, "admin: message composer must appear").toBeVisible({ timeout: 60_000 });
      await composer.click();

      // Element keeps the DM in a pending "Send your first message to invite …"
      // state when entered via a profile's "Send message" button: the room
      // (and therefore the invite to biber) is only created on the server once
      // admin actually sends. Without this bootstrap send, biber's side never
      // receives an invite tile and the accept-invite poll below times out.
      //
      // The bootstrap text is intentionally distinct from `marker`. With E2EE
      // enabled and biber not yet joined, this first ciphertext will land on
      // biber's side as "Unable to decrypt message" (no pre-join megolm key
      // share). That's acceptable — biber's assertion targets `marker`, which
      // admin sends AFTER biber has joined so Element establishes a fresh
      // outbound megolm session that includes biber's device.
      const bootstrap = `bootstrap-${Date.now()}`;
      await adminPage.keyboard.type(bootstrap);
      await adminPage.keyboard.press("Enter");

      // Biber: wait for admin's invite to propagate, then accept. The flow
      // mirrors Element's invite UX: (1) click the sidebar tile for admin's
      // invite (the tile renders with admin's display name but no standalone
      // Accept button), then (2) click the primary accept action in the invite
      // view (modern Element labels this "Start chatting" for DMs; older
      // builds / non-DM invites use "Accept" / "Join"). MUST NOT match
      // "Decline" / "Decline and block".
      await expect
        .poll(async () => {
          return await biberPage.evaluate(() => {
            // Step 1: open the invite.
            const roomTiles = document.querySelectorAll(
              "[role='treeitem'], [role='option'], .mx_RoomTile, [data-testid^='room-tile']",
            );
            for (const tile of roomTiles) {
              const text = (tile.textContent || "").trim();
              if (/administrator/i.test(text)) {
                tile.click();
                break;
              }
            }
            // Step 2: click accept.
            const acceptCandidates = document.querySelectorAll(
              "button, a, [role='button']",
            );
            for (const b of acceptCandidates) {
              const text = (b.textContent || "").trim();
              if (/^(start chatting|accept|accept invite|join|annehmen|akzeptieren)$/i.test(text)) {
                b.click();
              }
            }
            // Success: invite accepted when the room timeline renders a
            // message composer for biber (only appears once membership is
            // `join`). Use the same composer signature as admin's side.
            return !!document.querySelector(
              "div[role='textbox'][contenteditable='true'], textarea[aria-label*='message' i]",
            );
          }).catch(() => false);
        }, {
          timeout: 120_000,
          message: "biber: expected invite acceptance to produce a message composer",
        })
        .toBe(true);

      // Give admin's client a moment to observe biber's join and establish a
      // megolm session before sending the marker. Element batches outbound
      // session creation on membership events; 5s is generous.
      await adminPage.waitForTimeout(5_000);
      await composer.click();
      await adminPage.keyboard.type(marker);
      await adminPage.keyboard.press("Enter");

      // Biber should now receive the marker as a live (not historical)
      // message and decrypt it via the just-shared megolm session.
      await expect
        .poll(async () => {
          return (await biberPage.locator("body").innerText().catch(() => "")).includes(marker);
        }, {
          timeout: 120_000,
          message: `biber: expected to receive message "${marker}" from administrator`,
        })
        .toBe(true);

      await adminContext.close();
      await biberContext.close();
    });
  });
};
