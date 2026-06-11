// AlphaPilot 앱 셸 서비스워커 (Phase 6-4)
// 정적 자산만 캐시한다. API 응답은 토큰 보호를 위해 SW 캐시에 저장하지 않는다.
// (마지막 리포트 오프라인 열람은 앱의 localStorage API 캐시가 담당한다.)
const CACHE_NAME = "alphapilot-shell-v1";

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  // 같은 출처의 정적 자산만 처리한다. 백엔드 API(다른 출처)는 그대로 통과시킨다.
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      try {
        // 네트워크 우선: 배포 직후에도 최신 자산을 받는다.
        const fresh = await fetch(request);
        if (fresh.ok) cache.put(request, fresh.clone());
        return fresh;
      } catch (_error) {
        const cached = await cache.match(request);
        if (cached) return cached;
        if (request.mode === "navigate") {
          const shell =
            (await cache.match("./index.html")) || (await cache.match("./"));
          if (shell) return shell;
        }
        return Response.error();
      }
    }),
  );
});
