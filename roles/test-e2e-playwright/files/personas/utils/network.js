const CLEARNET = "clearnet";

function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}

/**
 * Args:
 *   host: a request or document host name.
 *   suffixes: network name -> host suffix, as the network registry declares it.
 *
 * Returns:
 *   The first network whose suffix the host carries, else "clearnet".
 */
function networkOf(host, suffixes) {
  const name = String(host || "").toLowerCase().replace(/\.$/, "");
  for (const [network, suffix] of Object.entries(suffixes || {})) {
    if (suffix && name.endsWith(suffix)) return network;
  }
  return CLEARNET;
}

/**
 * Args:
 *   requests: [{ url, documentUrl }] per request the page issued; documentUrl
 *     is the document the request was issued from.
 *   consoleErrors: the error texts the page logged to the console.
 *   suffixes: network name -> host suffix.
 *   allowedHosts: hosts every network may reach, i.e. the SSO issuer.
 *
 * Returns:
 *   One finding per request that leaves the network of its document and per
 *   mixed-content load the browser blocked.
 */
function crossNetworkLeaks({ requests, consoleErrors, suffixes, allowedHosts }) {
  const allowed = new Set((allowedHosts || []).map((host) => host.toLowerCase()));
  const findings = [];
  for (const { url, documentUrl } of requests || []) {
    const host = hostOf(url);
    const origin = hostOf(documentUrl);
    if (!host || !origin || allowed.has(host)) continue;
    const from = networkOf(origin, suffixes);
    const to = networkOf(host, suffixes);
    if (from !== to) findings.push(`${from} document ${documentUrl} requested ${to} ${url}`);
  }
  for (const text of consoleErrors || []) {
    if (/mixed content/i.test(text)) findings.push(`blocked mixed content: ${text}`);
  }
  return findings;
}

module.exports = { networkOf, crossNetworkLeaks };
