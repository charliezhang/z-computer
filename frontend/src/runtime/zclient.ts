/**
 * Client-side Z-runtime. Builds the sandboxed iframe document for an app.
 *
 * Network isolation is enforced in three layers:
 *  1. The iframe `sandbox="allow-scripts"` attribute (AppFrame.tsx): null origin, no storage, no popups,
 *     no top-navigation, no forms.
 *  2. The Content-Security-Policy below: `default-src 'none'` + `connect-src 'none'` blocks fetch/XHR/WebSocket/
 *     EventSource/beacons and every external script, style, image, font, frame and form target. Only inline
 *     code and `data:`/`blob:` media (i.e. bundled assets) are allowed.
 *  3. The bootstrap intercepts link clicks and reports CSP violations to the host as sandbox errors.
 * The only way out is postMessage to the host (AppFrame.tsx), which owns the single WebSocket to the backend and
 * mediates the platform primitives (camera, speech, and reactToImage, which the host forwards over that
 * same WebSocket so the backend runs the AI call with the app's persisted prompt).
 */
export const CLIENT_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline'",
  "style-src 'unsafe-inline'",
  "img-src data: blob:",
  "media-src data: blob:",
  "font-src data:",
  "connect-src 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
].join('; ');

export function buildSrcdoc(clientJs: string, assets: Record<string, string>): string {
  const bootstrap = `
(function () {
  var handlers = [], readyHandlers = [], ready = false, pending = {}, nextId = 1;
  var assets = ${JSON.stringify(assets)};
  function call(name, args) {
    return new Promise(function (resolve, reject) {
      var id = nextId++;
      pending[id] = { resolve: resolve, reject: reject };
      parent.postMessage({ z: 'call', id: id, name: name, args: args || {} }, '*');
    });
  }
  window.Z = {
    send: function (d) { parent.postMessage({ z: 'msg', data: d === undefined ? null : d }, '*'); },
    onMessage: function (f) { handlers.push(f); },
    onReady: function (f) { if (ready) f(); else readyHandlers.push(f); },
    asset: function (n) { return assets[n] || ''; },
    takePicture: function (opts) { return call('takePicture', opts); },
    recognizeSpeech: function (opts) { return call('recognizeSpeech', opts); },
    reactToImage: function (image, promptId) { return call('reactToImage', { image: image, promptId: promptId }); }
  };
  window.addEventListener('message', function (e) {
    var m = e.data; if (!m || !m.z) return;
    if (m.z === 'msg') handlers.forEach(function (f) { f(m.data); });
    else if (m.z === 'ready' && !ready) { ready = true; readyHandlers.forEach(function (f) { f(); }); readyHandlers = []; }
    else if (m.z === 'result') {
      var p = pending[m.id]; if (!p) return; delete pending[m.id];
      if (m.ok) p.resolve(m.value); else p.reject(new Error(m.error));
    }
  });
  window.addEventListener('error', function (e) { parent.postMessage({ z: 'clienterror', message: String(e.message) }, '*'); });
  window.addEventListener('securitypolicyviolation', function (e) {
    parent.postMessage({ z: 'clienterror', message: 'Blocked by Z sandbox: ' + (e.blockedURI || e.violatedDirective) }, '*');
  });
  document.addEventListener('click', function (e) {
    var a = e.target && e.target.closest && e.target.closest('a[href]');
    if (a) e.preventDefault();
  }, true);
  parent.postMessage({ z: 'hello' }, '*');
})();`;
  const safe = (s: string) => s.replace(/<\/script/gi, '<\\/script');
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CLIENT_CSP}"><style>body{margin:0;font-family:sans-serif}</style></head><body><div id="app"></div><script>${safe(bootstrap)}</script><script>${safe(clientJs)}</script></body></html>`;
}
