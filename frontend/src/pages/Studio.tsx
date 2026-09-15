import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AgentEvent, api, AppFiles, AppRow, Revision, RevisionDiff, wsUrl } from '../api';
import AppFrame from '../components/AppFrame';
import PasscodeGate from '../components/PasscodeGate';

export default function Studio() {
  return (
    <PasscodeGate>
      <StudioInner />
    </PasscodeGate>
  );
}

function StudioInner() {
  const { appId } = useParams();
  const nav = useNavigate();
  const [apps, setApps] = useState<AppRow[]>([]);
  const loadApps = () => api<AppRow[]>('/api/apps').then(setApps);
  useEffect(() => { loadApps(); }, []);

  async function newApp() {
    const name = prompt('App name?', 'My App');
    if (!name) return;
    const a = await api<AppRow>('/api/apps', { method: 'POST', body: JSON.stringify({ name }) });
    await loadApps();
    nav(`/studio/${a.id}`);
  }

  return (
    <div className="studio">
      <div className="sidebar">
        <button className="btn secondary" onClick={() => nav('/')}>← Home</button>
        <h3>Z-Studio</h3>
        <button className="btn" style={{ width: '100%' }} onClick={newApp}>+ New app</button>
        <div style={{ marginTop: 12 }}>
          {apps.map((a) => (
            <button key={a.id} className={'app' + (a.id === appId ? ' active' : '')} onClick={() => nav(`/studio/${a.id}`)}>
              {a.icon} {a.name} {a.version ? <small>v{a.version}</small> : <small>draft</small>}
            </button>
          ))}
        </div>
      </div>
      {appId ? <Editor key={appId} appId={appId} onChanged={loadApps} /> : (
        <div className="pane" style={{ gridColumn: '2 / 4', alignItems: 'center', justifyContent: 'center' }}>
          <p>Pick an app or create a new one.</p>
        </div>
      )}
    </div>
  );
}

function Editor({ appId, onChanged }: { appId: string; onChanged: () => void }) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [live, setLive] = useState<Record<number, { block: string; text: string }>>({});
  const [files, setFiles] = useState<AppFiles | null>(null);
  const [tab, setTab] = useState<'preview' | 'history' | 'client.js' | 'server.js' | 'prompts.json' | 'manifest.json'>('preview');
  const [sourceOpen, setSourceOpen] = useState(false);
  const [versions, setVersions] = useState<Revision[]>([]);
  const [selectedRev, setSelectedRev] = useState<number | null>(null);
  const [diff, setDiff] = useState<RevisionDiff | null>(null);
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('claude-opus-5');
  const [effort, setEffort] = useState('high');
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [published, setPublished] = useState<number | null>(null);
  const traceRef = useRef<HTMLDivElement>(null);

  const loadFiles = () => api<AppFiles>(`/api/apps/${appId}/files`).then(setFiles);
  const loadVersions = () => api<Revision[]>(`/api/apps/${appId}/revisions`).then(setVersions);
  useEffect(() => {
    api<AgentEvent[]>(`/api/apps/${appId}/events`).then(setEvents);
    loadFiles();
    loadVersions();
  }, [appId]);
  useEffect(() => { traceRef.current?.scrollTo(0, traceRef.current.scrollHeight); }, [events, live]);

  function send() {
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setPrompt('');
    const ws = new WebSocket(wsUrl(`/ws/studio/${appId}`));
    ws.onopen = () => ws.send(JSON.stringify({ prompt: text, model, effort }));
    ws.onmessage = (e) => {
      const ev: AgentEvent = JSON.parse(e.data);
      if (ev.kind === 'delta') {
        // Live partial block; replaced by the persisted thinking/text event when the block completes.
        const { index, block, text } = ev.payload;
        setLive((prev) => ({ ...prev, [index]: { block, text: (prev[index]?.text || '') + text } }));
        return;
      }
      setLive({});
      setEvents((prev) => [...prev, ev]);
      if (ev.kind === 'result' || ev.kind === 'error') {
        ws.close();
        setBusy(false);
        loadFiles().then(() => setReloadKey((k) => k + 1));
        loadVersions();
        onChanged();
      }
    };
    ws.onerror = () => { setBusy(false); setLive({}); };
  }

  async function publish() {
    const r = await api<{ version: number }>(`/api/apps/${appId}/publish`, { method: 'POST' });
    setPublished(r.version);
    loadVersions();
    onChanged();
  }

  async function promote(number: number) {
    const r = await api<{ version: number }>(`/api/apps/${appId}/revisions/${number}/promote`, { method: 'POST' });
    setPublished(r.version);
    loadVersions();
    onChanged();
  }

  async function showDiff(from: number, to: number) {
    setDiff(await api<RevisionDiff>(`/api/apps/${appId}/revisions/${from}/diff/${to}`));
  }

  async function revert(number: number) {
    await api(`/api/apps/${appId}/revisions/${number}/revert`, { method: 'POST' });
    await Promise.all([loadFiles(), loadVersions()]);
    setReloadKey((k) => k + 1);
    onChanged();
  }

  return (
    <>
      <div className="pane">
        <div className="pane-head"><b>Z-Coder</b><span className="grow" />{busy && <small>working…</small>}</div>
        <div className="trace" ref={traceRef}>
          {events.map((e, i) => <EventRow key={i} e={e} />)}
          {Object.keys(live).map(Number).sort((a, b) => a - b).map((i) => live[i].block === 'thinking' ? (
            <details key={'live' + i} className="ev thinking live" open><summary>💭 thinking…</summary><pre>{live[i].text}<span className="cursor" /></pre></details>
          ) : (
            <div key={'live' + i} className="ev text live">{live[i].text}<span className="cursor" /></div>
          ))}
        </div>
        <div className="composer">
          <textarea placeholder="Describe the app you want, e.g. 'A 10-question times-table quiz for a 3rd grader'"
            value={prompt} onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <div className="composer-side">
            <select value={model} onChange={(e) => setModel(e.target.value)} title="Model">
              {MODELS.map((m) => <option key={m} value={m}>{m.replace('claude-', '')}</option>)}
            </select>
            <select value={effort} onChange={(e) => setEffort(e.target.value)} title="Effort">
              {EFFORTS.map((x) => <option key={x} value={x}>{x}</option>)}
            </select>
            <button className="btn" disabled={busy} onClick={send}>Send</button>
          </div>
        </div>
      </div>
      <div className="pane">
        <div className="pane-head tabs">
          <button className={tab === 'preview' ? 'active' : ''} onClick={() => setTab('preview')}>preview</button>
          <button className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>History</button>
          <button className={'source-toggle' + (sourceOpen ? ' open' : '')}
            onClick={() => { if (sourceOpen && tab !== 'preview' && tab !== 'history') setTab('preview'); setSourceOpen(!sourceOpen); }}>
            {sourceOpen ? '▾' : '▸'} Source
          </button>
          {sourceOpen && (['client.js', 'server.js', 'prompts.json', 'manifest.json'] as const).map((t) => (
            <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>
          ))}
          <span className="grow" />
          <button className="btn secondary" onClick={() => setReloadKey((k) => k + 1)}>↻ Reload</button>
          <button className="btn" onClick={publish}>Publish</button>
          {published && <small>v{published} live</small>}
        </div>
        {tab === 'preview' ? (
          <div className="preview"><AppFrame appId={appId} mode="draft" reloadKey={reloadKey} /></div>
        ) : tab === 'history' ? (
          diff ? (
          <div className="history diff-view">
            <div className="version-head">
              <b>Diff v{diff.from} → v{diff.to}</b><span className="grow" />
              <button className="btn secondary" onClick={() => setDiff(null)}>← Back</button>
            </div>
            {diff.files.filter((f) => f.diff).length === 0 && <p>No differences.</p>}
            {diff.files.filter((f) => f.diff).map((f) => (
              <div key={f.name} className="version">
                <b>{f.name}</b>
                <pre className="udiff">{f.diff.split('\n').map((line, i) => (
                  <div key={i} className={line.startsWith('+') ? 'add' : line.startsWith('-') ? 'del' : line.startsWith('@@') ? 'hunk' : ''}>{line || ' '}</div>
                ))}</pre>
              </div>
            ))}
          </div>
          ) : (
          <div className={'history' + (selectedRev !== null ? ' has-selection' : '')}>
            {versions.map((v, i) => {
              const sel = versions.find((x) => x.id === selectedRev);
              const isSel = v.id === selectedRev;
              return (
              <div key={v.id} className={'version' + (v.live ? ' live' : '') + (isSel ? ' selected' : '')}
                onClick={() => setSelectedRev(v.id)}>
                <div className="version-head">
                  <b>v{v.number}</b> {v.icon} {v.name}
                  <span className="badge">{v.source}</span>
                  {v.live && <span className="badge live">LIVE</span>}
                  {i === 0 && <span className="badge">draft</span>}
                  <span className="grow" />
                  {sel && !isSel && (
                    <button className="btn secondary diff-btn" title={`Diff v${sel.number} → v${v.number}`}
                      onClick={(e) => { e.stopPropagation(); showDiff(sel.number, v.number); }}>± Diff</button>
                  )}
                  {isSel && !v.live && (
                    <button className="btn promote-btn" title="Make this revision live"
                      onClick={(e) => { e.stopPropagation(); promote(v.number); }}>↑ Promote live</button>
                  )}
                  {i > 0 && <button className="btn secondary" onClick={(e) => { e.stopPropagation(); revert(v.number); }}>Revert to v{v.number}</button>}
                </div>
                <small>{new Date(v.created_at).toLocaleString()}</small>
                <div className="summary">{v.summary}</div>
              </div>
              );
            })}
          </div>
          )
        ) : (
          <pre className="code">{files ? (tab === 'manifest.json' ? JSON.stringify(files.manifest, null, 2) : tab === 'prompts.json' ? JSON.stringify(files.prompts, null, 2) : tab === 'client.js' ? files.client_js : files.server_js) : ''}</pre>
        )}
      </div>
    </>
  );
}

const MODELS = ['claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8', 'claude-opus-5', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-haiku-4-5'];
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];

function EventRow({ e }: { e: AgentEvent }) {
  const p = e.payload;
  switch (e.kind) {
    case 'user_prompt': return <div className="ev user_prompt">{p.text}{p.model && <small className="meta">{String(p.model).replace('claude-', '')} · {p.effort}</small>}</div>;
    case 'text': return <div className="ev text">{p.text}</div>;
    case 'thinking': return <details className="ev thinking"><summary>💭 thinking</summary><pre>{p.text}</pre></details>;
    case 'tool_use': {
      const f = p.input?.file_path ? String(p.input.file_path).split('/').pop() : p.input?.pattern || '';
      return <div className="ev tool_use">🔧 {p.name} {f}</div>;
    }
    case 'tool_result': return p.is_error ? <div className="ev error">tool error: {String(p.content).slice(0, 300)}</div> : null;
    case 'result': return <div className="ev result">✅ {p.is_error ? 'finished with errors' : 'done'} · {p.num_turns} turns · {(p.duration_ms / 1000).toFixed(1)}s{p.total_cost_usd != null ? ` · $${p.total_cost_usd.toFixed(3)}` : ''}</div>;
    case 'error': return <div className="ev error">⚠️ {p.message}</div>;
    default: return null;
  }
}
