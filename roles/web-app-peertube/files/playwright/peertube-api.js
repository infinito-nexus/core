const { expect } = require("@playwright/test");
const { resolveTimeout } = require("./timeouts");

async function rootAccessToken(request, baseUrl, username, password) {
  const client = await request.get(`${baseUrl}/api/v1/oauth-clients/local`, { timeout: resolveTimeout(30_000) });
  expect(client.ok(), `GET ${baseUrl}/api/v1/oauth-clients/local answered ${client.status()}`).toBe(true);
  const { client_id: clientId, client_secret: clientSecret } = await client.json();
  const token = await request.post(`${baseUrl}/api/v1/users/token`, {
    form: { client_id: clientId, client_secret: clientSecret, grant_type: "password", username, password },
    timeout: resolveTimeout(30_000),
  });
  expect(token.ok(), `root token request answered ${token.status()}`).toBe(true);
  return (await token.json()).access_token;
}

async function peertubeAccountOf(request, baseUrl, accessToken, username) {
  const response = await request.get(
    `${baseUrl}/api/v1/users?search=${encodeURIComponent(username)}&count=100`,
    { headers: { Authorization: `Bearer ${accessToken}` }, timeout: resolveTimeout(30_000) },
  );
  expect(response.ok(), `GET ${baseUrl}/api/v1/users answered ${response.status()}`).toBe(true);
  const { data } = await response.json();
  const account = (data || []).find((candidate) => candidate.username === username);
  expect(account, `PeerTube MUST hold an account named "${username}" after its OIDC login`).toBeTruthy();
  return account;
}

module.exports = { rootAccessToken, peertubeAccountOf };
