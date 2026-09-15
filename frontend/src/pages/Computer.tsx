import { useEffect, useState } from 'react';
import { api, AppRow } from '../api';
import AppFrame from '../components/AppFrame';
import PasscodeGate from '../components/PasscodeGate';

/** Kid-facing thin client: lists published apps from Z-Studio and runs one at a time. */
export default function Computer() {
  return (
    <PasscodeGate>
      <Launcher />
    </PasscodeGate>
  );
}

function Launcher() {
  const [apps, setApps] = useState<AppRow[]>([]);
  const [open, setOpen] = useState<AppRow | null>(null);

  useEffect(() => {
    const load = () => api<AppRow[]>('/api/apps?published=1').then(setApps).catch(() => {});
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, []);

  if (open) {
    return (
      <div className="fullscreen">
        <div className="pane-head">
          <button className="btn secondary" onClick={() => setOpen(null)}>🏠 Home</button>
          <b>{open.icon} {open.name}</b>
        </div>
        <AppFrame appId={open.id} mode="published" />
      </div>
    );
  }
  return (
    <div className="computer">
      <h1 style={{ textAlign: 'center' }}>🧒 My Z-Computer</h1>
      <div className="grid">
        {apps.map((a) => (
          <button key={a.id} className="tile" onClick={() => setOpen(a)}>
            <span>{a.icon}</span>{a.name}
          </button>
        ))}
      </div>
      {apps.length === 0 && <p style={{ textAlign: 'center' }}>No apps published yet. Ask a creator to make one!</p>}
    </div>
  );
}
