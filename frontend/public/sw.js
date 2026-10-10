// Minimal offline support for the citizen page: app shell cache-first, citizen API network-first
// with the last good answer as fallback (weak networks).
const SHELL = 'heatrelief-shell-v1';
const API = 'heatrelief-api-v1';

self.addEventListener('install', (e) => { self.skipWaiting(); e.waitUntil(caches.open(SHELL).then((c) => c.addAll(['/', '/favicon.svg']))); });
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.pathname.startsWith('/api/v1/citizen') || (url.pathname.startsWith('/api/v1/') && url.origin !== location.origin)) {
    if (!url.pathname.includes('/citizen') && !url.pathname.includes('/cities')) return;
    e.respondWith(fetch(req).then((res) => { const copy = res.clone(); caches.open(API).then((c) => c.put(req, copy)); return res; })
      .catch(() => caches.match(req)));
    return;
  }
  if (url.origin === location.origin) {
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(SHELL).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match('/'))));
  }
});
