import { useEffect, useMemo, useRef, useState } from 'react';
import { api, AppFiles, wsUrl } from '../api';
import { buildSrcdoc } from '../runtime/zclient';
import { runPrimitive } from '../runtime/primitives';

/** Runtime host: sandboxed iframe (client.js) <-> postMessage <-> one WebSocket <-> server.js in QuickJS.
 *  Also executes platform primitives (camera, speech) on the app's behalf; see runtime/zclient.ts for the sandbox layers. */
export default function AppFrame({ appId, mode, reloadKey = 0 }: { appId: string; mode: 'draft' | 'published'; reloadKey?: number }) {
  const [files, setFiles] = useState<AppFiles | null>(null);
  const [err, setErr] = useState('');
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    let alive = true;
    setFiles(null);
    setErr('');
    api<AppFiles>(`/api/apps/${appId}/files?mode=${mode}`)
      .then((f) => alive && setFiles(f))
      .catch((e) => alive && setErr(String(e)));
    return () => { alive = false; };
  }, [appId, mode, reloadKey]);

  useEffect(() => {
    if (!files) return;
    const ws = new WebSocket(wsUrl(`/ws/app/${appId}`, { mode }));
    let wsOpen = false, frameReady = false;
    const frame = () => iframeRef.current?.contentWindow;
    const sendReady = () => { if (wsOpen && frameReady) frame()?.postMessage({ z: 'ready' }, '*'); };
    ws.onopen = () => { wsOpen = true; sendReady(); };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.type === 'msg') frame()?.postMessage({ z: 'msg', data: m.data }, '*');
      else if (m.type === 'error') setErr(m.message);
    };
    const onMsg = (e: MessageEvent) => {
      if (e.source !== frame()) return;
      const m = e.data;
      if (m?.z === 'hello') { frameReady = true; sendReady(); }
      else if (m?.z === 'msg' && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'msg', data: m.data }));
      else if (m?.z === 'clienterror') setErr('client.js error: ' + m.message);
      else if (m?.z === 'call') {
        runPrimitive(m.name, m.args).then(
          (value) => frame()?.postMessage({ z: 'result', id: m.id, ok: true, value }, '*'),
          (err) => frame()?.postMessage({ z: 'result', id: m.id, ok: false, error: String(err?.message || err) }, '*'),
        );
      }
    };
    window.addEventListener('message', onMsg);
    return () => { window.removeEventListener('message', onMsg); ws.close(); };
  }, [files, appId, mode]);

  const srcdoc = useMemo(() => (files ? buildSrcdoc(files.client_js, files.assets) : ''), [files]);

  return (
    <div className="frame-wrap">
      {files && <iframe ref={iframeRef} key={reloadKey} sandbox="allow-scripts" srcDoc={srcdoc} title={files.manifest.name} />}
      {err && <div className="frame-err">{err}</div>}
    </div>
  );
}
