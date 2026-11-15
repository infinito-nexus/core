(function () {
  const STORAGE_PREFIX = "vault-";
  const REVOKE_PATH = "/v1/auth/token/revoke-self";
  const LOGOUT_ROUTE = "/ui/vault/logout";
  const LOGOUT_CONTROL = "#logout, a[href$='/ui/vault/logout']";

  function browserStorages() {
    const storages = [];
    ["localStorage", "sessionStorage"].forEach(function (name) {
      try {
        if (window[name]) storages.push(window[name]);
      } catch {
        return;
      }
    });
    return storages;
  }

  function storedToken(raw) {
    try {
      const data = JSON.parse(raw);
      return data && typeof data.token === "string" ? data.token : null;
    } catch {
      return null;
    }
  }

  function revoke(token) {
    window
      .fetch(REVOKE_PATH, { method: "POST", headers: { "X-Vault-Token": token }, keepalive: true })
      .catch(function () {
        return null;
      });
  }

  function endSession() {
    browserStorages().forEach(function (storage) {
      const keys = [];
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (key && key.indexOf(STORAGE_PREFIX) === 0) keys.push(key);
      }
      keys.forEach(function (key) {
        const token = storedToken(storage.getItem(key));
        if (token) revoke(token);
        storage.removeItem(key);
      });
    });
  }

  if (window.location.pathname === LOGOUT_ROUTE) endSession();

  window.addEventListener(
    "click",
    function (event) {
      const target = event.target;
      if (target && typeof target.closest === "function" && target.closest(LOGOUT_CONTROL)) endSession();
    },
    true,
  );
})();
