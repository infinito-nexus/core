# Caching in OpenResty and Cloudflare

## Overview

When deploying OpenResty as a reverse proxy, content may be cached at multiple layers:

- **Local Proxy Cache:** If you configure NGINX/OpenResty with a cache zone (using directives like `proxy_cache`), responses can be stored locally on disk and served to future clients.
- **Browser Cache:** Browsers cache responses based on HTTP headers like `Cache-Control` or `Expires`.
- **CDN Cache (Cloudflare):** If your domain is proxied through Cloudflare, Cloudflare may cache your content at their edge servers and serve it from there, often without requests reaching your origin server.

## Troubleshooting Cache Issues

Caching can cause problems, especially when you update your web content or configuration but still receive outdated responses. Typical symptoms include:

- Changes to HTML/CSS/JS are not visible immediately.
- Old redirects or headers persist even after config changes.
- Assets do not update after a deployment.

If this happens, always consider all caching layers:  

1. **Browser:** Clear the browser cache or use a private window.
2. **OpenResty:** If using a proxy cache, purge or clear the cache directory, or temporarily disable the cache zone.
3. **Cloudflare:** Purge the CDN cache as described below.

## Purging Cloudflare Cache

Cloudflare aggressively caches static content by default. Even after you deploy new files or update your proxy configuration, users may continue to see cached versions until the cache expires.

### Manual Purge via Cloudflare Dashboard

1. Log into your [Cloudflare dashboard](https://dash.cloudflare.com).
2. Select your domain.
3. Go to **Caching** → **Configuration**.
4. Click **Purge Cache**.
    - Choose **Purge Everything** to delete all cached files (recommended after a deployment).
    - Or use **Custom Purge** to specify individual URLs.

### Purge with Cloudflare API

You can also purge the cache programmatically with Cloudflare’s API:

```bash
curl -X POST "https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/purge_cache" \
     -H "Authorization: Bearer <YOUR_API_TOKEN>" \
     -H "Content-Type: application/json" \
     --data '{"purge_everything":true}'
````

- Replace `<ZONE_ID>` with your Cloudflare Zone ID.
- Replace `<YOUR_API_TOKEN>` with a valid API token with cache purge permissions.

To find your Zone ID, go to the overview page for your domain in the Cloudflare dashboard.
**Note:** It can take a few seconds for the cache to be purged globally.

## Recommendations

- Always purge the Cloudflare cache after significant changes to your website or OpenResty/NGINX configuration.
- If you use custom cache rules in OpenResty, consider providing cache-busting mechanisms (e.g., versioned URLs).
- Test changes in a private/incognito window to rule out browser cache.

## Further Reading

- [Cloudflare Purge Cache Documentation](https://developers.cloudflare.com/cache/how-to/purge-cache/)
