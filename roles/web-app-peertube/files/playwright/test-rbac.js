const { test, expect } = require("@playwright/test");
const { skipUnlessServiceEnabled } = require("./service-gating");
const { rootAccessToken, peertubeAccountOf } = require("./peertube-api");

const PEERTUBE_ROLE_ADMINISTRATOR = 0;
const PEERTUBE_ROLE_USER = 2;

exports.register = function (shared) {
  const scenarios = [
    {
      title: "administrator: OIDC account holds the PeerTube Administrator role",
      persona: "administrator",
      username: () => shared.env.adminUsername,
      password: () => shared.env.adminPassword,
      expectedRole: PEERTUBE_ROLE_ADMINISTRATOR,
    },
    {
      title: "biber: OIDC account without a role group holds the PeerTube User role",
      persona: "biber",
      username: () => shared.env.biberUsername,
      password: () => shared.env.biberPassword,
      expectedRole: PEERTUBE_ROLE_USER,
    },
  ];

  for (const scenario of scenarios) {
    test(scenario.title, async ({ page, request }) => {
      skipUnlessServiceEnabled("sso");
      await shared.signIn(page, scenario.username(), scenario.password(), scenario.persona);
      await shared.logout(page);

      const accessToken = await rootAccessToken(
        request,
        shared.env.peertubeBaseUrl,
        shared.env.rootUsername,
        shared.env.rootPassword,
      );
      const account = await peertubeAccountOf(request, shared.env.peertubeBaseUrl, accessToken, scenario.username());
      expect(
        account.role.id,
        `${scenario.persona} MUST hold PeerTube role ${scenario.expectedRole} as the deploy converged it from the role groups`,
      ).toBe(scenario.expectedRole);
    });
  }
};
