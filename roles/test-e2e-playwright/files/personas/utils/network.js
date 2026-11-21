const CLEARNET = "clearnet";
const TOR = "tor";
const URL_PATTERN = /\bhttps?:\/\/[^/,\s"']+/gi;

function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return "";
  }
}

/**
 * Returns:
 *   The network name -> host suffix table of the network registry, which the
 *   harness renders into PLAYWRIGHT_NETWORK_SUFFIXES.
 */
function registrySuffixes() {
  const raw = process.env.PLAYWRIGHT_NETWORK_SUFFIXES || "";
  if (!raw) {
    throw new Error(
      "PLAYWRIGHT_NETWORK_SUFFIXES is missing from the environment. The harness " +
        "writes it into the staged .env, so this run was started outside it."
    );
  }
  return JSON.parse(raw);
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
 *   host: a host name.
 *
 * Returns:
 *   Whether the registry puts the host into the tor network.
 */
function isTorHost(host) {
  return Boolean(host) && networkOf(host, registrySuffixes()) === TOR;
}

/**
 * Args:
 *   url: an absolute URL.
 *
 * Returns:
 *   Whether the host of the URL belongs to the tor network.
 */
function isTorUrl(url) {
  return isTorHost(hostOf(url));
}

/**
 * Args:
 *   values: strings that may carry absolute URLs, e.g. the environment values.
 *
 * Returns:
 *   The unique origins of the tor URLs in the values.
 */
function torOrigins(values) {
  const origins = new Set();
  for (const value of values) {
    if (typeof value !== "string") continue;
    for (const url of value.match(URL_PATTERN) || []) {
      if (isTorUrl(url)) origins.add(new URL(url).origin);
    }
  }
  return [...origins];
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

module.exports = {
  registrySuffixes,
  networkOf,
  isTorHost,
  isTorUrl,
  torOrigins,
  crossNetworkLeaks,
};
