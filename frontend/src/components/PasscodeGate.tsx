import { FormEvent, ReactNode, useState } from 'react';
import { api, getToken, setToken } from '../api';

export default function PasscodeGate({ children }: { children: ReactNode }) {
  const [ok, setOk] = useState(!!getToken());
  const [code, setCode] = useState('');
  const [err, setErr] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    try {
      const r = await api<{ token: string }>('/api/auth', { method: 'POST', body: JSON.stringify({ passcode: code }) });
      setToken(r.token);
      setOk(true);
    } catch {
      setErr('Wrong passcode');
    }
  }

  if (ok) return <>{children}</>;
  return (
    <div className="center">
      <form className="card" onSubmit={submit}>
        <h1>Z-Computer</h1>
        <p>Enter the passcode</p>
        <input autoFocus value={code} onChange={(e) => setCode(e.target.value)} style={{ fontSize: 24, padding: 8, textAlign: 'center', width: 180 }} />
        <div style={{ marginTop: 12 }}><button className="btn" type="submit">Enter</button></div>
        {err && <p className="err">{err}</p>}
      </form>
    </div>
  );
}
