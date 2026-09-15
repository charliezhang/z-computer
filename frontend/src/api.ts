export type AppRow = {
  id: string; name: string; icon: string; status: 'draft' | 'published';
  agent_session_id: string | null; version: number | null; updated_at: string;
};
export type AppFiles = {
  manifest: { id: string; name: string; icon: string; description: string; version: number };
  client_js: string; server_js: string; assets: Record<string, string>;
};
export type Revision = { id: number; number: number; source: string; summary: string; created_at: string; name: string; icon: string; live: boolean };
export type RevisionDiff = { from: number; to: number; files: { name: string; diff: string }[] };
export type AgentEvent = { run_id: string; seq: number; ts: string; kind: string; payload: any };

export const getToken = () => sessionStorage.getItem('z_token') || '';
export const setToken = (t: string) => sessionStorage.setItem('z_token', t);

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Z-Token': getToken(), ...(init?.headers || {}) },
  });
  if (r.status === 401 && path !== '/api/auth') {
    sessionStorage.removeItem('z_token');
    location.reload();
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export function wsUrl(path: string, params: Record<string, string> = {}): string {
  const u = new URL(path, location.href);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.searchParams.set('token', getToken());
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return u.toString();
}
