/**
 * Minimal path-style S3 client for role specs: SigV4 signing plus
 * ListObjectsV2, on node:crypto alone.
 *
 * Contract:
 *   sign({method, host, path, region, accessKey, secretKey, query, payload})
 *     -> header object to merge into the request
 *   canonicalQuery(query)
 *     -> the query string the signature commits to; build the request URL
 *        from THIS, never from URLSearchParams, which emits "+" for a space
 *        where SigV4 requires "%20"
 *   listObjects(request, {baseUrl, bucket, region, accessKey, secretKey})
 *     -> Map<objectKey, versionToken> across every continuation page
 *
 * The signing algorithm is pinned by
 * tests/unit/python/roles/web-svc-seaweedfs/test_sigv4.py, which holds the
 * same vectors for the engine-side Python signer.
 */

const crypto = require("node:crypto");

const ALGORITHM = "AWS4-HMAC-SHA256";
const SERVICE = "s3";
const SIGNED_HEADERS = "host;x-amz-content-sha256;x-amz-date";
const PAGE_LIMIT = 1000;
const MAX_PAGES = 64;

function rfc3986(value) {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function canonicalQuery(query) {
  const entries = Object.entries(query || {});
  if (entries.length === 0) {
    return "";
  }
  return entries
    .map(([name, value]) => [rfc3986(name), rfc3986(String(value))])
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .map(([name, value]) => `${name}=${value}`)
    .join("&");
}

function hmac(key, message) {
  return crypto.createHmac("sha256", key).update(message, "utf8").digest();
}

function sign({ method, host, path, region, accessKey, secretKey, query, payload = "", now }) {
  const stamp = (now || new Date()).toISOString().replace(/[-:]|\.\d{3}/g, "");
  const amzDate = `${stamp.slice(0, 15)}Z`;
  const dateStamp = amzDate.slice(0, 8);
  const payloadHash = crypto.createHash("sha256").update(payload).digest("hex");

  const canonicalRequest = [
    method,
    path,
    canonicalQuery(query),
    `host:${host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${amzDate}\n`,
    SIGNED_HEADERS,
    payloadHash,
  ].join("\n");

  const scope = `${dateStamp}/${region}/${SERVICE}/aws4_request`;
  const toSign = [
    ALGORITHM,
    amzDate,
    scope,
    crypto.createHash("sha256").update(canonicalRequest, "utf8").digest("hex"),
  ].join("\n");

  let key = hmac(`AWS4${secretKey}`, dateStamp);
  key = hmac(key, region);
  key = hmac(key, SERVICE);
  key = hmac(key, "aws4_request");
  const signature = crypto.createHmac("sha256", key).update(toSign, "utf8").digest("hex");

  return {
    "x-amz-content-sha256": payloadHash,
    "x-amz-date": amzDate,
    Authorization:
      `${ALGORITHM} Credential=${accessKey}/${scope}, ` +
      `SignedHeaders=${SIGNED_HEADERS}, Signature=${signature}`,
  };
}

function parseListing(xml) {
  const objects = new Map();
  for (const block of xml.split("<Contents>").slice(1)) {
    const key = (block.match(/<Key>([\s\S]*?)<\/Key>/) || [])[1];
    if (!key) {
      continue;
    }
    const etag = (block.match(/<ETag>([\s\S]*?)<\/ETag>/) || [])[1] || "";
    const modified = (block.match(/<LastModified>([\s\S]*?)<\/LastModified>/) || [])[1] || "";
    objects.set(key, `${etag}|${modified}`);
  }
  const truncated = /<IsTruncated>\s*true\s*<\/IsTruncated>/i.test(xml);
  const token = (xml.match(/<NextContinuationToken>([\s\S]*?)<\/NextContinuationToken>/) || [])[1];
  return { objects, next: truncated ? token || "" : "" };
}

async function listObjects(request, { baseUrl, bucket, region, accessKey, secretKey }) {
  const url = new URL(baseUrl);
  const host = url.host;
  const path = `/${bucket}`;
  const all = new Map();
  let token = "";

  for (let page = 0; page < MAX_PAGES; page += 1) {
    const query = { "list-type": "2", "max-keys": String(PAGE_LIMIT) };
    if (token) {
      query["continuation-token"] = token;
    }
    const headers = sign({
      method: "GET",
      host,
      path,
      region,
      accessKey,
      secretKey,
      query,
    });
    const res = await request.get(`${url.origin}${path}?${canonicalQuery(query)}`, { headers });
    if (!res.ok()) {
      throw new Error(
        `S3 ListObjectsV2 on '${bucket}' answered ${res.status()} — ` +
          "the object store rejected the consumer identity or the bucket is absent",
      );
    }
    const { objects, next } = parseListing(await res.text());
    for (const [key, version] of objects) {
      all.set(key, version);
    }
    if (!next) {
      return all;
    }
    token = next;
  }
  throw new Error(`S3 ListObjectsV2 on '${bucket}' did not terminate within ${MAX_PAGES} pages`);
}

module.exports = { canonicalQuery, listObjects, parseListing, sign };
