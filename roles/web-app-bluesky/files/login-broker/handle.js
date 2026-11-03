"use strict";

const { t } = require("./messages");

const PDS_HANDLE_LABEL_MIN = 3;
const PDS_HANDLE_LABEL_MAX = 18;
const RESERVED_PREFIX = "i8-";
const CHOSEN_LABEL_PATTERN = `(?!.*${RESERVED_PREFIX})[a-z0-9][a-z0-9\\-]*-[a-z0-9\\-]*[a-z0-9]`;

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
  if (!/^[a-z0-9-]+$/.test(label)) return t("label_charset");
  if (!fitsPds(label)) return t("label_length", { min: PDS_HANDLE_LABEL_MIN, max: PDS_HANDLE_LABEL_MAX });
  if (!label.includes("-")) return t("label_hyphen");
  if (label.includes(RESERVED_PREFIX)) return t("label_prefix", { prefix: RESERVED_PREFIX });
  if (label.startsWith("-") || label.endsWith("-")) return t("label_edge");
  return null;
}

/**
 * First name that yields an acceptable label, middle words cut to their initial.
 *
 * @param {...string} names candidates in order, e.g. the username and the e-mail local part
 * @returns {string} label chosenLabelError accepts, empty when no candidate yields one
 */
function suggestLabel(...names) {
  for (const name of names) {
    const parts = deriveLabel(name).split("-").filter(Boolean);
    for (let i = 1; i < parts.length - 1 && parts.join("-").length > PDS_HANDLE_LABEL_MAX; i++) {
      parts[i] = parts[i][0];
    }
    const label = parts.join("-").slice(0, PDS_HANDLE_LABEL_MAX).replace(/-+$/, "");
    if (chosenLabelError(label) === null) return label;
  }
  return "";
}

module.exports = {
  CHOSEN_LABEL_PATTERN,
  PDS_HANDLE_LABEL_MAX,
  PDS_HANDLE_LABEL_MIN,
  RESERVED_PREFIX,
  chosenLabelError,
  deriveLabel,
  fitsPds,
  prefixedLabel,
  suggestLabel,
};
