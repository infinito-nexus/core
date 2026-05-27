/* logoutPatch.js */
(function(global) {

  /**
   * Initialize the logout patch script.
   * @param {string} logoutUrlBase - Base logout URL (e.g., from your OIDC client).
   * @param {string} webProtocol - Protocol to use (e.g., "https").
   * @param {string} primaryDomain - Primary domain (e.g., "example.com").
   * @param {boolean} debugMode - If true, debug logging is enabled.
   */
  function initLogoutPatch(logoutUrlBase, webProtocol, primaryDomain, debugMode) {
    const DEBUG = !!debugMode;

    function log(reason, el, extra) {
      if (!DEBUG) return;
      console.debug('[logoutPatch]', reason, extra || {}, el || null);
    }

    const redirectUri = encodeURIComponent(`${webProtocol}://${primaryDomain}`);
    const logoutUrl = `${logoutUrlBase}?redirect_uri=${redirectUri}`;

    function matchesLogout(str) {
      const matched = str && /(?:^|\W)log\s*out(?:\W|$)|logout/i.test(str);
      if (matched) log('matchesLogout', null, { value: str });
      return matched;
    }

    /**
     * Returns true if any attribute name or value on the given element
     * contains the substring "logout" (case-insensitive).
     *
     * @param {Element} element – The DOM element to inspect.
     * @returns {boolean} – True if "logout" appears in any relevant attribute name or value.
     */
    function containsLogoutAttribute(element) {
      for (const attribute of element.attributes) {
        const name = attribute.name || '';
        const value = attribute.value || '';

        // Strong indicator: attribute *name* contains "logout"
        if (/logout/i.test(name)) {
          log('containsLogoutAttribute (name match)', element, {
            attrName: name,
            attrValue: value
          });
          return true;
        }

        // Only consider values of semantic attributes (NOT href/action)
        if ((name.startsWith('data-') || name.startsWith('aria-')) && /logout/i.test(value)) {
          log('containsLogoutAttribute (data/aria value match)', element, {
            attrName: name,
            attrValue: value
          });
          return true;
        }
      }
      return false;
    }

    function matchesTechnicalIndicators(el) {
      const title = el.getAttribute('title');
      const ariaLabel = el.getAttribute('aria-label');
      const onclick = el.getAttribute('onclick');

      if (matchesLogout(title)) return true;
      if (matchesLogout(ariaLabel)) return true;
      if (matchesLogout(onclick)) return true;

      for (const attr of el.attributes) {
        if (attr.name.startsWith('data-') &&
            matchesLogout(attr.name + attr.value)) {
          log('matchesTechnicalIndicators (data-* match)', el, {
            attrName: attr.name,
            attrValue: attr.value
          });
          return true;
        }
      }

      if (typeof el.onclick === 'function' &&
          matchesLogout(el.onclick.toString())) {
        log('matchesTechnicalIndicators (onclick function match)', el);
        return true;
      }

      if (el.tagName.toLowerCase() === 'use') {
        const href = el.getAttribute('xlink:href') || el.getAttribute('href');
        if (matchesLogout(href)) {
          log('matchesTechnicalIndicators (<use> href match)', el, { href });
          return true;
        }
      }

      return false;
    }

    /**
     * Apply logout redirect behavior to a matching element:
     * – Installs a capturing click‐handler to force navigation to logoutUrl
     * – Always sets href/formaction/action to logoutUrl
     * – Marks the element as patched to avoid double‐binding
     *
     * @param {Element} el – The element to override (e.g. <a>, <button>, <form>, <input>)
     * @param {string} logoutUrl – The full logout URL including redirect params
     */
    function overrideLogout(el, logoutUrl) {
      // avoid patching the same element twice
      if (el.dataset._logoutHandled) {
        log('overrideLogout skipped (already handled)', el);
        return;
      }
      el.dataset._logoutHandled = "true";

      log('overrideLogout applied', el, { logoutUrl });

      // show pointer cursor
      el.style.cursor = 'pointer';

      // capture‐phase listener so it fires before any framework handlers
      el.addEventListener('click', function(e) {
        log('click intercepted, redirecting to logoutUrl', el);
        e.preventDefault();
        window.location.href = logoutUrl;
      }, { capture: true });

      const tag = el.tagName.toLowerCase();

      // always set the link target on <a>
      if (tag === 'a') {
        el.setAttribute('href', logoutUrl);
      }
      // always set the formaction on <button> or <input>
      else if ((tag === 'button' || tag === 'input') && el.hasAttribute('formaction')) {
        el.setAttribute('formaction', logoutUrl);
      }
      // always set the form action on <form>
      else if (tag === 'form') {
        el.setAttribute('action', logoutUrl);
      }
    }

    function scanAndPatch(elements) {
      elements.forEach(el => {
        const tagName = el.tagName.toLowerCase();
        const isPotential = ['a','button','input','use'].includes(tagName);
        if (!isPotential) return;

        // Prevent massive matches on huge containers
        let text = el.innerText;
        if (text && text.length > 1000) {
          text = ''; // ignore very large blocks
        }

        const match =
          matchesLogout(el.getAttribute('name')) ||
          matchesLogout(el.id) ||
          matchesLogout(el.className) ||
          matchesLogout(text) ||
          containsLogoutAttribute(el) ||
          matchesTechnicalIndicators(el);

        if (match) {
          log('scanAndPatch match', el, { tagName });
          overrideLogout(el, logoutUrl);
        }
      });
    }

    // Initial scan
    log('initial scan start');
    scanAndPatch(Array.from(document.querySelectorAll('*')));
    log('initial scan end');

    // Watch for dynamic content
    const observer = new MutationObserver(mutations => {
      mutations.forEach(mutation => {
        mutation.addedNodes.forEach(node => {
          if (!(node instanceof Element)) return;
          log('MutationObserver (new element)', node);
          scanAndPatch([node, ...node.querySelectorAll('*')]);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });

    log('MutationObserver attached');
  }

  // Expose to global scope
  global.initLogoutPatch = initLogoutPatch;
})(window);
