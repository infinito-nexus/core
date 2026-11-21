/**
 * Rewrite the adapter so its redirect_uri carries the scheme the front proxy forwarded.
 *
 * Args:
 *   Deno.args[0]: path of the upstream adapter.ts, rewritten in place.
 *
 * Exits 1 when a replaced line is missing or not unique.
 */
// The `?? "https"` fallback is the upstream adapter's own hard-coded scheme, kept for a request without the proxy header.
const SCHEME = 'req.headers.get("x-forwarded-proto") ?? "https"';

const REPLACEMENTS: Array<[string, string]> = [
  [
    "const token = await getToken(host, code, path, search, hash);",
    "const token = await getToken(`${" + SCHEME + "}://${host}`, code, path, search, hash);",
  ],
  [
    "const redirectURI = `https://${host}/static/oidc-adapter.html` +",
    "const redirectURI = `${host}/static/oidc-adapter.html` +",
  ],
  [
    "`&prompt=${prompt}&redirect_uri=https://${host}/static/oidc-adapter.html` +",
    "`&prompt=${prompt}&redirect_uri=${" + SCHEME + "}://${host}/static/oidc-adapter.html` +",
  ],
];

const path = Deno.args[0];
let source = await Deno.readTextFile(path);
for (const [from, to] of REPLACEMENTS) {
  if (source.split(from).length !== 2) {
    console.error(`expected exactly one occurrence of: ${from}`);
    Deno.exit(1);
  }
  source = source.replace(from, () => to);
}
await Deno.writeTextFile(path, source);
