/* Adds the CSRF token to every same-origin state-changing fetch(). */
(() => {
  const token = () => document.querySelector('meta[name="csrf-token"]')?.content || '';
  const orig = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && url.origin === location.origin) {
      init = {...init, headers: {...Object.fromEntries(new Headers(init.headers || {})), 'X-CSRF-Token': token()}};
    }
    return orig(input, init);
  };
})();
