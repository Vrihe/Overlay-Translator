/* Points the download button at the newest installer and shows its version and size.
   The HTML already links to /releases/latest, so when anything fails (offline, API rate
   limit, no matching asset) the page just keeps that default link. */
(function () {
  "use strict";

  var API = "https://api.github.com/repos/Vrihe/Overlay-Translator/releases/latest";
  var ASSET = /^TranslatorOverlay-Setup-.*\.exe$/;
  var HOST = "https://github.com/Vrihe/Overlay-Translator/releases/download/";
  var CACHE_KEY = "to-latest-release";
  var CACHE_MS = 10 * 60 * 1000;

  function formatSize(bytes) {
    var ru = (document.documentElement.lang || "").slice(0, 2) === "ru";
    var mb = bytes / (1024 * 1024);
    return mb.toFixed(mb >= 100 ? 0 : 1) + (ru ? " МБ" : " MB");
  }

  function each(selector, fn) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) fn(nodes[i]);
  }

  function size(info) { return info.bytes ? formatSize(info.bytes) : ""; }

  function apply(info) {
    each("[data-dl]", function (a) { a.href = info.url; });
    each("[data-dl-version]", function (el) { el.textContent = info.version; });
    each("[data-dl-size]", function (el) { el.textContent = size(info); });
    // The one-line "v1.2.3 · 95 MB" under the button text.
    each("[data-dl-meta]", function (el) {
      var sz = size(info);
      el.textContent = sz ? info.version + " · " + sz : info.version;
    });
  }

  function parse(release) {
    var assets = (release && release.assets) || [];
    for (var i = 0; i < assets.length; i++) {
      var a = assets[i];
      if (ASSET.test(a.name || "") && String(a.browser_download_url).indexOf(HOST) === 0) {
        var m = /^TranslatorOverlay-Setup-(.*)\.exe$/.exec(a.name);
        return {
          url: a.browser_download_url,
          version: "v" + (m ? m[1] : String(release.tag_name || "").replace(/^v/, "")),
          bytes: a.size > 0 ? a.size : 0
        };
      }
    }
    return null;
  }

  function cached() {
    try {
      var raw = JSON.parse(sessionStorage.getItem(CACHE_KEY));
      if (raw && Date.now() - raw.t < CACHE_MS) return raw.info;
    } catch (e) { /* storage blocked: ignore */ }
    return null;
  }

  function remember(info) {
    try {
      sessionStorage.setItem(CACHE_KEY, JSON.stringify({ t: Date.now(), info: info }));
    } catch (e) { /* ignore */ }
  }

  function run() {
    var hit = cached();
    if (hit) { apply(hit); return; }
    if (!window.fetch) return;

    var controller = window.AbortController ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 5000) : null;

    fetch(API, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller ? controller.signal : undefined
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (release) {
        var info = parse(release);
        if (info) { remember(info); apply(info); }
      })
      .catch(function () { /* keep the default link */ })
      .then(function () { if (timer) clearTimeout(timer); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();
