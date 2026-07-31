self.addEventListener('push', function (event) {
  let data = { title: 'OrderTogether', body: '' };
  try { data = event.data.json(); } catch (e) {}
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icon-180.png',
      badge: '/static/icon-180.png',
    })
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      if (list.length > 0) return list[0].focus();
      return clients.openWindow('/');
    })
  );
});
