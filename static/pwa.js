(function () {
  if (!("serviceWorker" in navigator)) return;
  const script = document.currentScript;
  const swUrl = (script && script.dataset.swUrl) || "/sw.js";
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(swUrl).catch((error) => {
      console.warn("PlaneRadar service worker registration failed", error);
    });
  });
})();
