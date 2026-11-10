const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const PROJECT_ROOT = path.resolve(__dirname, "../../../../../../..");
const {
  CHOSEN_LABEL_PATTERN,
  PDS_HANDLE_LABEL_MAX,
  chosenLabelError,
  deriveLabel,
  fitsPds,
  prefixedLabel,
  suggestLabel,
} = require(path.join(PROJECT_ROOT, "roles/web-app-bluesky/files/login-broker/handle.js"));

test("a username becomes its label without any prefix", () => {
  assert.equal(deriveLabel("biber"), "biber");
  assert.equal(deriveLabel("Biber.Test"), "biber-test");
  assert.equal(deriveLabel(""), "user");
});

test("only a reserved name carries the i8- prefix", () => {
  assert.equal(prefixedLabel("administrator"), "i8-administrator");
  assert.ok(fitsPds(prefixedLabel("administrator")));
});

test("a label longer than the PDS limit needs a chosen handle", () => {
  assert.equal(deriveLabel("kevinveenbirkenbach").length, PDS_HANDLE_LABEL_MAX + 1);
  assert.equal(fitsPds(deriveLabel("kevinveenbirkenbach")), false);
  assert.equal(fitsPds("a".repeat(PDS_HANDLE_LABEL_MAX)), true);
  assert.equal(fitsPds("ab"), false);
});

test("a chosen handle must carry a hyphen and never i8-", () => {
  assert.equal(chosenLabelError("kevin-veen"), null);
  assert.match(chosenLabelError("kevinveen"), /hyphen/);
  assert.match(chosenLabelError("i8-kevin"), /i8-/);
  assert.match(chosenLabelError("kevin-i8-veen"), /i8-/);
  assert.match(chosenLabelError("-kevin"), /start or end/);
  assert.match(chosenLabelError("kevin-"), /start or end/);
  assert.match(chosenLabelError("Kevin-Veen"), /lowercase/);
  assert.match(chosenLabelError("kevin-veen-birkenbach"), /characters/);
});

test("the browser pattern accepts exactly what chosenLabelError accepts", () => {
  const browser = new RegExp(`^(?:${CHOSEN_LABEL_PATTERN})$`, "v");
  const samples = [
    "kevin-veen", "a-b", "a--b", "9-9", "kevin-v-birkenbach", "kevinveen", "i8-kevin", "kevin-i8-veen",
    "ki8-x", "-kevin", "kevin-", "-", "Kevin-Veen", "kevin_veen", "kevin.veen", "kevin veen",
  ];
  for (const sample of samples) {
    assert.equal(browser.test(sample), chosenLabelError(sample) === null, sample);
  }
});

test("the suggested handle passes the form and keeps the name readable", () => {
  assert.equal(suggestLabel("kevin.veen.birkenbach", "kvb"), "kevin-v-birkenbach");
  assert.equal(suggestLabel("kevinveenbirkenbach", "kevin.veen"), "kevin-veen");
  assert.equal(suggestLabel("christopherson-mcallisterfield", "x"), "christopherson-mca");
  assert.equal(suggestLabel("kevinveenbirkenbach", "kevin"), "");
  assert.equal(chosenLabelError(suggestLabel("maria.de.los.angeles.longname", "")), null);
});
