const { test, expect } = require("@playwright/test");
const { skipUnlessAddonEnabled } = require("../addon-gating");
const shared = require("../_shared");

test("addon activitypub: WordPress is a discoverable Fediverse actor (WebFinger -> ActivityStreams actor)", async ({ browser }) => {
  skipUnlessAddonEnabled("activitypub");
  test.setTimeout(120_000);

  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  try {
    await shared.wpAdminLoginViaOidc(
      page,
      shared.env.wpBaseUrl,
      shared.env.adminUsername,
      shared.env.adminPassword
    );

    await page.goto(`${shared.env.wpBaseUrl}/wp-admin/profile.php`, {
      waitUntil: "domcontentloaded",
      timeout: 60_000,
    });
    const loginField = page.locator("#user_login");
    await expect(
      loginField,
      "the WP admin profile must expose the user_login used to mint the ActivityPub author handle"
    ).toBeVisible({ timeout: 30_000 });
    const wpUserLogin = (await loginField.inputValue()).trim();
    expect(wpUserLogin, "WP user_login must be resolvable").toBeTruthy();

    const wpHost = new URL(shared.env.wpBaseUrl).host;
    const resource = `acct:${wpUserLogin}@${wpHost}`;

    const request = context.request;
    const webfingerUrl = new URL("/.well-known/webfinger", shared.env.wpBaseUrl);
    webfingerUrl.searchParams.set("resource", resource);

    const webfingerResp = await request.get(webfingerUrl.toString(), {
      headers: { Accept: "application/jrd+json, application/json" },
    });
    expect(
      webfingerResp.status(),
      `WebFinger for ${resource} must resolve (HTTP 200) — a 404 means the ActivityPub federation discovery endpoint is absent and the addon never landed`
    ).toBe(200);

    const webfingerCt = (webfingerResp.headers()["content-type"] || "").toLowerCase();
    expect(
      webfingerCt,
      "WebFinger must answer with a JRD/JSON document, not an HTML error page"
    ).toMatch(/json/);

    const jrd = await webfingerResp.json();
    expect(
      jrd.subject,
      "the WebFinger JRD subject must echo the queried acct: resource (proves the actor is the one we asked for)"
    ).toBe(resource);

    const links = Array.isArray(jrd.links) ? jrd.links : [];
    const selfLink = links.find(
      (l) =>
        l &&
        l.rel === "self" &&
        typeof l.type === "string" &&
        /application\/activity\+json|application\/ld\+json/i.test(l.type)
    );
    expect(
      selfLink && selfLink.href,
      "the WebFinger JRD must carry a rel=self link of type application/activity+json — this is the actor id remote partners dereference to federate"
    ).toBeTruthy();

    const actorUrl = new URL(selfLink.href);
    expect(
      actorUrl.host,
      "the discovered ActivityPub actor must be served by this WordPress host (the Fediverse identity belongs to this install)"
    ).toBe(wpHost);

    const actorResp = await request.get(actorUrl.toString(), {
      headers: { Accept: "application/activity+json" },
    });
    expect(
      actorResp.status(),
      "the ActivityPub actor object must be fetchable (HTTP 200) the way a remote Fediverse server would dereference it"
    ).toBe(200);

    const actorCt = (actorResp.headers()["content-type"] || "").toLowerCase();
    expect(
      actorCt,
      "the actor must be served as ActivityStreams JSON (application/activity+json or ld+json), not HTML — otherwise no partner can federate with it"
    ).toMatch(/activity\+json|ld\+json/);

    const actor = await actorResp.json();

    const contextValues = []
      .concat(actor["@context"] || [])
      .map((c) => (typeof c === "string" ? c : (c && c["@vocab"]) || ""));
    expect(
      contextValues.some((c) => /^https?:\/\/www\.w3\.org\/ns\/activitystreams$/i.test(c)),
      "the actor JSON-LD must declare the ActivityStreams @context (proves it is a real federation object)"
    ).toBeTruthy();

    expect(
      typeof actor.type === "string" &&
        /^(Person|Service|Application|Group|Organization)$/.test(actor.type),
      `the actor must declare a Fediverse actor type, got "${actor.type}"`
    ).toBeTruthy();

    expect(
      actor.id,
      "the actor must publish a canonical id remote partners address it by"
    ).toBeTruthy();

    expect(
      typeof actor.inbox === "string" && /^https?:\/\//i.test(actor.inbox),
      "the actor must expose an inbox URL — the endpoint a remote server POSTs activities to. Without it nothing can federate in"
    ).toBeTruthy();
    expect(
      new URL(actor.inbox).host,
      "the federation inbox must live on this WordPress host"
    ).toBe(wpHost);

    expect(
      typeof actor.outbox === "string" && /^https?:\/\//i.test(actor.outbox),
      "the actor must expose an outbox URL — the endpoint partners pull this actor's published activities from"
    ).toBeTruthy();

    expect(
      typeof actor.publicKey === "object" &&
        actor.publicKey &&
        typeof actor.publicKey.publicKeyPem === "string" &&
        /BEGIN PUBLIC KEY/.test(actor.publicKey.publicKeyPem),
      "the actor must publish an RSA publicKey — HTTP-Signature verification of this key is how partners authenticate federated deliveries"
    ).toBeTruthy();
  } finally {
    await page.close().catch(() => {});
    await context.close().catch(() => {});
  }
});
