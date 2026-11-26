// 負例の相方: Service Worker の skipWaiting()。見せ場を飛ばす手段ではない。
self.addEventListener('install', () => {
  self.skipWaiting();
});
