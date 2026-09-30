/**
 * Dotenv-quote decoders shared by every Playwright spec.
 *
 * `docker --env-file` preserves the surrounding double-quotes that the
 * project's `dotenv_quote` Jinja filter emits, so specs MUST decode
 * the quoted values before building URLs or typing credentials. The
 * `$$` -> `$` replacement undoes the dollar-sign escape that
 * `dotenv_quote` applies on the way out.
 *
 *   `decodeDotenvQuotedValue(raw)` returns the decoded string (or
 *   the input untouched when it is not a doubly-quoted dotenv value).
 *
 *   `normalizeBaseUrl(raw)` decodes AND strips a trailing slash so
 *   callers can append paths without `//` accidents.
 */

function decodeDotenvQuotedValue(value) {
  if (typeof value !== "string" || value.length < 2) {
    return value;
  }
  if (!(value.startsWith('"') && value.endsWith('"'))) {
    return value;
  }
  const encoded = value.slice(1, -1);
  try {
    return JSON.parse(`"${encoded}"`).replace(/\$\$/g, "$");
  } catch {
    return encoded.replace(/\$\$/g, "$");
  }
}

function normalizeBaseUrl(value) {
  return decodeDotenvQuotedValue(value || "").replace(/\/$/, "");
}

/**
 * Decode a dotenv value carrying a JSON array of target roles.
 *
 * `JSON.parse` on the quoted form succeeds and yields a STRING, which
 * `Array.isArray` then reads as "no targets" - every assertion over the list
 * passes vacuously. Only an absent or empty variable yields an empty list.
 */
function decodeDotenvJsonList(raw, name) {
  const decoded = decodeDotenvQuotedValue(raw || "");
  if (decoded === "") {
    return [];
  }
  let parsed;
  try {
    parsed = JSON.parse(decoded);
  } catch (error) {
    throw new Error(`${name} is not valid JSON`, { cause: error });
  }
  if (!Array.isArray(parsed)) {
    throw new Error(
      `${name} decoded to ${typeof parsed}, not an array — the value reached ` +
        "the container still dotenv-quoted, and reading it as an empty list " +
        "would pass every assertion that iterates it."
    );
  }
  return parsed;
}

module.exports = {
  decodeDotenvQuotedValue,
  decodeDotenvJsonList,
  normalizeBaseUrl,
};
