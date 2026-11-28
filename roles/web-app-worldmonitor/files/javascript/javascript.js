(function () {
  const API_PREFIX = "/api/";
  const nativeFetch = window.fetch;

  function omitsCredentials(input, init) {
    if (init && init.credentials !== undefined) return init.credentials === "omit";
    return input instanceof window.Request && input.credentials === "omit";
  }

  function resolved(input) {
    try {
      return new window.URL(input instanceof window.Request ? input.url : String(input), window.location.href);
    } catch {
      return null;
    }
  }

  function isOwnApi(input) {
    const url = resolved(input);
    return url !== null && url.origin === window.location.origin && url.pathname.indexOf(API_PREFIX) === 0;
  }

  window.fetch = function (input, init) {
    if (!omitsCredentials(input, init) || !isOwnApi(input)) return nativeFetch.call(window, input, init);
    return nativeFetch.call(window, input, { ...init, credentials: "same-origin" });
  };
})();
