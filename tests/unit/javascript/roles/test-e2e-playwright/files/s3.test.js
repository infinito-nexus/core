const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const s3 = require(
  path.join(
    __dirname,
    "..", "..", "..", "..", "..", "..",
    "roles", "test-e2e-playwright", "files", "personas", "utils", "s3.js",
  ),
);

const ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE";
const SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY";
const REGION = "us-east-1";
const STAMP = new Date(Date.UTC(2013, 4, 24, 0, 0, 0));

const VECTORS = [
  {
    method: "GET",
    host: "seaweedfs:8333",
    path: "/",
    query: null,
    payload: "",
    signature: "741e224559611fe6adfe50315e98fec09bdb9a52da21c86b77ee676d98e00dd1",
  },
  {
    method: "GET",
    host: "seaweedfs:8333",
    path: "/matrix",
    query: { "list-type": "2", "max-keys": "1" },
    payload: "",
    signature: "eee845a1bf4fa9439b3e9a3fe61ab440e0560036caacb71cc871c079fd4ad7b5",
  },
  {
    method: "PUT",
    host: "seaweedfs:8333",
    path: "/infinito-engine-check-abc",
    query: null,
    payload: "",
    signature: "53e844ed6b237bdf9329204161e0c80a0f699c4032b4862f5ce4cb52ec737464",
  },
  {
    method: "DELETE",
    host: "127.0.0.1:8085",
    path: "/bucket/infinito-engine-check/xyz",
    query: null,
    payload: "",
    signature: "fb4f99e695b2c37135b9b2a92ebcb5436c6deabd9bd6e876cd6b5d4eae00b0b0",
  },
  {
    method: "GET",
    host: "host.example:8333",
    path: "/b/k",
    query: { a: "1", B: "2", c: "x y" },
    payload: "body",
    signature: "6cf8880d3c0baa47750aa5b0736a2b10459546b2f583643689200c01e067e8ec",
  },
];

function signatureOf(vector) {
  const headers = s3.sign({
    method: vector.method,
    host: vector.host,
    path: vector.path,
    region: REGION,
    accessKey: ACCESS_KEY,
    secretKey: SECRET_KEY,
    query: vector.query,
    payload: vector.payload,
    now: STAMP,
  });
  return headers.Authorization.split("Signature=")[1];
}

test("signatures match the reference implementation", () => {
  for (const vector of VECTORS) {
    assert.equal(signatureOf(vector), vector.signature, `${vector.method} ${vector.path}`);
  }
});

test("the node signer agrees with the python engine probe", () => {
  const fs = require("node:fs");
  const pinned = path.join(
    __dirname,
    "..", "..", "..", "..", "..", "..",
    "tests", "unit", "python", "roles", "web-svc-seaweedfs", "test_sigv4.py",
  );
  const python = fs.readFileSync(pinned, "utf8");
  for (const vector of VECTORS) {
    assert.ok(
      python.includes(vector.signature),
      `${vector.signature} must also be pinned in test_sigv4.py so the two signers cannot drift apart`,
    );
  }
});

test("a changed secret changes the signature", () => {
  const headers = s3.sign({
    method: "GET",
    host: "seaweedfs:8333",
    path: "/",
    region: REGION,
    accessKey: ACCESS_KEY,
    secretKey: `${SECRET_KEY}x`,
    payload: "",
    now: STAMP,
  });
  assert.ok(!headers.Authorization.includes(VECTORS[0].signature));
});

test("a space encodes as %20, not +", () => {
  assert.equal(s3.canonicalQuery({ c: "x y" }), "c=x%20y");
});

test("the secret never reaches the returned headers", () => {
  const headers = s3.sign({
    method: "GET",
    host: "seaweedfs:8333",
    path: "/",
    region: REGION,
    accessKey: ACCESS_KEY,
    secretKey: SECRET_KEY,
    payload: "",
    now: STAMP,
  });
  assert.ok(!Object.values(headers).join("").includes(SECRET_KEY));
});

test("a truncated listing reports its continuation token", () => {
  const xml = [
    "<ListBucketResult>",
    "<Contents><Key>a/1</Key><ETag>&quot;e1&quot;</ETag><LastModified>2026-01-01T00:00:00Z</LastModified></Contents>",
    "<Contents><Key>b/2</Key><ETag>&quot;e2&quot;</ETag><LastModified>2026-01-02T00:00:00Z</LastModified></Contents>",
    "<IsTruncated>true</IsTruncated>",
    "<NextContinuationToken>tok-42</NextContinuationToken>",
    "</ListBucketResult>",
  ].join("");
  const { objects, next } = s3.parseListing(xml);
  assert.deepEqual([...objects.keys()], ["a/1", "b/2"]);
  assert.notEqual(objects.get("a/1"), objects.get("b/2"));
  assert.equal(next, "tok-42");
});

test("a complete listing reports no continuation", () => {
  const xml =
    "<ListBucketResult><Contents><Key>only</Key></Contents><IsTruncated>false</IsTruncated></ListBucketResult>";
  const { objects, next } = s3.parseListing(xml);
  assert.deepEqual([...objects.keys()], ["only"]);
  assert.equal(next, "");
});

test("an empty listing yields no objects", () => {
  const { objects, next } = s3.parseListing(
    "<ListBucketResult><IsTruncated>false</IsTruncated></ListBucketResult>",
  );
  assert.equal(objects.size, 0);
  assert.equal(next, "");
});
