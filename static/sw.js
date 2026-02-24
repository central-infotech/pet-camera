/**
 * Pet Camera — Service Worker
 *
 * Caches the app shell (HTML, CSS, JS, icons) for fast loading.
 * Streaming data (MJPEG, WebSocket) is NOT cached.
 */

const CACHE_NAME = "petcam-v12";
const APP_SHELL = [
  "/",
  "/static/css/style.css",
  "/static/js/webrtc.js",
  "/static/js/app.js",
  "/static/js/audio.js",
  "/static/js/display.js",
  "/static/img/icon-192.png",
  "/static/img/favicon.png",
  "/static/manifest.json",
];

// Install: pre-cache app shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch: network-first for navigation & API, cache-first for static assets
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // Skip non-GET, streaming, WebSocket, and API requests
  if (
    event.request.method !== "GET" ||
    url.pathname.startsWith("/video_feed") ||
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/socket.io/")
  ) {
    return;
  }

  // Navigation requests (HTML pages): network-first
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Static assets: cache-first, fallback to network
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ||
          fetch(event.request).then((response) => {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
            return response;
          })
      )
    );
    return;
  }
});
