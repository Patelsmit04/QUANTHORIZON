/* ==========================================================================
   TRADEXO PWA SERVICE WORKER (Phase 4 — Lock-Screen Web Push Notifications)
   ========================================================================== */

const CACHE_NAME = 'tradexo-cache-v1';
const ASSETS_TO_CACHE = [
    '/',
    '/static/styles.css',
    '/static/mobile-audit.css',
    '/static/app.js',
    '/static/manifest.json',
    '/static/favicon.ico',
    '/static/icon-192.png',
    '/static/icon-512.png',
    '/static/apple-touch-icon.png',
    '/static/tradexo_wordmark_dark_bg.png'
];

self.addEventListener('install', (event) => {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS_TO_CACHE).catch((err) => {
                console.warn('[TRADEXO SW] Pre-caching asset error (non-fatal):', err);
            });
        })
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Network-first with Cache fallback for app assets, network-only for API routes
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Never cache API or WebSocket requests
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) {
        return;
    }

    event.respondWith(
        fetch(event.request)
            .then((response) => {
                if (response && response.status === 200 && response.type === 'basic') {
                    const responseToCache = response.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseToCache);
                    });
                }
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});

// Handle Push Notifications for lock-screen mobile alerts
self.addEventListener('push', (event) => {
    let payload = {
        title: 'TRADEXO Institutional Alert',
        body: 'New High-Conviction Market Signal Detected',
        icon: '/static/icon-192.png',
        badge: '/static/favicon.png',
        tag: 'tradexo-signal',
        data: { url: '/' }
    };

    if (event.data) {
        try {
            const data = event.data.json();
            payload = { ...payload, ...data };
        } catch (e) {
            payload.body = event.data.text() || payload.body;
        }
    }

    const options = {
        body: payload.body,
        icon: payload.icon || '/static/icon-192.png',
        badge: payload.badge || '/static/favicon.png',
        vibrate: [200, 100, 200, 100, 200],
        tag: payload.tag || 'tradexo-alert',
        renotify: true,
        requireInteraction: true,
        data: payload.data || { url: '/' },
        actions: [
            { action: 'open_app', title: 'Open Dashboard' },
            { action: 'dismiss', title: 'Dismiss' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(payload.title, options)
    );
});

// Handle notification click to focus or open the app window
self.addEventListener('notificationclick', (event) => {
    event.notification.close();

    if (event.action === 'dismiss') {
        return;
    }

    const targetUrl = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (let i = 0; i < clientList.length; i++) {
                const client = clientList[i];
                if (client.url.includes(self.location.origin) && 'focus' in client) {
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
