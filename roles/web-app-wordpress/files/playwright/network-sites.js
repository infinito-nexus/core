/**
 * Args:
 *   networkBaseUrls: WORDPRESS_NETWORK_BASE_URLS, the sites separated by ";", each site's URLs by ",", canonical network first.
 * Returns:
 *   One URL list per network site, the canonical URL first, then its network siblings.
 */
function networkSiteUrls(networkBaseUrls) {
  if (!networkBaseUrls) {
    throw new Error("WORDPRESS_NETWORK_BASE_URLS must be set");
  }
  const sites = networkBaseUrls
    .split(";")
    .filter(Boolean)
    .map((siblings) =>
      siblings
        .split(",")
        .filter(Boolean)
        .map((url) => new URL(url))
    );
  if (sites.length === 0) {
    throw new Error("WORDPRESS_NETWORK_BASE_URLS lists no site of the network");
  }
  return sites;
}

/**
 * Args:
 *   networkBaseUrls: as networkSiteUrls takes it.
 * Returns:
 *   One host list per network site, the site domain first, then its network siblings.
 */
function networkSites(networkBaseUrls) {
  return networkSiteUrls(networkBaseUrls).map((urls) => urls.map((url) => url.hostname.toLowerCase()));
}

/**
 * Args:
 *   env: networkBaseUrls (WORDPRESS_NETWORK_BASE_URLS), rbacGroupMapJson (WORDPRESS_RBAC_GROUP_MAP)
 *     and canonicalDomain (CANONICAL_DOMAIN, the pass's network sibling of the main site).
 * Returns:
 *   primary: the domain of the network site whose hosts include CANONICAL_DOMAIN.
 *   children: the domains of the other network sites.
 */
function networkTenants(env) {
  const all = new Set(
    Object.values(JSON.parse(env.rbacGroupMapJson))
      .map((entry) => entry.tenant)
      .filter(Boolean)
  );
  const sites = networkSites(env.networkBaseUrls);
  const domains = sites.map(([domain]) => domain);
  const ungrouped = domains.filter((domain) => !all.has(domain));
  if (ungrouped.length > 0) {
    throw new Error(
      `WORDPRESS_RBAC_GROUP_MAP carries no per-site group for ${ungrouped.join(", ")}; tenants: ${[...all].join(", ")}`
    );
  }
  const canonical = env.canonicalDomain.toLowerCase();
  const primarySite = sites.find((hosts) => hosts.includes(canonical));
  if (!primarySite) {
    throw new Error(`CANONICAL_DOMAIN ${canonical} is no host of a network site; sites: ${domains.join(", ")}`);
  }
  const [primary] = primarySite;
  return { primary, children: domains.filter((domain) => domain !== primary) };
}

/**
 * Args:
 *   env: as networkTenants takes it.
 * Returns:
 *   The origin of the main site on the canonical network.
 */
function canonicalMainOrigin(env) {
  const { primary } = networkTenants(env);
  return networkSiteUrls(env.networkBaseUrls).find(([url]) => url.hostname.toLowerCase() === primary)[0].origin;
}

module.exports = { networkSites, networkTenants, canonicalMainOrigin };
