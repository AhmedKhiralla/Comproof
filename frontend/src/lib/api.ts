// JSON client for the Comproof API. Sends the CSRF header on every request.

export class ApiError extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  extra: Record<string, unknown>;
  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}, extra = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.extra = extra;
  }
}

type Listener = (err: ApiError) => void;
const authListeners = new Set<Listener>();
export function onAuthError(fn: Listener) {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

export async function api<T = any>(method: string, path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "comproof" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "network");
  }
  const text = await res.text();
  let data: any = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!res.ok) {
    const e = data?.error ?? {};
    const { code, message, fields, ...extra } = e;
    const err = new ApiError(res.status, code ?? "server_error", message ?? res.statusText, fields ?? {}, extra);
    if (res.status === 401 && path !== "/api/auth/login" && path !== "/api/auth/me") {
      authListeners.forEach((fn) => fn(err));
    }
    throw err;
  }
  return data as T;
}

export const get = <T = any>(path: string) => api<T>("GET", path);
export const post = <T = any>(path: string, body: unknown = {}) => api<T>("POST", path, body);
export const patch = <T = any>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const put = <T = any>(path: string, body: unknown) => api<T>("PUT", path, body);
export const del = <T = any>(path: string) => api<T>("DELETE", path);

export function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}
