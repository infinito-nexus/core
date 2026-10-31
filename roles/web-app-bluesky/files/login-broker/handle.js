"use strict";

const PDS_HANDLE_LABEL_MIN = 3;
const PDS_HANDLE_LABEL_MAX = 18;
const RESERVED_PREFIX = "i8-";

/**
 * First handle label derived from a Keycloak username.
 *
 * @param {string} username Keycloak username
 * @returns {string} lowercase label of [a-z0-9-], without prefix
 */
function deriveLabel(username) {
  const mapped = String(username || "")
    .toLowerCase()
    .slice(0, 256)
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "");
  return mapped || "user";
}

/**
 * Label for a name the PDS reserves ("admin", "administrator", ...).
 *
 * @param {string} label derived label
 * @returns {string} label carrying the reserved-name prefix
 */
function prefixedLabel(label) {
  return `${RESERVED_PREFIX}${label}`;
}

/**
 * @param {string} label first handle label
 * @returns {boolean} whether the PDS accepts its length
 */
function fitsPds(label) {
  return label.length >= PDS_HANDLE_LABEL_MIN && label.length <= PDS_HANDLE_LABEL_MAX;
}

/**
 * @param {string} label label the user typed
 * @returns {string|null} reason shown in the form, null when acceptable
 */
function chosenLabelError(label) {
  if (!/^[a-z0-9-]+$/.test(label)) return "Use lowercase letters, digits and hyphens only.";
  if (!fitsPds(label)) {
    return `Use ${PDS_HANDLE_LABEL_MIN} to ${PDS_HANDLE_LABEL_MAX} characters.`;
  }
  if (!label.includes("-")) return "Include at least one hyphen (-).";
  if (label.includes(RESERVED_PREFIX)) return `Do not use "${RESERVED_PREFIX}" anywhere in the handle.`;
  if (label.startsWith("-") || label.endsWith("-")) return "Do not start or end the handle with a hyphen.";
  return null;
}

module.exports = {
  PDS_HANDLE_LABEL_MAX,
  PDS_HANDLE_LABEL_MIN,
  RESERVED_PREFIX,
  chosenLabelError,
  deriveLabel,
  fitsPds,
  prefixedLabel,
};
