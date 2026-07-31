self.addEventListener('push', function (event) {
  let data = { title: 'OrderTogether', body: '' };
  try { data = event.data.json(); } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon.svg',
      badge: '/static/icon.svg',
    })
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(clients.openWindow('/'));
});
