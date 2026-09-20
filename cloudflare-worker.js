const API_PREFIXES = ['/api/', '/healthz', '/readyz'];

function isApiRequest(pathname) {
  return API_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(prefix));
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (isApiRequest(url.pathname)) {
      if (!env.BACKEND_ORIGIN) {
        return new Response('Backend proxy is not configured', { status: 503 });
      }
      const target = new URL(url.pathname + url.search, env.BACKEND_ORIGIN);
      return fetch(new Request(target, request));
    }
    return env.ASSETS.fetch(request);
  },
};
